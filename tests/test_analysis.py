"""analysis.py 테스트 (역할 4).

AWS 를 실제로 호출하지 않는다. boto3 클라이언트를 가짜로 바꿔 호출 순서·인자·오류 변환을 검사한다.
실사진 정확도는 여기서 측정하지 않는다(미측정).
"""

from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from backend.app import analysis
from backend.app.analysis import (
    AUTH_MESSAGE_KO,
    MODE_LIVE,
    MODE_MOCK,
    PROVIDER_MOCK,
    PROVIDER_REKOGNITION,
    AnalysisError,
    Settings,
    analyze,
    load_settings,
    validate_reference,
)
from tests.conftest import make_image


# --------------------------------------------------------------------------
# 가짜 Rekognition 클라이언트
# --------------------------------------------------------------------------
def box(left, top, width, height):
    return {"Left": left, "Top": top, "Width": width, "Height": height}


def face(bbox, *, sharpness=80.0, brightness=70.0, eyes_open=True, eyes_conf=99.0, confidence=99.5):
    return {
        "BoundingBox": bbox,
        "Confidence": confidence,
        "Quality": {"Sharpness": sharpness, "Brightness": brightness},
        "EyesOpen": {"Value": eyes_open, "Confidence": eyes_conf},
        "Smile": {"Value": True, "Confidence": 95.0},
    }


class FakeRekognition:
    def __init__(self, *, faces=None, compare=None, labels=None, errors=None):
        self._faces = faces if faces is not None else []
        self._compare = compare or {}  # source key -> FaceMatches
        self._labels = labels or []
        self._errors = errors or {}
        self.calls: list[tuple[str, dict]] = []

    def _maybe_raise(self, op, kwargs):
        error = self._errors.get(op)
        if callable(error):
            error = error(kwargs)
        if error is not None:
            raise error

    def detect_faces(self, **kwargs):
        self.calls.append(("detect_faces", kwargs))
        self._maybe_raise("detect_faces", kwargs)
        return {"FaceDetails": list(self._faces)}

    def compare_faces(self, **kwargs):
        self.calls.append(("compare_faces", kwargs))
        self._maybe_raise("compare_faces", kwargs)
        source = kwargs["SourceImage"]
        key = source.get("S3Object", {}).get("Name") if "S3Object" in source else source["Bytes"]
        return {"FaceMatches": list(self._compare.get(key, []))}

    def detect_labels(self, **kwargs):
        self.calls.append(("detect_labels", kwargs))
        self._maybe_raise("detect_labels", kwargs)
        return {"Labels": list(self._labels)}

    def ops(self):
        return [name for name, _ in self.calls]


@pytest.fixture
def live_settings():
    return Settings(
        provider=PROVIDER_REKOGNITION,
        region="us-east-1",
        similarity_threshold=90.0,
        candidate_margin=5.0,
        manifest_path=analysis._DEFAULT_MANIFEST,
        mock_synthetic_match=True,
    )


@pytest.fixture
def use_fake(monkeypatch):
    def _install(client):
        monkeypatch.setattr(analysis, "_rekognition_client", lambda region: client)
        return client

    return _install


# --------------------------------------------------------------------------
# 설정
# --------------------------------------------------------------------------
def test_default_provider_is_mock():
    assert load_settings({}).provider == PROVIDER_MOCK


def test_invalid_provider_is_rejected_not_silently_defaulted():
    with pytest.raises(AnalysisError) as err:
        load_settings({"FACE_PROVIDER": "openai"})
    assert err.value.code == "CONFIG_INVALID"
    assert err.value.retryable is False


def test_candidate_threshold_is_widened_by_margin():
    settings = load_settings({"SIMILARITY_THRESHOLD": "90", "CANDIDATE_MARGIN": "5"})
    assert settings.candidate_threshold == 85.0


# --------------------------------------------------------------------------
# validate_reference
# --------------------------------------------------------------------------
def test_validate_reference_ok(jpeg_bytes, live_settings, use_fake):
    client = use_fake(FakeRekognition(faces=[face(box(0.1, 0.1, 0.2, 0.2))]))
    result = validate_reference(jpeg_bytes, settings=live_settings)
    assert result == {
        "provider": PROVIDER_REKOGNITION,
        "mode": MODE_LIVE,
        "face_count": 1,
        "elapsed_ms": result["elapsed_ms"],
    }
    assert client.calls[0][1]["Attributes"] == ["DEFAULT"]


def test_validate_reference_no_face(jpeg_bytes, live_settings, use_fake):
    use_fake(FakeRekognition(faces=[]))
    with pytest.raises(AnalysisError) as err:
        validate_reference(jpeg_bytes, settings=live_settings)
    assert err.value.code == "NO_FACE"
    assert err.value.retryable is False


def test_validate_reference_multiple_faces_has_distinct_code(jpeg_bytes, live_settings, use_fake):
    use_fake(FakeRekognition(faces=[face(box(0.1, 0.1, 0.2, 0.2)), face(box(0.5, 0.1, 0.2, 0.2))]))
    with pytest.raises(AnalysisError) as err:
        validate_reference(jpeg_bytes, settings=live_settings)
    assert err.value.code == "MULTIPLE_FACES"
    assert err.value.code != "NO_FACE"
    assert err.value.details["face_count"] == 2


# --------------------------------------------------------------------------
# analyze — 호출 순서
# --------------------------------------------------------------------------
def test_detect_faces_called_before_compare_faces(jpeg_bytes, live_settings, use_fake):
    client = use_fake(
        FakeRekognition(
            faces=[face(box(0.1, 0.1, 0.2, 0.2))],
            compare={b"ref-a": [{"Similarity": 97.0, "Face": {"BoundingBox": box(0.1, 0.1, 0.2, 0.2)}}]},
        )
    )
    analyze(jpeg_bytes, "album-1", [{"id": "m1", "reference_bytes": _ref(b"ref-a")}], settings=live_settings)
    ops = client.ops()
    assert ops.index("detect_faces") < ops.index("compare_faces")
    assert ops[-1] == "detect_labels"


def test_no_face_image_skips_compare_faces(jpeg_bytes, live_settings, use_fake):
    client = use_fake(FakeRekognition(faces=[], labels=[{"Name": "Beach", "Confidence": 99.0}]))
    result = analyze(jpeg_bytes, "album-1", [{"id": "m1", "reference_bytes": _ref(b"ref-a")}], settings=live_settings)

    assert "compare_faces" not in client.ops()
    assert result["calls"]["compare_faces"] == 0
    assert result["face_count"] == 0
    assert result["shot_type"] == "no_face"
    assert result["faces"] == []
    assert result["tags"] == ["바다"]


def test_compare_faces_uses_widened_threshold_and_auto_quality_filter(jpeg_bytes, live_settings, use_fake):
    client = use_fake(FakeRekognition(faces=[face(box(0.1, 0.1, 0.2, 0.2))]))
    analyze(jpeg_bytes, "a", [{"id": "m1", "reference_bytes": _ref(b"ref-a")}], settings=live_settings)
    _, kwargs = next(c for c in client.calls if c[0] == "compare_faces")
    assert kwargs["SimilarityThreshold"] == 85.0
    assert kwargs["QualityFilter"] == "AUTO"


# --------------------------------------------------------------------------
# analyze — 매칭 판정
# --------------------------------------------------------------------------
def test_solo_match_is_confirmed(jpeg_bytes, live_settings, use_fake):
    ref = _ref(b"ref-a")
    use_fake(
        FakeRekognition(
            faces=[face(box(0.1, 0.1, 0.2, 0.2))],
            compare={ref: [{"Similarity": 97.5, "Face": {"BoundingBox": box(0.1, 0.1, 0.2, 0.2)}}]},
        )
    )
    result = analyze(jpeg_bytes, "a", [{"id": "m1", "reference_bytes": ref}], settings=live_settings)
    assert result["shot_type"] == "solo"
    assert result["faces"][0]["member_id"] == "m1"
    assert result["faces"][0]["status"] == "matched"
    assert result["faces"][0]["uncertain"] is False
    assert result["matched_member_ids"] == ["m1"]
    assert result["mode"] == MODE_LIVE


def test_two_faces_is_group(jpeg_bytes, live_settings, use_fake):
    use_fake(FakeRekognition(faces=[face(box(0.1, 0.1, 0.2, 0.2)), face(box(0.6, 0.1, 0.2, 0.2))]))
    result = analyze(jpeg_bytes, "a", [], settings=live_settings)
    assert result["face_count"] == 2
    assert result["shot_type"] == "group"
    assert all(f["status"] == "unregistered" for f in result["faces"])


def test_ambiguous_match_is_left_uncertain(jpeg_bytes, live_settings, use_fake):
    """1위 93, 2위 91 -> 차이 2 < MARGIN 5 이므로 억지로 배정하지 않는다."""
    target = box(0.1, 0.1, 0.2, 0.2)
    ref_a, ref_b = _ref(b"ref-a"), _ref(b"ref-b")
    use_fake(
        FakeRekognition(
            faces=[face(target)],
            compare={
                ref_a: [{"Similarity": 93.0, "Face": {"BoundingBox": target}}],
                ref_b: [{"Similarity": 91.0, "Face": {"BoundingBox": target}}],
            },
        )
    )
    result = analyze(
        jpeg_bytes,
        "a",
        [{"id": "m1", "reference_bytes": ref_a}, {"id": "m2", "reference_bytes": ref_b}],
        settings=live_settings,
    )
    entry = result["faces"][0]
    assert entry["member_id"] is None
    assert entry["uncertain"] is True
    assert entry["status"] == "uncertain"
    assert [c["member_id"] for c in entry["candidates"]] == ["m1", "m2"]
    assert result["matched_member_ids"] == []


def test_below_threshold_candidate_is_not_assigned(jpeg_bytes, live_settings, use_fake):
    """후보 임계(85)는 넘었지만 확정 임계(90) 미만이면 확정하지 않는다."""
    target = box(0.1, 0.1, 0.2, 0.2)
    ref = _ref(b"ref-a")
    use_fake(
        FakeRekognition(
            faces=[face(target)],
            compare={ref: [{"Similarity": 86.0, "Face": {"BoundingBox": target}}]},
        )
    )
    result = analyze(jpeg_bytes, "a", [{"id": "m1", "reference_bytes": ref}], settings=live_settings)
    assert result["faces"][0]["member_id"] is None
    assert result["faces"][0]["uncertain"] is True


def test_low_iou_match_is_ignored(jpeg_bytes, live_settings, use_fake):
    """매치 박스가 탐지된 얼굴과 겹치지 않으면(IoU < 0.4) 버린다."""
    ref = _ref(b"ref-a")
    use_fake(
        FakeRekognition(
            faces=[face(box(0.1, 0.1, 0.2, 0.2))],
            compare={ref: [{"Similarity": 99.0, "Face": {"BoundingBox": box(0.7, 0.7, 0.2, 0.2)}}]},
        )
    )
    result = analyze(jpeg_bytes, "a", [{"id": "m1", "reference_bytes": ref}], settings=live_settings)
    assert result["faces"][0]["member_id"] is None
    assert result["faces"][0]["status"] == "unregistered"


def test_same_member_is_not_assigned_to_two_faces(jpeg_bytes, live_settings, use_fake):
    face_a, face_b = box(0.1, 0.1, 0.2, 0.2), box(0.6, 0.1, 0.2, 0.2)
    ref = _ref(b"ref-a")
    use_fake(
        FakeRekognition(
            faces=[face(face_a), face(face_b)],
            compare={
                ref: [
                    {"Similarity": 97.0, "Face": {"BoundingBox": face_a}},
                    {"Similarity": 95.0, "Face": {"BoundingBox": face_b}},
                ]
            },
        )
    )
    result = analyze(jpeg_bytes, "a", [{"id": "m1", "reference_bytes": ref}], settings=live_settings)
    assigned = [f["member_id"] for f in result["faces"]]
    assert assigned.count("m1") == 1
    assert result["matched_member_ids"] == ["m1"]
    # 밀려난 얼굴은 확정되지 않는다
    assert any(f["member_id"] is None for f in result["faces"])


# --------------------------------------------------------------------------
# analyze — 태그
# --------------------------------------------------------------------------
def test_labels_are_mapped_filtered_and_deduped(jpeg_bytes, live_settings, use_fake):
    use_fake(
        FakeRekognition(
            faces=[],
            labels=[
                {"Name": "Sea", "Confidence": 99.0},
                {"Name": "Ocean", "Confidence": 98.0},
                {"Name": "Person", "Confidence": 99.0},
                {"Name": "Hamburger", "Confidence": 97.0},
                {"Name": "Sunset", "Confidence": 91.0},
            ],
        )
    )
    result = analyze(jpeg_bytes, "a", [], settings=live_settings)
    assert result["tags"] == ["바다", "노을"]


def test_detect_labels_uses_contract_parameters(jpeg_bytes, live_settings, use_fake):
    client = use_fake(FakeRekognition(faces=[]))
    analyze(jpeg_bytes, "a", [], settings=live_settings)
    _, kwargs = next(c for c in client.calls if c[0] == "detect_labels")
    assert kwargs["MaxLabels"] == 30
    assert kwargs["MinConfidence"] == 80


# --------------------------------------------------------------------------
# analyze — 오류 변환
# --------------------------------------------------------------------------
def _client_error(code, message="raw aws detail with arn:aws:iam::123:user/secret"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "DetectFaces")


def test_access_denied_is_non_retryable_and_message_is_masked(jpeg_bytes, live_settings, use_fake):
    use_fake(FakeRekognition(errors={"detect_faces": _client_error("AccessDeniedException")}))
    with pytest.raises(AnalysisError) as err:
        analyze(jpeg_bytes, "a", [], settings=live_settings)
    assert err.value.code == "AWS_AUTH"
    assert err.value.retryable is False
    assert err.value.message_ko == AUTH_MESSAGE_KO
    assert "arn:aws:iam" not in json.dumps(err.value.to_dict(), ensure_ascii=False)


def test_no_credentials_does_not_fall_back_to_mock(jpeg_bytes, live_settings, use_fake):
    use_fake(FakeRekognition(errors={"detect_faces": NoCredentialsError()}))
    with pytest.raises(AnalysisError) as err:
        analyze(jpeg_bytes, "a", [], settings=live_settings)
    assert err.value.code == "AWS_AUTH"
    assert err.value.retryable is False


def test_throttling_is_retryable(jpeg_bytes, live_settings, use_fake):
    use_fake(FakeRekognition(errors={"detect_faces": _client_error("ThrottlingException")}))
    with pytest.raises(AnalysisError) as err:
        analyze(jpeg_bytes, "a", [], settings=live_settings)
    assert err.value.retryable is True
    assert err.value.code == "AWS_THROTTLED"


def test_internal_server_error_is_retryable(jpeg_bytes, live_settings, use_fake):
    use_fake(FakeRekognition(errors={"detect_faces": _client_error("InternalServerError")}))
    with pytest.raises(AnalysisError) as err:
        analyze(jpeg_bytes, "a", [], settings=live_settings)
    assert err.value.retryable is True


def test_connection_error_is_retryable(jpeg_bytes, live_settings, use_fake):
    use_fake(
        FakeRekognition(errors={"detect_faces": EndpointConnectionError(endpoint_url="https://rekognition")})
    )
    with pytest.raises(AnalysisError) as err:
        analyze(jpeg_bytes, "a", [], settings=live_settings)
    assert err.value.code == "AWS_UNAVAILABLE"
    assert err.value.retryable is True


def test_member_with_faceless_reference_is_skipped_not_fatal(jpeg_bytes, live_settings, use_fake):
    target = box(0.1, 0.1, 0.2, 0.2)
    good_ref, bad_ref = _ref(b"good"), _ref(b"bad")

    def compare_error(kwargs):
        if kwargs["SourceImage"].get("Bytes") == bad_ref:
            return ClientError(
                {"Error": {"Code": "InvalidParameterException", "Message": "no face in source"}},
                "CompareFaces",
            )
        return None

    use_fake(
        FakeRekognition(
            faces=[face(target)],
            compare={good_ref: [{"Similarity": 98.0, "Face": {"BoundingBox": target}}]},
            errors={"compare_faces": compare_error},
        )
    )
    result = analyze(
        jpeg_bytes,
        "a",
        [{"id": "bad", "reference_bytes": bad_ref}, {"id": "good", "reference_bytes": good_ref}],
        settings=live_settings,
    )
    assert result["matched_member_ids"] == ["good"]
    assert result["skipped_members"] == [{"member_id": "bad", "reason": "INVALID_PARAMETER"}]


def test_member_without_reference_is_skipped(jpeg_bytes, live_settings, use_fake):
    use_fake(FakeRekognition(faces=[face(box(0.1, 0.1, 0.2, 0.2))]))
    result = analyze(jpeg_bytes, "a", [{"id": "m1"}], settings=live_settings)
    assert result["skipped_members"] == [{"member_id": "m1", "reason": "NO_REFERENCE"}]
    assert result["calls"]["compare_faces"] == 0


def test_orm_style_member_object_is_accepted(jpeg_bytes, live_settings, use_fake):
    """worker 는 dict 가 아니라 SQLAlchemy Member 객체를 그대로 넘긴다."""

    class Member:  # ORM 객체 흉내 (속성 접근만 지원)
        def __init__(self, id, reference_key):
            self.id = id
            self.reference_key = reference_key
            self.reference_indexed = True

    target = box(0.1, 0.1, 0.2, 0.2)
    ref = _ref(b"ref-a")
    client = use_fake(
        FakeRekognition(
            faces=[face(target)],
            compare={ref: [{"Similarity": 98.0, "Face": {"BoundingBox": target}}]},
        )
    )
    result = analyze(
        jpeg_bytes,
        "album-1",
        [Member("m1", "albums/a/members/m1/reference.jpg")],
        settings=live_settings,
        load_reference=lambda key: ref,
    )
    assert result["matched_member_ids"] == ["m1"]
    _, kwargs = next(c for c in client.calls if c[0] == "compare_faces")
    assert kwargs["SourceImage"] == {"Bytes": ref}


def test_member_without_bucket_or_loader_is_skipped_with_clear_reason(jpeg_bytes, live_settings, use_fake):
    """STORAGE_BACKEND=local 처럼 S3 버킷이 없고 로더도 없으면 그 멤버만 건너뛴다."""
    use_fake(FakeRekognition(faces=[face(box(0.1, 0.1, 0.2, 0.2))]))
    result = analyze(
        jpeg_bytes,
        "album-1",
        [{"id": "m1", "reference_key": "albums/a/members/m1/reference.jpg"}],
        settings=live_settings,
    )
    assert result["skipped_members"] == [{"member_id": "m1", "reason": "NO_REFERENCE_BUCKET"}]
    assert result["face_count"] == 1  # 사진 분석 자체는 계속된다


def test_reference_loader_failure_skips_only_that_member(jpeg_bytes, live_settings, use_fake):
    target = box(0.1, 0.1, 0.2, 0.2)
    good_ref = _ref(b"good")

    def loader(key):
        if key.endswith("bad.jpg"):
            raise FileNotFoundError(key)
        return good_ref

    use_fake(
        FakeRekognition(
            faces=[face(target)],
            compare={good_ref: [{"Similarity": 98.0, "Face": {"BoundingBox": target}}]},
        )
    )
    result = analyze(
        jpeg_bytes,
        "album-1",
        [{"id": "bad", "reference_key": "bad.jpg"}, {"id": "good", "reference_key": "good.jpg"}],
        settings=live_settings,
        load_reference=loader,
    )
    assert result["matched_member_ids"] == ["good"]
    assert result["skipped_members"] == [{"member_id": "bad", "reason": "REFERENCE_LOAD_FAILED"}]


def test_member_reference_via_s3_is_used(jpeg_bytes, live_settings, use_fake):
    target = box(0.1, 0.1, 0.2, 0.2)
    client = use_fake(
        FakeRekognition(
            faces=[face(target)],
            compare={"refs/m1.jpg": [{"Similarity": 98.0, "Face": {"BoundingBox": target}}]},
        )
    )
    result = analyze(
        jpeg_bytes,
        "a",
        [{"id": "m1", "reference_bucket": "kmu-proj-06-zzik", "reference_key": "refs/m1.jpg"}],
        settings=live_settings,
    )
    _, kwargs = next(c for c in client.calls if c[0] == "compare_faces")
    assert kwargs["SourceImage"] == {"S3Object": {"Bucket": "kmu-proj-06-zzik", "Name": "refs/m1.jpg"}}
    assert result["matched_member_ids"] == ["m1"]


# --------------------------------------------------------------------------
# mock 제공자
# --------------------------------------------------------------------------
def test_mock_is_deterministic_and_marks_mode(jpeg_bytes):
    settings = load_settings({"FACE_PROVIDER": "mock"})
    first = analyze(jpeg_bytes, "a", [{"id": "m1"}], settings=settings)
    second = analyze(jpeg_bytes, "a", [{"id": "m1"}], settings=settings)

    for key in ("faces", "face_count", "shot_type", "tags", "quality", "best_score"):
        assert first[key] == second[key]
    assert first["provider"] == PROVIDER_MOCK
    assert first["mode"] == MODE_MOCK
    assert first["calls"]["total"] == 0


def test_mock_never_calls_aws(monkeypatch, jpeg_bytes):
    def explode(region):
        raise AssertionError("mock 모드가 AWS 클라이언트를 만들면 안 된다")

    monkeypatch.setattr(analysis, "_rekognition_client", explode)
    settings = load_settings({"FACE_PROVIDER": "mock"})
    analyze(jpeg_bytes, "a", [{"id": "m1"}], settings=settings)
    validate_reference(jpeg_bytes, settings=settings)


def test_mock_unregistered_image_is_flagged_synthetic(jpeg_bytes):
    settings = load_settings({"FACE_PROVIDER": "mock"})
    result = analyze(jpeg_bytes, "a", [{"id": "m1"}], settings=settings)
    assert result["mock_source"] == "synthetic"
    assert result["warnings"]
    assert all(f.get("synthetic") is True for f in result["faces"])


def test_mock_synthetic_match_can_be_disabled(jpeg_bytes):
    settings = load_settings({"FACE_PROVIDER": "mock", "MOCK_SYNTHETIC_MATCH": "0"})
    result = analyze(jpeg_bytes, "a", [{"id": "m1"}, {"id": "m2"}], settings=settings)
    assert result["matched_member_ids"] == []
    assert all(f["member_id"] is None for f in result["faces"])


def test_mock_manifest_entry_is_used(tmp_path, jpeg_bytes):
    from backend.app.quality import inspect_image

    digest = inspect_image(jpeg_bytes).content_hash
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": {
                    digest: {
                        "label": "합성 테스트 이미지",
                        "source": "테스트에서 Pillow로 생성",
                        "license": "자체 생성",
                        "face_count": 2,
                        "tags": ["바다"],
                        "quality": {"sharpness": 80.0, "brightness": 60.0, "eyes_open_ratio": 1.0},
                        "member_slots": [0, 1],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings({"FACE_PROVIDER": "mock", "MOCK_MANIFEST_PATH": str(manifest)})
    result = analyze(jpeg_bytes, "a", [{"id": "m1"}, {"id": "m2"}], settings=settings)

    assert result["mock_source"] == "manifest"
    assert result["face_count"] == 2
    assert result["shot_type"] == "group"
    assert result["tags"] == ["바다"]
    assert result["matched_member_ids"] == ["m1", "m2"]
    assert all("synthetic" not in f for f in result["faces"])
    # 80*0.5 + 1.0*100*0.4 + 60*0.1 = 86.0
    assert result["best_score"] == 86.0


def test_mock_manifest_member_slot_can_be_null(tmp_path, jpeg_bytes):
    """manifest 의 member_slots 는 null 을 담을 수 있다 ("이 얼굴은 등록 멤버가 아님")."""
    from backend.app.quality import inspect_image

    digest = inspect_image(jpeg_bytes).content_hash
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"samples": {digest: {"face_count": 3, "tags": [], "member_slots": [0, None, 1]}}}
        ),
        encoding="utf-8",
    )
    settings = load_settings({"FACE_PROVIDER": "mock", "MOCK_MANIFEST_PATH": str(manifest)})
    result = analyze(jpeg_bytes, "a", [{"id": "m1"}, {"id": "m2"}], settings=settings)

    assert [face["member_id"] for face in result["faces"]] == ["m1", None, "m2"]
    assert result["faces"][1]["status"] == "unregistered"
    assert result["matched_member_ids"] == ["m1", "m2"]


def test_mock_manifest_out_of_range_slot_is_not_assigned(tmp_path, jpeg_bytes):
    from backend.app.quality import inspect_image

    digest = inspect_image(jpeg_bytes).content_hash
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"samples": {digest: {"face_count": 2, "member_slots": [0, 9]}}}),
        encoding="utf-8",
    )
    settings = load_settings({"FACE_PROVIDER": "mock", "MOCK_MANIFEST_PATH": str(manifest)})
    result = analyze(jpeg_bytes, "a", [{"id": "m1"}], settings=settings)

    assert [face["member_id"] for face in result["faces"]] == ["m1", None]


def test_mock_manifest_can_express_no_face_and_multiple_faces(tmp_path):
    from backend.app.quality import inspect_image

    no_face_img = make_image(color=(10, 10, 10))
    many_img = make_image(color=(200, 10, 10))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": {
                    inspect_image(no_face_img).content_hash: {"face_count": 0, "tags": []},
                    inspect_image(many_img).content_hash: {"face_count": 3, "tags": []},
                }
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings({"FACE_PROVIDER": "mock", "MOCK_MANIFEST_PATH": str(manifest)})

    with pytest.raises(AnalysisError) as no_face:
        validate_reference(no_face_img, settings=settings)
    assert no_face.value.code == "NO_FACE"

    with pytest.raises(AnalysisError) as many:
        validate_reference(many_img, settings=settings)
    assert many.value.code == "MULTIPLE_FACES"

    assert analyze(no_face_img, "a", [], settings=settings)["shot_type"] == "no_face"


# --------------------------------------------------------------------------
# 계약 형태
# --------------------------------------------------------------------------
@pytest.mark.parametrize("provider", [PROVIDER_MOCK, PROVIDER_REKOGNITION])
def test_analyze_returns_contract_keys(provider, jpeg_bytes, live_settings, use_fake, monkeypatch):
    if provider == PROVIDER_REKOGNITION:
        use_fake(FakeRekognition(faces=[face(box(0.1, 0.1, 0.2, 0.2))]))
        settings = live_settings
    else:
        settings = load_settings({"FACE_PROVIDER": "mock"})

    result = analyze(jpeg_bytes, "album-1", [], settings=settings)
    for key in (
        "faces",
        "face_count",
        "shot_type",
        "tags",
        "quality",
        "best_score",
        "provider",
        "mode",
        "calls",
        "elapsed_ms",
    ):
        assert key in result, key
    assert set(result["quality"]) == {"sharpness", "brightness", "eyes_open_ratio"}
    assert result["shot_type"] in {"unknown", "no_face", "solo", "group"}


def _ref(marker: bytes) -> bytes:
    """기준 셀카 바이트. 가짜 클라이언트는 이 바이트를 키로 매치를 찾는다."""
    return make_image(width=200, height=200, color=(marker[0] % 250, marker[-1] % 250, 100))

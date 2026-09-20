"""FACE_PROVIDER=local 통합 테스트 (역할 4).

test_analysis.py 의 FakeRekognition 패턴과 같은 생각이다: 진짜 모델을 부르지
않고 backend.app.local_vision 의 세 함수(detect_faces/compare_faces/detect_labels)를
가짜로 바꿔서, analysis._analyze_local 이 _resolve_faces/_best_iou_face 같은
공용 판정 로직을 rekognition 경로와 똑같이 재사용하는지만 검사한다.
local_vision 자체의 얼굴 인식 정확도는 test_local_vision.py 와 이 세션에서 실사진으로
수동 검증했다(Wikimedia 공개 인물 사진, 저장소에는 커밋하지 않음) — 여기서는 안 본다.
"""

from __future__ import annotations

import pytest

from backend.app import analysis
from backend.app.analysis import (
    MODE_LIVE,
    PROVIDER_LOCAL,
    AnalysisError,
    Settings,
    analyze,
    load_settings,
    validate_reference,
)
from tests.conftest import make_image


def box(left, top, width, height):
    return {"Left": left, "Top": top, "Width": width, "Height": height}


def face(bbox, *, confidence=95.0):
    return {
        "BoundingBox": bbox,
        "Confidence": confidence,
        "Quality": {"Sharpness": 70.0, "Brightness": 60.0},
        "EyesOpen": {"Value": True, "Confidence": 96.0},
    }


class FakeLocalVision:
    def __init__(self, *, faces=None, compare=None, labels=None, detect_faces_error=None, compare_error=None):
        self._faces = faces if faces is not None else []
        self._compare = compare or {}  # source bytes -> FaceMatches
        self._labels = labels or []
        self._detect_faces_error = detect_faces_error
        self._compare_error = compare_error
        self.calls: list[tuple[str, dict]] = []

    def detect_faces(self, image_bytes):
        self.calls.append(("detect_faces", {"image_bytes": image_bytes}))
        if self._detect_faces_error is not None:
            raise self._detect_faces_error
        return list(self._faces)

    def compare_faces(self, source_bytes, target_bytes, similarity_threshold):
        self.calls.append(
            (
                "compare_faces",
                {"source_bytes": source_bytes, "target_bytes": target_bytes, "similarity_threshold": similarity_threshold},
            )
        )
        if callable(self._compare_error):
            error = self._compare_error(source_bytes)
            if error is not None:
                raise error
        return list(self._compare.get(source_bytes, []))

    def detect_labels(self, image_bytes, *, min_confidence=80.0, face_boxes=None):
        self.calls.append(("detect_labels", {"min_confidence": min_confidence, "face_boxes": face_boxes}))
        return list(self._labels)

    def ops(self):
        return [name for name, _ in self.calls]


@pytest.fixture
def local_settings():
    return Settings(
        provider=PROVIDER_LOCAL,
        region="us-east-1",
        similarity_threshold=90.0,
        candidate_margin=5.0,
        manifest_path=analysis._DEFAULT_MANIFEST,
        mock_synthetic_match=True,
    )


@pytest.fixture
def use_fake(monkeypatch):
    def _install(fake):
        monkeypatch.setattr(analysis, "local_vision", fake)
        return fake

    return _install


def _ref(marker: bytes) -> bytes:
    return make_image(width=200, height=200, color=(marker[0] % 250, marker[-1] % 250, 100))


def test_default_provider_stays_mock_local_is_opt_in():
    assert load_settings({}).provider != PROVIDER_LOCAL
    assert load_settings({"FACE_PROVIDER": "local"}).provider == PROVIDER_LOCAL


def test_validate_reference_uses_local_vision_and_reports_live_mode(jpeg_bytes, local_settings, use_fake):
    use_fake(FakeLocalVision(faces=[face(box(0.1, 0.1, 0.2, 0.2))]))
    result = validate_reference(jpeg_bytes, settings=local_settings)
    assert result["provider"] == PROVIDER_LOCAL
    assert result["mode"] == MODE_LIVE  # mock 이 아니다 — 진짜(로컬) 분석이라 '샘플' 배지가 뜨면 안 된다


def test_validate_reference_no_face_and_multiple_faces(jpeg_bytes, local_settings, use_fake):
    use_fake(FakeLocalVision(faces=[]))
    with pytest.raises(AnalysisError) as err:
        validate_reference(jpeg_bytes, settings=local_settings)
    assert err.value.code == "NO_FACE"

    use_fake(FakeLocalVision(faces=[face(box(0.1, 0.1, 0.2, 0.2)), face(box(0.5, 0.1, 0.2, 0.2))]))
    with pytest.raises(AnalysisError) as err:
        validate_reference(jpeg_bytes, settings=local_settings)
    assert err.value.code == "MULTIPLE_FACES"


def test_detect_faces_called_before_compare_faces(jpeg_bytes, local_settings, use_fake):
    ref = _ref(b"ref-a")
    fake = use_fake(
        FakeLocalVision(
            faces=[face(box(0.1, 0.1, 0.2, 0.2))],
            compare={ref: [{"Similarity": 97.0, "Face": {"BoundingBox": box(0.1, 0.1, 0.2, 0.2)}}]},
        )
    )
    analyze(jpeg_bytes, "album-1", [{"id": "m1", "reference_bytes": ref}], settings=local_settings)
    ops = fake.ops()
    assert ops.index("detect_faces") < ops.index("compare_faces")
    assert ops[-1] == "detect_labels"


def test_no_face_image_skips_compare_faces(jpeg_bytes, local_settings, use_fake):
    use_fake(FakeLocalVision(faces=[], labels=[{"Name": "Sea", "Confidence": 99.0}]))
    result = analyze(jpeg_bytes, "album-1", [{"id": "m1", "reference_bytes": _ref(b"ref-a")}], settings=local_settings)
    assert result["calls"]["compare_faces"] == 0
    assert result["face_count"] == 0
    assert result["shot_type"] == "no_face"
    assert result["tags"] == ["바다"]
    assert result["provider"] == PROVIDER_LOCAL
    assert result["mode"] == MODE_LIVE


def test_solo_match_is_confirmed(jpeg_bytes, local_settings, use_fake):
    ref = _ref(b"ref-a")
    use_fake(
        FakeLocalVision(
            faces=[face(box(0.1, 0.1, 0.2, 0.2))],
            compare={ref: [{"Similarity": 97.5, "Face": {"BoundingBox": box(0.1, 0.1, 0.2, 0.2)}}]},
        )
    )
    result = analyze(jpeg_bytes, "a", [{"id": "m1", "reference_bytes": ref}], settings=local_settings)
    assert result["faces"][0]["member_id"] == "m1"
    assert result["faces"][0]["status"] == "matched"
    assert result["matched_member_ids"] == ["m1"]


def test_ambiguous_match_is_left_uncertain(jpeg_bytes, local_settings, use_fake):
    """1위-2위 차이가 margin(5) 보다 작으면 억지로 배정하지 않는다 — rekognition 경로와
    완전히 같은 _resolve_faces 를 쓰므로 규칙도 동일하다."""
    target = box(0.1, 0.1, 0.2, 0.2)
    ref_a, ref_b = _ref(b"ref-a"), _ref(b"ref-b")
    use_fake(
        FakeLocalVision(
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
        settings=local_settings,
    )
    entry = result["faces"][0]
    assert entry["member_id"] is None
    assert entry["status"] == "uncertain"
    assert result["matched_member_ids"] == []


def test_compare_faces_uses_widened_candidate_threshold(jpeg_bytes, local_settings, use_fake):
    fake = use_fake(FakeLocalVision(faces=[face(box(0.1, 0.1, 0.2, 0.2))]))
    analyze(jpeg_bytes, "a", [{"id": "m1", "reference_bytes": _ref(b"ref-a")}], settings=local_settings)
    _, kwargs = next(c for c in fake.calls if c[0] == "compare_faces")
    assert kwargs["similarity_threshold"] == 85.0  # 90 - margin(5)


def test_member_with_faceless_reference_is_skipped_not_fatal(jpeg_bytes, local_settings, use_fake):
    target = box(0.1, 0.1, 0.2, 0.2)
    good_ref, bad_ref = _ref(b"good"), _ref(b"bad")

    def compare_error(source_bytes):
        if source_bytes == bad_ref:
            return AnalysisError("INVALID_PARAMETER", "이미지에서 비교할 얼굴을 찾지 못했습니다", retryable=False)
        return None

    use_fake(
        FakeLocalVision(
            faces=[face(target)],
            compare={good_ref: [{"Similarity": 98.0, "Face": {"BoundingBox": target}}]},
            compare_error=compare_error,
        )
    )
    result = analyze(
        jpeg_bytes,
        "a",
        [{"id": "bad", "reference_bytes": bad_ref}, {"id": "good", "reference_bytes": good_ref}],
        settings=local_settings,
    )
    assert result["matched_member_ids"] == ["good"]
    assert result["skipped_members"] == [{"member_id": "bad", "reason": "INVALID_PARAMETER"}]


def test_member_with_s3_only_reference_is_skipped_local_cant_fetch_s3(jpeg_bytes, local_settings, use_fake):
    """local_vision 은 S3 를 직접 못 읽는다 — reference_bytes/load_reference 가 없으면
    S3Object 참조만 있어도 그 멤버는 건너뛴다(사진 전체 분석은 계속된다)."""
    use_fake(FakeLocalVision(faces=[face(box(0.1, 0.1, 0.2, 0.2))]))
    result = analyze(
        jpeg_bytes,
        "a",
        [{"id": "m1", "reference_bucket": "kmu-proj-06-zzik", "reference_key": "refs/m1.jpg"}],
        settings=local_settings,
    )
    assert result["skipped_members"] == [{"member_id": "m1", "reason": "NO_REFERENCE_BUCKET"}]
    assert result["face_count"] == 1


def test_labels_are_mapped_and_face_boxes_are_forwarded(jpeg_bytes, local_settings, use_fake):
    detected = [face(box(0.1, 0.1, 0.2, 0.2))]
    fake = use_fake(
        FakeLocalVision(faces=detected, labels=[{"Name": "Sea", "Confidence": 99.0}, {"Name": "Person", "Confidence": 99.0}])
    )
    result = analyze(jpeg_bytes, "a", [], settings=local_settings)
    assert result["tags"] == ["바다"]
    _, kwargs = next(c for c in fake.calls if c[0] == "detect_labels")
    assert kwargs["face_boxes"] == [detected[0]["BoundingBox"]]
    assert kwargs["min_confidence"] == 80.0


def test_analyze_returns_contract_keys(jpeg_bytes, local_settings, use_fake):
    use_fake(FakeLocalVision(faces=[face(box(0.1, 0.1, 0.2, 0.2))]))
    result = analyze(jpeg_bytes, "album-1", [], settings=local_settings)
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
    assert result["provider"] == PROVIDER_LOCAL
    assert result["mode"] == MODE_LIVE


# --------------------------------------------------------------------------
# 임계값 기본값은 공급자별로 다르다
# --------------------------------------------------------------------------
def test_local_provider_uses_a_looser_default_similarity_threshold():
    """90 은 Rekognition Similarity 기준이다. local 은 점수 눈금이 달라 같은 값을 쓰면
    같은 사람인데도 '미등록'으로 떨어진다(90점 = SFace cosine 0.583)."""
    local = load_settings({"FACE_PROVIDER": "local"})
    rekognition = load_settings({"FACE_PROVIDER": "rekognition"})

    assert local.similarity_threshold == 70.0
    assert rekognition.similarity_threshold == 90.0
    # 후보를 넓게 받는 규칙(임계값 - 마진)은 공급자와 무관하게 그대로다.
    assert local.candidate_threshold == 65.0


def test_explicit_threshold_still_wins_for_the_local_provider():
    settings = load_settings({"FACE_PROVIDER": "local", "SIMILARITY_THRESHOLD": "88"})

    assert settings.similarity_threshold == 88.0

"""worker 와 실제 분석 모듈을 함께 돌리는 검사 (역할 4, ROLE_04 9번 항목).

3번의 `tests/test_worker.py` 는 `analyze` 를 가짜로 바꿔 worker 트랜잭션만 본다.
여기서는 **진짜 `backend.app.analysis` 를 그대로 태워** 계약이 실제로 맞물리는지 본다.

AWS 는 호출하지 않는다. 기본 `FACE_PROVIDER=mock` 이거나, rekognition 경로를 볼 때는
boto3 클라이언트만 가짜로 바꾼다. DB 는 테스트 전용 SQLite 파일이고 공유 RDS 를
건드리지 않는다.
"""

from __future__ import annotations

import hashlib
import io
import json

from PIL import Image
from sqlalchemy import select

from backend.app.models import Photo
from backend.app.worker import process_one
from tests.test_api import create_album, make_client


def photo_bytes(color: str = "#3366aa", size: tuple[int, int] = (320, 240)) -> bytes:
    """업로드용 합성 이미지. 사람 얼굴 사진이 아니다."""
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="JPEG")
    return output.getvalue()


def upload_one(client, album_id: str, name: str = "one.jpg", data: bytes | None = None) -> str:
    response = client.post(
        f"/api/albums/{album_id}/photos",
        files=[("files", (name, data or photo_bytes(), "image/jpeg"))],
    )
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["ok"], result
    return result["photo"]["id"]


def register_sample(app, monkeypatch, tmp_path, photo_id: str, entry: dict) -> None:
    """저장된 사진의 실제 바이트 해시로 mock manifest 를 만든다.

    업로드 시 storage.normalize_image 가 다시 인코딩하므로, 올린 바이트가 아니라
    **저장된 바이트**의 해시를 써야 manifest 가 맞는다.
    """
    with app.state.session_factory() as db:
        stored = app.state.storage.get(db.get(Photo, photo_id).s3_key)
    digest = hashlib.sha256(stored).hexdigest()
    manifest = tmp_path / f"manifest-{digest[:8]}.json"
    manifest.write_text(json.dumps({"samples": {digest: entry}}), encoding="utf-8")
    monkeypatch.setenv("MOCK_MANIFEST_PATH", str(manifest))


def test_real_analysis_module_completes_a_photo_through_the_worker(tmp_path, monkeypatch) -> None:
    """업로드 → worker → done. 가짜 analyze 없이 실제 모듈이 돈다."""
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])
    register_sample(
        app,
        monkeypatch,
        tmp_path,
        photo_id,
        {
            "label": "테스트 합성 이미지",
            "source": "테스트에서 Pillow 로 생성",
            "license": "자체 생성",
            "face_count": 2,
            "tags": ["바다"],
            "quality": {"sharpness": 80.0, "brightness": 60.0, "eyes_open_ratio": 1.0},
        },
    )

    assert process_one(app.state.session_factory, app.state.storage) is True

    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        assert photo.analysis_status == "done"
        assert photo.analysis_error is None
        assert photo.face_count == 2
        assert photo.shot_type == "group"
        assert photo.tags == ["바다"]
        assert photo.quality["eyes_open_ratio"] == 1.0
        # 80*0.5 + 1.0*100*0.4 + 60*0.1 = 86.0
        assert photo.best_score == 86.0


def test_mock_mode_is_visible_in_the_stored_row(tmp_path, monkeypatch) -> None:
    """화면이 "샘플 분석" 배지를 띄울 수 있도록 provider/mode 가 DB 에 남아야 한다."""
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])

    assert process_one(app.state.session_factory, app.state.storage) is True

    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        assert (photo.provider, photo.mode) == ("mock", "mock")

    listed = client.get(f"/api/albums/{album['album_id']}/photos").json()["items"][0]
    assert listed["provider"] == "mock"
    assert listed["mode"] == "mock"


def test_queue_drains_and_reports_empty(tmp_path) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    upload_one(client, album["album_id"], "a.jpg")
    upload_one(client, album["album_id"], "b.jpg", photo_bytes("#aa3366"))

    assert process_one(app.state.session_factory, app.state.storage) is True
    assert process_one(app.state.session_factory, app.state.storage) is True
    # 큐가 비면 False 를 돌려준다
    assert process_one(app.state.session_factory, app.state.storage) is False

    status = client.get(f"/api/albums/{album['album_id']}/status").json()
    assert status["pending"] == 0
    assert status["processing"] == 0
    assert status["failed"] == 0
    assert status["done"] == 2


# --------------------------------------------------------------------------
# 재시도 — worker 는 AnalysisError.retryable 만 보고 판단해야 한다
# --------------------------------------------------------------------------
class CountingRekognition:
    """호출 횟수를 세는 가짜 Rekognition. 지정한 예외를 계속 던진다."""

    def __init__(self, error):
        self.error = error
        self.calls = 0

    def detect_faces(self, **_kwargs):
        self.calls += 1
        raise self.error

    def compare_faces(self, **_kwargs):  # pragma: no cover - 여기까지 오지 않는다
        raise AssertionError("DetectFaces 가 실패하면 CompareFaces 를 부르면 안 된다")

    def detect_labels(self, **_kwargs):  # pragma: no cover
        raise AssertionError("DetectFaces 가 실패하면 DetectLabels 를 부르면 안 된다")


def use_rekognition(monkeypatch, client_obj) -> None:
    monkeypatch.setenv("FACE_PROVIDER", "rekognition")
    monkeypatch.setattr(
        "backend.app.analysis._rekognition_client", lambda region: client_obj
    )
    # 재시도 대기(2초, 4초)를 실제로 자지 않는다
    monkeypatch.setattr("backend.app.worker.time.sleep", lambda _seconds: None)


def aws_error(code: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": "raw aws detail"}}, "DetectFaces")


def test_throttling_is_retried_three_times_then_marked_failed(tmp_path, monkeypatch) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])
    fake = CountingRekognition(aws_error("ThrottlingException"))
    use_rekognition(monkeypatch, fake)

    assert process_one(app.state.session_factory, app.state.storage) is True

    assert fake.calls == 3, "retryable 오류는 3번까지 시도해야 한다"
    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        assert photo.analysis_status == "failed"
        assert photo.analysis_error.startswith("AWS_THROTTLED")


def test_auth_failure_is_not_retried(tmp_path, monkeypatch) -> None:
    """권한 오류를 반복 호출하면 요금만 나가고 절대 성공하지 않는다."""
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])
    fake = CountingRekognition(aws_error("AccessDeniedException"))
    use_rekognition(monkeypatch, fake)

    assert process_one(app.state.session_factory, app.state.storage) is True

    assert fake.calls == 1, "AWS_AUTH 는 재시도하면 안 된다"
    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        assert photo.analysis_status == "failed"
        assert photo.analysis_error.startswith("AWS_AUTH")


def test_stored_error_does_not_leak_raw_aws_message(tmp_path, monkeypatch) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])
    use_rekognition(monkeypatch, CountingRekognition(aws_error("UnrecognizedClientException")))

    assert process_one(app.state.session_factory, app.state.storage) is True

    with app.state.session_factory() as db:
        stored = db.get(Photo, photo_id).analysis_error
    assert "raw aws detail" not in stored
    assert "AWS 분석 권한을 확인해 주세요" in stored


def test_auth_failure_never_becomes_a_mock_success(tmp_path, monkeypatch) -> None:
    """인증 실패를 mock 성공으로 바꾸지 않는다. 자동 폴백 금지."""
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])
    use_rekognition(monkeypatch, CountingRekognition(aws_error("AccessDeniedException")))

    process_one(app.state.session_factory, app.state.storage)

    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        assert photo.analysis_status == "failed"
        assert photo.provider is None
        assert photo.mode is None
        assert photo.face_count == 0


# --------------------------------------------------------------------------
# 수동 수정 보존 — 재분석해도 사람이 고친 것을 덮어쓰지 않는다
# --------------------------------------------------------------------------
def member_ids(client, album_id: str) -> list[str]:
    return [item["id"] for item in client.get(f"/api/albums/{album_id}").json()["members"]]


def test_manual_member_link_survives_reanalyze(tmp_path, monkeypatch) -> None:
    """수동으로 지정한 인물은 재분석 후에도 남아야 한다."""
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])
    me = member_ids(client, album["album_id"])[0]

    assert process_one(app.state.session_factory, app.state.storage) is True

    manual = client.put(
        f"/api/photos/{photo_id}/members",
        json={"members": [{"member_id": me, "excluded": False}]},
    )
    assert manual.status_code == 200
    assert manual.json()["members"][0]["source"] == "manual"

    assert client.post(f"/api/photos/{photo_id}/reanalyze").status_code in (200, 202)
    assert process_one(app.state.session_factory, app.state.storage) is True

    after = client.get(f"/api/photos/{photo_id}").json()["members"]
    assert [(m["member_id"], m["source"]) for m in after] == [(me, "manual")]


def test_manual_exclusion_survives_reanalyze(tmp_path, monkeypatch) -> None:
    """사람이 '이 사람 아님'으로 제외한 것도 재분석이 되살리면 안 된다."""
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])
    me = member_ids(client, album["album_id"])[0]

    assert process_one(app.state.session_factory, app.state.storage) is True
    client.put(
        f"/api/photos/{photo_id}/members",
        json={"members": [{"member_id": me, "excluded": True}]},
    )

    client.post(f"/api/photos/{photo_id}/reanalyze")
    assert process_one(app.state.session_factory, app.state.storage) is True

    after = client.get(f"/api/photos/{photo_id}").json()["members"]
    excluded = [m for m in after if m["member_id"] == me]
    assert excluded and excluded[0]["excluded"] is True


def test_reanalyze_requeues_the_photo(tmp_path) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])
    assert process_one(app.state.session_factory, app.state.storage) is True

    client.post(f"/api/photos/{photo_id}/reanalyze")
    with app.state.session_factory() as db:
        assert db.get(Photo, photo_id).analysis_status == "pending"
    assert process_one(app.state.session_factory, app.state.storage) is True
    with app.state.session_factory() as db:
        assert db.get(Photo, photo_id).analysis_status == "done"


# --------------------------------------------------------------------------
# 사람 없는 사진 / 분석 실패 구분 — 둘을 섞으면 화면이 거짓말을 한다
# --------------------------------------------------------------------------
def test_photo_without_faces_is_done_not_failed(tmp_path, monkeypatch) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])
    register_sample(app, monkeypatch, tmp_path, photo_id, {"face_count": 0, "tags": ["산"]})

    assert process_one(app.state.session_factory, app.state.storage) is True

    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        assert photo.analysis_status == "done"      # 실패가 아니다
        assert photo.analysis_error is None
        assert photo.shot_type == "no_face"
        assert photo.face_count == 0


def test_failed_and_no_face_are_separate_states(tmp_path, monkeypatch) -> None:
    """status 집계에서 '사람 없는 사진'과 '분석 실패'가 섞이지 않아야 한다."""
    client, app = make_client(tmp_path)
    album = create_album(client)
    empty_id = upload_one(client, album["album_id"], "empty.jpg")
    register_sample(app, monkeypatch, tmp_path, empty_id, {"face_count": 0, "tags": []})
    assert process_one(app.state.session_factory, app.state.storage) is True

    broken_id = upload_one(client, album["album_id"], "broken.jpg", photo_bytes("#112233"))
    use_rekognition(monkeypatch, CountingRekognition(aws_error("AccessDeniedException")))
    assert process_one(app.state.session_factory, app.state.storage) is True

    status = client.get(f"/api/albums/{album['album_id']}/status").json()
    assert status["done"] == 1
    assert status["failed"] == 1

    with app.state.session_factory() as db:
        assert db.get(Photo, empty_id).shot_type == "no_face"
        assert db.get(Photo, broken_id).analysis_status == "failed"


def test_missing_capture_time_stays_null(tmp_path) -> None:
    """EXIF 가 없으면 촬영 시각을 지어내지 않고 NULL 로 둔다."""
    client, app = make_client(tmp_path)
    album = create_album(client)
    photo_id = upload_one(client, album["album_id"])

    assert process_one(app.state.session_factory, app.state.storage) is True

    with app.state.session_factory() as db:
        assert db.get(Photo, photo_id).captured_at is None
    detail = client.get(f"/api/photos/{photo_id}").json()
    assert detail["captured_at"] is None

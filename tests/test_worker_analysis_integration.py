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

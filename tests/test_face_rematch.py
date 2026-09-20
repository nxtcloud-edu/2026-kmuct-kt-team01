"""뒤늦게 기준 사진을 등록한 사람이 직접 눌러 얼굴 분류를 다시 돌리는 경로.

자동이 아니라 수동 버튼이다. 사진 1장당 분석 호출이 다시 나가므로 사용자가 언제
비용을 쓸지 고르게 한다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.models import AnalysisStatus, Photo
from tests.test_api import create_album, jpeg_bytes, make_client


def register_reference(client: TestClient) -> None:
    assert client.post(
        "/api/members/me/reference",
        files={"file": ("selfie.jpg", jpeg_bytes(), "image/jpeg")},
    ).status_code == 200


def test_rematch_requires_a_reference_photo_first(tmp_path) -> None:
    owner, _app = make_client(tmp_path)
    album = create_album(owner)

    response = owner.post(f"/api/albums/{album['album_id']}/rematch")
    assert response.status_code == 409
    assert response.json()["code"] == "REFERENCE_REQUIRED"


def test_rematch_queues_only_photos_with_unregistered_faces(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    uploaded = owner.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[
            ("files", ("a.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("b.jpg", jpeg_bytes(), "image/jpeg")),
        ],
    ).json()
    ids = [result["photo"]["id"] for result in uploaded["results"]]

    # 한 장은 미등록 얼굴이 남은 분석 완료 상태, 다른 한 장은 전원 매칭된 상태로 둔다.
    with app.state.session_factory() as db:
        first, second = db.get(Photo, ids[0]), db.get(Photo, ids[1])
        for photo in (first, second):
            photo.analysis_status = AnalysisStatus.DONE.value
        first.unregistered_face_count = 2
        second.unregistered_face_count = 0
        db.commit()

    register_reference(owner)
    response = owner.post(f"/api/albums/{album['album_id']}/rematch")
    assert response.status_code == 200
    assert response.json() == {"queued": 1}

    with app.state.session_factory() as db:
        requeued = db.get(Photo, ids[0])
        assert requeued.analysis_status == AnalysisStatus.PENDING.value
        assert requeued.analysis_attempts == 0
        assert requeued.processing_started_at is None
        # 이미 전원 매칭된 사진은 다시 분석하지 않는다. 분석 호출이 공짜가 아니다.
        assert db.get(Photo, ids[1]).analysis_status == AnalysisStatus.DONE.value


def test_rematch_reports_zero_when_there_is_nothing_to_redo(tmp_path) -> None:
    owner, _app = make_client(tmp_path)
    album = create_album(owner)
    register_reference(owner)

    response = owner.post(f"/api/albums/{album['album_id']}/rematch")
    assert response.status_code == 200
    assert response.json() == {"queued": 0}


def test_rematch_rejects_someone_who_is_not_in_the_album(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    outsider = TestClient(app)
    create_album(outsider, "제주 여행")

    response = outsider.post(f"/api/albums/{album['album_id']}/rematch")
    assert response.status_code == 403
    assert response.json()["code"] == "ALBUM_FORBIDDEN"

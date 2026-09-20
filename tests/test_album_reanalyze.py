"""앨범 단위 재분석. 사용자가 직접 눌러야 실행되는 수동 경로다.

사진 1장당 분석 호출이 다시 나가므로 기본 범위를 가장 좁게(failed) 두고,
필요한 범위를 scope 로 고르게 한다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.models import AnalysisStatus, Photo
from tests.test_api import create_album, jpeg_bytes, make_client


def upload_two(client: TestClient, album_id: str) -> list[str]:
    uploaded = client.post(
        f"/api/albums/{album_id}/photos",
        files=[
            ("files", ("a.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("b.jpg", jpeg_bytes(), "image/jpeg")),
        ],
    ).json()
    return [result["photo"]["id"] for result in uploaded["results"]]


def register_reference(client: TestClient) -> None:
    assert client.post(
        "/api/members/me/reference",
        files={"file": ("selfie.jpg", jpeg_bytes(), "image/jpeg")},
    ).status_code == 200


def test_failed_scope_requeues_only_failures(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    ids = upload_two(owner, album["album_id"])
    with app.state.session_factory() as db:
        db.get(Photo, ids[0]).analysis_status = AnalysisStatus.FAILED.value
        db.get(Photo, ids[1]).analysis_status = AnalysisStatus.DONE.value
        db.commit()

    response = owner.post(f"/api/albums/{album['album_id']}/reanalyze?scope=failed")
    assert response.status_code == 200
    assert response.json() == {"pending": 1, "processing": 0, "done": 1, "failed": 0}

    with app.state.session_factory() as db:
        assert db.get(Photo, ids[0]).analysis_status == AnalysisStatus.PENDING.value
        assert db.get(Photo, ids[0]).analysis_attempts == 0
        assert db.get(Photo, ids[1]).analysis_status == AnalysisStatus.DONE.value


def test_failed_is_the_default_scope(tmp_path) -> None:
    """기본값을 가장 좁은 범위로 둔다. 실수로 전체를 다시 돌리면 분석 비용이 크다."""
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    ids = upload_two(owner, album["album_id"])
    with app.state.session_factory() as db:
        for photo_id in ids:
            db.get(Photo, photo_id).analysis_status = AnalysisStatus.DONE.value
        db.commit()

    response = owner.post(f"/api/albums/{album['album_id']}/reanalyze")
    assert response.status_code == 200
    assert response.json()["done"] == 2
    assert response.json()["pending"] == 0


def test_all_scope_requeues_everything(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    ids = upload_two(owner, album["album_id"])
    with app.state.session_factory() as db:
        db.get(Photo, ids[0]).analysis_status = AnalysisStatus.DONE.value
        db.get(Photo, ids[1]).analysis_status = AnalysisStatus.FAILED.value
        db.commit()

    response = owner.post(f"/api/albums/{album['album_id']}/reanalyze?scope=all")
    assert response.status_code == 200
    assert response.json() == {"pending": 2, "processing": 0, "done": 0, "failed": 0}


def test_unmatched_scope_only_touches_photos_with_unregistered_faces(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    ids = upload_two(owner, album["album_id"])
    with app.state.session_factory() as db:
        first, second = db.get(Photo, ids[0]), db.get(Photo, ids[1])
        for photo in (first, second):
            photo.analysis_status = AnalysisStatus.DONE.value
        first.unregistered_face_count = 2
        second.unregistered_face_count = 0
        db.commit()

    register_reference(owner)
    response = owner.post(f"/api/albums/{album['album_id']}/reanalyze?scope=unmatched")
    assert response.status_code == 200
    assert response.json() == {"pending": 1, "processing": 0, "done": 1, "failed": 0}

    with app.state.session_factory() as db:
        assert db.get(Photo, ids[0]).analysis_status == AnalysisStatus.PENDING.value
        # 이미 전원 매칭된 사진은 다시 분석하지 않는다.
        assert db.get(Photo, ids[1]).analysis_status == AnalysisStatus.DONE.value


def test_unmatched_scope_needs_a_reference_photo(tmp_path) -> None:
    """비교할 기준 얼굴이 없으면 다시 돌려도 결과가 같다. 헛돌지 않게 막는다."""
    owner, _app = make_client(tmp_path)
    album = create_album(owner)

    response = owner.post(f"/api/albums/{album['album_id']}/reanalyze?scope=unmatched")
    assert response.status_code == 409
    assert response.json()["code"] == "REFERENCE_REQUIRED"


def test_failed_scope_does_not_need_a_reference_photo(tmp_path) -> None:
    owner, _app = make_client(tmp_path)
    album = create_album(owner)

    assert owner.post(f"/api/albums/{album['album_id']}/reanalyze?scope=failed").status_code == 200


def test_unknown_scope_is_rejected(tmp_path) -> None:
    owner, _app = make_client(tmp_path)
    album = create_album(owner)

    assert owner.post(f"/api/albums/{album['album_id']}/reanalyze?scope=everything").status_code == 422


def test_reanalyze_rejects_someone_who_is_not_in_the_album(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    outsider = TestClient(app)
    create_album(outsider, "제주 여행")

    response = outsider.post(f"/api/albums/{album['album_id']}/reanalyze?scope=all")
    assert response.status_code == 403
    assert response.json()["code"] == "ALBUM_FORBIDDEN"

from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import Approval, Base, Edit, Member, Photo


def jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 24), "#7c3aed").save(output, format="JPEG")
    return output.getvalue()


def make_client(tmp_path) -> tuple[TestClient, object]:
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'zzik_test.sqlite'}",
        session_secret="test-secret-that-is-not-used-outside-tests",
        local_storage_path=tmp_path / "objects",
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    return TestClient(app), app


def create_album(client: TestClient, name: str = "부산 여행") -> dict[str, str]:
    response = client.post(
        "/api/albums", json={"name": name, "display_name": "민지"}
    )
    assert response.status_code == 201
    return response.json()


def test_session_and_album_authorization(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    first = create_album(owner)

    outsider = TestClient(app)
    create_album(outsider, "제주 여행")
    forbidden = outsider.get(f"/api/albums/{first['album_id']}")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "ALBUM_FORBIDDEN"

    unauthenticated = TestClient(app)
    missing = unauthenticated.get(f"/api/albums/{first['album_id']}")
    assert missing.status_code == 401
    assert missing.json() == {
        "code": "SESSION_REQUIRED",
        "message": "앨범 참여가 필요합니다.",
    }


def test_multi_upload_keeps_success_when_another_file_fails(tmp_path) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)

    response = client.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[
            ("files", ("ok.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("bad.txt", b"not an image", "text/plain")),
        ],
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["ok"] for item in results] == [True, False]
    assert results[1]["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"

    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Photo.id))) == 1

    listing = client.get(f"/api/albums/{album['album_id']}/photos")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["analysis_status"] == "pending"
    assert listing.json()["items"][0]["provider"] is None
    assert listing.json()["items"][0]["mode"] is None


def test_manual_member_change_invalidates_approvals(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    invitee = TestClient(app)
    joined = invitee.post(
        "/api/albums/join",
        json={"invite_code": album["invite_code"], "display_name": "서준"},
    )
    assert joined.status_code == 200

    album_view = owner.get(f"/api/albums/{album['album_id']}").json()
    owner_id, invitee_id = [item["id"] for item in album_view["members"]]
    uploaded = owner.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("group.jpg", jpeg_bytes(), "image/jpeg"))],
    ).json()
    photo_id = uploaded["results"][0]["photo"]["id"]

    with app.state.session_factory() as db:
        edit = Edit(
            photo_id=photo_id,
            author_member_id=owner_id,
            number=1,
            brightness=1.0,
            saturation=1.0,
        )
        db.add(edit)
        db.flush()
        db.add(Approval(edit_id=edit.id, member_id=owner_id))
        db.commit()

    changed = owner.put(
        f"/api/photos/{photo_id}/members",
        json={"members": [{"member_id": invitee_id, "excluded": False}]},
    )
    assert changed.status_code == 200
    assert changed.json()["members"] == [
        {
            "member_id": invitee_id,
            "similarity": None,
            "source": "manual",
            "excluded": False,
        }
    ]
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Approval.edit_id))) == 0


def test_reference_endpoint_reports_missing_role_four_dependency(tmp_path, monkeypatch) -> None:
    """역할 4 모듈이 없을 때의 503 동작. 이제 모듈이 있으므로 부재 상황을 주입해 검사한다."""
    from backend.app import analysis_contract

    def unavailable(_image_bytes):
        raise analysis_contract.AnalysisUnavailable("role 4 analysis module is not available")

    monkeypatch.setattr("backend.app.api.validate_reference", unavailable)
    client, _ = make_client(tmp_path)
    create_album(client)
    response = client.post(
        "/api/members/me/reference",
        files={"file": ("selfie.jpg", jpeg_bytes(), "image/jpeg")},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "ANALYSIS_UNAVAILABLE"
    assert response.json()["details"] == {"owner": "role-4", "mode": "unavailable"}


def test_reference_endpoint_accepts_selfie_once_role_four_is_connected(tmp_path) -> None:
    """역할 4 analysis.py 가 붙은 뒤의 정상 경로. 기본 FACE_PROVIDER=mock 이다."""
    client, app = make_client(tmp_path)
    create_album(client)
    response = client.post(
        "/api/members/me/reference",
        files={"file": ("selfie.jpg", jpeg_bytes(), "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    with app.state.session_factory() as db:
        member = db.scalar(select(Member))
        assert member.reference_indexed is True
        assert member.reference_key.endswith("/reference.jpg")


def test_selected_originals_download_as_zip(tmp_path) -> None:
    client, _ = make_client(tmp_path)
    album = create_album(client)
    upload = client.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[
            ("files", ("same.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("same.jpg", jpeg_bytes(), "image/jpeg")),
        ],
    ).json()
    photo_ids = [item["photo"]["id"] for item in upload["results"]]
    response = client.post(
        f"/api/albums/{album['album_id']}/download",
        json={"photo_ids": photo_ids, "version": "original"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["same.jpg", "2-same.jpg"]


def test_openapi_exposes_the_confirmed_contract(tmp_path) -> None:
    _, app = make_client(tmp_path)
    operations = {
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }
    assert {
        ("POST", "/api/albums"),
        ("POST", "/api/albums/join"),
        ("GET", "/api/albums/{album_id}"),
        ("POST", "/api/members/me/reference"),
        ("GET", "/api/albums/{album_id}/photos"),
        ("POST", "/api/albums/{album_id}/photos"),
        ("GET", "/api/photos/{photo_id}"),
        ("PUT", "/api/photos/{photo_id}/members"),
        ("POST", "/api/photos/{photo_id}/reanalyze"),
        ("GET", "/api/albums/{album_id}/status"),
        ("GET", "/api/albums/{album_id}/coverage"),
        ("GET", "/api/photos/{photo_id}/download"),
        ("POST", "/api/albums/{album_id}/download"),
        ("POST", "/api/photos/{photo_id}/edits"),
        ("GET", "/api/photos/{photo_id}/edits"),
        ("POST", "/api/edits/{edit_id}/approve"),
        ("DELETE", "/api/edits/{edit_id}/approve"),
        ("GET", "/api/health/ready"),
    }.issubset(operations)

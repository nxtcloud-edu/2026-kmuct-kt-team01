from __future__ import annotations

import io
import hashlib
import zipfile
from urllib.parse import quote

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import Approval, Base, Edit, Member, Photo, PhotoMember


def jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 24), "#7c3aed").save(output, format="JPEG")
    return output.getvalue()


def png_bytes(width: int = 2600, height: int = 25) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (width, height), (124, 58, 237, 128)).save(output, format="PNG")
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
    assert response.json()["member_id"]
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


def test_download_with_non_ascii_filename_does_not_500(tmp_path) -> None:
    """Content-Disposition 헤더는 latin-1만 허용한다. 한글 파일명을 그대로 넣으면
    UnicodeEncodeError로 500이 나서 사진 상세·보정 화면의 이미지가 전부 깨졌었다."""
    client, _app = make_client(tmp_path)
    album = create_album(client)
    upload = client.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("이상혁_연속컷_1.jpeg", jpeg_bytes(), "image/jpeg"))],
    )
    assert upload.status_code == 200
    photo = upload.json()["results"][0]["photo"]
    assert photo is not None

    download = client.get(f"/api/photos/{photo['id']}/download")
    assert download.status_code == 200
    disposition = download.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert quote("이상혁_연속컷_1.jpeg") in disposition


def test_upload_preserves_png_original_bytes_and_metadata_across_restart(tmp_path) -> None:
    client, app = make_client(tmp_path)
    album = create_album(client)
    original = png_bytes()

    uploaded = client.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("wide.png", original, "image/png"))],
    ).json()["results"][0]["photo"]

    with app.state.session_factory() as db:
        photo = db.get(Photo, uploaded["id"])
        assert photo.mime == "image/png"
        assert (photo.width, photo.height, photo.byte_size) == (2600, 25, len(original))
        assert photo.s3_key.endswith("/original.png")
        assert app.state.storage.get(photo.s3_key) == original
        assert app.state.storage.get(photo.thumb_key) != original

    restarted = TestClient(create_app(app.state.settings))
    restarted.cookies.update(client.cookies)
    downloaded = restarted.get(f"/api/photos/{uploaded['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.content == original
    assert hashlib.sha256(downloaded.content).hexdigest() == hashlib.sha256(original).hexdigest()


def test_manual_member_change_invalidates_approvals(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    invitee = TestClient(app)
    joined = invitee.post(
        "/api/albums/join",
        json={"invite_code": album["invite_code"], "display_name": "서준"},
    )
    assert joined.status_code == 200
    assert joined.json()["member_id"]

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
            "display_name": "서준",
            "similarity": None,
            "source": "manual",
            "excluded": False,
        }
    ]
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Approval.edit_id))) == 0


def test_reference_endpoint_uses_role_four_mock_and_stores_reference(tmp_path) -> None:
    client, app = make_client(tmp_path)
    create_album(client)
    response = client.post(
        "/api/members/me/reference",
        files={"file": ("selfie.jpg", jpeg_bytes(), "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["reference_indexed"] is True
    assert response.json()["provider"] == "mock"
    assert response.json()["mode"] == "mock"
    with app.state.session_factory() as db:
        member = db.get(Member, response.json()["member_id"])
        assert member.reference_key.endswith("/reference.jpg")
        assert app.state.storage.get(member.reference_key)


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


def test_role5_edit_approval_and_final_zip_preserve_original(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    invitee = TestClient(app)
    assert invitee.post(
        "/api/albums/join",
        json={"invite_code": album["invite_code"], "display_name": "서준"},
    ).status_code == 200
    members = owner.get(f"/api/albums/{album['album_id']}").json()["members"]
    owner_id, invitee_id = [item["id"] for item in members]
    uploaded = owner.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("group.jpg", jpeg_bytes(), "image/jpeg"))],
    ).json()
    photo_id = uploaded["results"][0]["photo"]["id"]

    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        original = app.state.storage.get(photo.s3_key)
        original_hash = hashlib.sha256(original).hexdigest()
        photo.analysis_status = "done"
        photo.face_count = 2
        photo.shot_type = "group"
        db.add_all(
            [
                PhotoMember(photo_id=photo_id, member_id=owner_id, similarity=99, source="auto"),
                PhotoMember(photo_id=photo_id, member_id=invitee_id, similarity=98, source="auto"),
            ]
        )
        db.commit()

    created = owner.post(
        f"/api/photos/{photo_id}/edits",
        json={"brightness": 1.2, "saturation": 0.8, "parent_id": None},
    )
    assert created.status_code == 201
    edit_id = created.json()["id"]
    assert owner.post(f"/api/edits/{edit_id}/approve").json()["is_final"] is False
    approved = invitee.post(f"/api/edits/{edit_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["is_final"] is True

    preview = owner.get(approved.json()["preview_url"])
    download = owner.get(approved.json()["download_url"])
    assert preview.status_code == download.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    assert download.headers["content-disposition"] == 'attachment; filename="group-edit-1.jpg"'
    assert preview.content == download.content

    final_zip = owner.post(
        f"/api/albums/{album['album_id']}/download",
        json={"photo_ids": [photo_id], "version": "final"},
    )
    assert final_zip.status_code == 200
    with zipfile.ZipFile(io.BytesIO(final_zip.content)) as archive:
        assert archive.namelist() == ["group-edit-1.jpg"]
        assert archive.read("group-edit-1.jpg") != original
    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        assert hashlib.sha256(app.state.storage.get(photo.s3_key)).hexdigest() == original_hash


def test_zero_confirmed_members_use_uploader_as_only_approver(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    uploaded = owner.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("unknown.jpg", jpeg_bytes(), "image/jpeg"))],
    ).json()
    photo_id = uploaded["results"][0]["photo"]["id"]
    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        photo.analysis_status = "done"
        photo.face_count = 1
        photo.shot_type = "solo"
        db.commit()
    edit = owner.post(
        f"/api/photos/{photo_id}/edits",
        json={"brightness": 1.0, "saturation": 1.0},
    ).json()
    assert edit["required_count"] == 1
    assert edit["approval_blocked_reason"] is None
    assert owner.post(f"/api/edits/{edit['id']}/approve").json()["is_final"] is True


def test_reanalysis_invalidates_edit_approvals(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    uploaded = owner.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("solo.jpg", jpeg_bytes(), "image/jpeg"))],
    ).json()
    photo_id = uploaded["results"][0]["photo"]["id"]
    with app.state.session_factory() as db:
        photo = db.get(Photo, photo_id)
        photo.analysis_status = "done"
        photo.face_count = 0
        photo.shot_type = "no_face"
        db.commit()
    edit = owner.post(
        f"/api/photos/{photo_id}/edits",
        json={"brightness": 1.0, "saturation": 1.0},
    ).json()
    assert owner.post(f"/api/edits/{edit['id']}/approve").json()["is_final"] is True
    assert owner.post(f"/api/photos/{photo_id}/reanalyze").status_code == 200
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Approval.edit_id))) == 0


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
        ("GET", "/api/photos/{photo_id}/thumbnail"),
        ("POST", "/api/albums/{album_id}/download"),
        ("POST", "/api/photos/{photo_id}/edits"),
        ("GET", "/api/photos/{photo_id}/edits"),
        ("POST", "/api/edits/{edit_id}/approve"),
        ("DELETE", "/api/edits/{edit_id}/approve"),
        ("GET", "/api/health/ready"),
    }.issubset(operations)


def test_photo_response_urls_names_pages_and_multi_member_and_filter(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    invitee = TestClient(app)
    invitee.post(
        "/api/albums/join",
        json={"invite_code": album["invite_code"], "display_name": "서준"},
    )
    members = owner.get(f"/api/albums/{album['album_id']}").json()["members"]
    owner_id, invitee_id = [item["id"] for item in members]
    uploaded = owner.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[
            ("files", ("both.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("owner.jpg", jpeg_bytes(), "image/jpeg")),
        ],
    ).json()["results"]
    both_id, owner_only_id = [item["photo"]["id"] for item in uploaded]
    with app.state.session_factory() as db:
        both = db.get(Photo, both_id)
        owner_only = db.get(Photo, owner_only_id)
        both.tags = ["실내", "노트북"]
        both.unregistered_face_count = 1
        owner_only.tags = ["실내"]
        owner_only.uncertain_face_count = 1
        db.add_all(
            [
                PhotoMember(photo_id=both_id, member_id=owner_id, source="manual"),
                PhotoMember(photo_id=both_id, member_id=invitee_id, source="manual"),
                PhotoMember(photo_id=owner_only_id, member_id=owner_id, source="manual"),
            ]
        )
        db.commit()

    album_detail = owner.get(f"/api/albums/{album['album_id']}").json()
    assert album_detail["tags"] == ["노트북", "실내"]

    response = owner.get(
        f"/api/albums/{album['album_id']}/photos",
        params=[("member_id", owner_id), ("member_id", invitee_id), ("page_size", "1")],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["total_pages"] == 1
    photo = body["items"][0]
    assert photo["id"] == both_id
    assert photo["image_url"] == f"/api/photos/{both_id}/download"
    assert photo["thumb_url"] == f"/api/photos/{both_id}/thumbnail"
    assert {member["display_name"] for member in photo["members"]} == {"민지", "서준"}
    assert owner.get(photo["thumb_url"]).status_code == 200

    unregistered = owner.get(
        f"/api/albums/{album['album_id']}/photos",
        params={"face_status": "unregistered"},
    ).json()
    assert [item["id"] for item in unregistered["items"]] == [both_id]
    uncertain = owner.get(
        f"/api/albums/{album['album_id']}/photos",
        params={"face_status": "uncertain"},
    ).json()
    assert [item["id"] for item in uncertain["items"]] == [owner_only_id]

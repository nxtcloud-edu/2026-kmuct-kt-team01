"""올린 사람으로 사진을 거르는 필터.

'내가 올린 사진은 이미 내 폰에 있으니 남이 찍어준 것만 받는다'는 쓰임새 때문이다.
사진에 누가 찍혔는지(member_id)와는 다른 축이라 필터를 따로 둔다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_api import create_album, jpeg_bytes, make_client


def upload(client: TestClient, album_id: str, name: str) -> str:
    response = client.post(
        f"/api/albums/{album_id}/photos",
        files=[("files", (name, jpeg_bytes(), "image/jpeg"))],
    )
    assert response.status_code == 200
    return response.json()["results"][0]["photo"]["id"]


def filenames(client: TestClient, album_id: str, query: str = "") -> list[str]:
    response = client.get(f"/api/albums/{album_id}/photos{query}")
    assert response.status_code == 200
    return [item["filename"] for item in response.json()["items"]]


def two_member_album(tmp_path):
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    guest = TestClient(app)
    assert guest.post(
        "/api/albums/join",
        json={
            "invite_code": album["invite_code"],
            "display_name": "서준",
            "passcode": "guest-pass",
        },
    ).status_code == 200
    upload(owner, album["album_id"], "owner.jpg")
    upload(guest, album["album_id"], "guest.jpg")
    return owner, guest, album["album_id"]


def test_others_returns_only_photos_someone_else_uploaded(tmp_path) -> None:
    owner, guest, album_id = two_member_album(tmp_path)

    assert filenames(owner, album_id, "?uploaded_by=others") == ["guest.jpg"]
    assert filenames(guest, album_id, "?uploaded_by=others") == ["owner.jpg"]


def test_me_returns_only_my_own_uploads(tmp_path) -> None:
    owner, guest, album_id = two_member_album(tmp_path)

    assert filenames(owner, album_id, "?uploaded_by=me") == ["owner.jpg"]
    assert filenames(guest, album_id, "?uploaded_by=me") == ["guest.jpg"]


def test_no_filter_still_returns_the_whole_album(tmp_path) -> None:
    owner, _guest, album_id = two_member_album(tmp_path)

    assert sorted(filenames(owner, album_id)) == ["guest.jpg", "owner.jpg"]


def test_total_count_reflects_the_filter(tmp_path) -> None:
    """페이지네이션이 필터링된 결과 기준이어야 '전체 선택'이 맞는 장수를 받는다."""
    owner, _guest, album_id = two_member_album(tmp_path)

    response = owner.get(f"/api/albums/{album_id}/photos?uploaded_by=others")
    assert response.json()["total"] == 1
    assert response.json()["total_pages"] == 1


def test_unknown_uploaded_by_value_is_rejected(tmp_path) -> None:
    owner, _guest, album_id = two_member_album(tmp_path)

    assert owner.get(f"/api/albums/{album_id}/photos?uploaded_by=everyone").status_code == 422

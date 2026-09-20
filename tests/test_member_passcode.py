from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.models import Member
from backend.app.passcodes import hash_passcode, verify_passcode
from tests.test_api import create_album, jpeg_bytes, make_client


def join(client: TestClient, invite_code: str, name: str, passcode: str):
    return client.post(
        "/api/albums/join",
        json={"invite_code": invite_code, "display_name": name, "passcode": passcode},
    )


def test_hash_is_salted_and_only_verifies_the_right_passcode():
    first = hash_passcode("pw-1234")
    second = hash_passcode("pw-1234")

    # 같은 비밀번호라도 솔트가 달라 저장값이 달라야 한다.
    assert first != second
    assert first.startswith("pbkdf2_sha256$")
    assert "pw-1234" not in first
    assert verify_passcode("pw-1234", first) is True
    assert verify_passcode("pw-1235", first) is False
    assert verify_passcode("pw-1234", None) is False
    assert verify_passcode("pw-1234", "broken-format") is False


def test_same_name_and_passcode_returns_the_original_member(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)

    first_visit = join(TestClient(app), album["invite_code"], "서준", "seojun-pw")
    assert first_visit.status_code == 200
    assert first_visit.json()["rejoined"] is False
    member_id = first_visit.json()["member_id"]

    # 브라우저를 닫았다가 다시 들어오는 상황. 쿠키가 없는 새 클라이언트로 확인한다.
    second_visit = join(TestClient(app), album["invite_code"], "서준", "seojun-pw")
    assert second_visit.status_code == 200
    assert second_visit.json()["member_id"] == member_id
    assert second_visit.json()["rejoined"] is True

    members = owner.get(f"/api/albums/{album['album_id']}").json()["members"]
    assert [member["display_name"] for member in members] == ["민지", "서준"]


def test_wrong_passcode_cannot_take_over_an_existing_name(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    assert join(TestClient(app), album["invite_code"], "서준", "seojun-pw").status_code == 200

    impostor = join(TestClient(app), album["invite_code"], "서준", "guessing")
    assert impostor.status_code == 403
    assert impostor.json()["code"] == "PASSCODE_MISMATCH"

    members = owner.get(f"/api/albums/{album['album_id']}").json()["members"]
    assert len(members) == 2


def test_rejoined_member_keeps_reference_photo_and_uploads(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    first = TestClient(app)
    assert join(first, album["invite_code"], "서준", "seojun-pw").status_code == 200
    assert first.post(
        "/api/members/me/reference",
        files={"file": ("selfie.jpg", jpeg_bytes(), "image/jpeg")},
    ).status_code == 200
    first.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[("files", ("mine.jpg", jpeg_bytes(), "image/jpeg"))],
    )

    returning = join(TestClient(app), album["invite_code"], "서준", "seojun-pw")
    assert returning.json()["rejoined"] is True
    # 기준 사진이 남아 있으므로 프런트가 셀카 단계를 건너뛸 수 있다.
    assert returning.json()["reference_indexed"] is True

    with app.state.session_factory() as db:
        member = db.get(Member, returning.json()["member_id"])
        assert member.reference_key is not None
        assert len(member.uploaded_photos) == 1


def test_a_different_name_still_creates_a_new_member(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    assert join(TestClient(app), album["invite_code"], "서준", "seojun-pw").status_code == 200

    other = join(TestClient(app), album["invite_code"], "예린", "yerin-pw")
    assert other.status_code == 200
    assert other.json()["rejoined"] is False

    members = owner.get(f"/api/albums/{album['album_id']}").json()["members"]
    assert {member["display_name"] for member in members} == {"민지", "서준", "예린"}


def test_short_passcode_is_rejected_before_touching_the_album(tmp_path) -> None:
    owner, app = make_client(tmp_path)
    album = create_album(owner)

    assert join(TestClient(app), album["invite_code"], "서준", "no").status_code == 422
    members = owner.get(f"/api/albums/{album['album_id']}").json()["members"]
    assert len(members) == 1


def test_member_without_a_passcode_can_claim_one_on_first_return(tmp_path) -> None:
    """비밀번호 기능 전에 만들어진 멤버는 해시가 없다. 그 이름으로 처음 들어온 사람이 정한다."""
    owner, app = make_client(tmp_path)
    album = create_album(owner)
    with app.state.session_factory() as db:
        legacy = Member(album_id=album["album_id"], display_name="레거시")
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id

    claimed = join(TestClient(app), album["invite_code"], "레거시", "now-mine")
    assert claimed.status_code == 200
    assert claimed.json()["member_id"] == legacy_id
    assert claimed.json()["rejoined"] is True

    # 한 번 정해진 다음에는 다른 비밀번호로 들어올 수 없다.
    assert join(TestClient(app), album["invite_code"], "레거시", "other-pw").status_code == 403
    assert join(TestClient(app), album["invite_code"], "레거시", "now-mine").status_code == 200

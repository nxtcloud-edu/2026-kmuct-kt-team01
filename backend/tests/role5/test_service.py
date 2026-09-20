from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest

from backend.app.edits import EditError, EditService, EditSettings, edit_key, invalidate_approvals, render_edit
from backend.tests.role5.fixtures import FixtureRepository, FixtureStorage, seed_photo


@pytest.fixture
def env(tmp_path):
    repo = FixtureRepository(tmp_path / "edits_test.sqlite3")
    storage = FixtureStorage(tmp_path / "objects")
    photo, members = seed_photo(repo, storage)
    return EditService(repo, storage), repo, storage, photo, members


def test_versions_use_original_and_survive_restart(env):
    service, repo, storage, photo, members = env
    original_hash = sha256((storage.root / photo.s3_key).read_bytes()).hexdigest()
    first = service.create(photo.id, members[0], EditSettings(0.5, 0))
    second = service.create(photo.id, members[1], EditSettings(1.2, 1.4), first["id"])
    assert second["number"] == 2
    assert second["parent_id"] == first["id"]
    assert second["approval_count"] == 0
    assert second["is_final"] is False
    expected = BytesIO()
    with storage.open_original(photo) as source:
        render_edit(source, expected, EditSettings(1.2, 1.4))
    path = storage.root / edit_key(photo, 2)
    assert path.read_bytes() == expected.getvalue()
    assert sha256((storage.root / photo.s3_key).read_bytes()).hexdigest() == original_hash
    service.approve(second["id"], members[0])
    service.approve(second["id"], members[1])
    restarted = EditService(FixtureRepository(repo.path), FixtureStorage(storage.root))
    restored = restarted.list(photo.id, members[0])["versions"][0]
    assert restored["id"] == second["id"]
    assert restored["brightness"] == 1.2
    assert restored["saturation"] == 1.4
    assert restored["is_final"] is True
    assert path.read_bytes() == expected.getvalue()


def test_approval_is_explicit_idempotent_and_latest_eligible_version_wins(env):
    service, _, _, photo, members = env
    first = service.create(photo.id, members[0], EditSettings())
    for member in members:
        service.approve(first["id"], member)
    service.approve(first["id"], members[0])
    second = service.create(photo.id, members[0], EditSettings())
    assert second["approval_count"] == 0
    assert service.list(photo.id, members[0])["final_edit_id"] == first["id"]
    for member in members:
        service.approve(second["id"], member)
    versions = service.list(photo.id, members[0])
    assert versions["final_edit_id"] == second["id"]
    assert [row["is_final"] for row in versions["versions"]] == [True, False]
    assert versions["versions"][0]["approval_count"] == 2
    service.revoke(second["id"], members[0])
    assert service.list(photo.id, members[0])["final_edit_id"] == first["id"]


def test_non_album_member_cannot_read_edit_or_approve(env):
    service, _, _, photo, members = env
    edit = service.create(photo.id, members[0], EditSettings())
    stranger = str(uuid4())
    for call in [lambda: service.create(photo.id, stranger, EditSettings()),
                 lambda: service.list(photo.id, stranger),
                 lambda: service.approve(edit["id"], stranger),
                 lambda: service.revoke(edit["id"], stranger)]:
        with pytest.raises(EditError) as error:
            call()
        assert error.value.status == 403


def test_unpictured_album_member_cannot_approve(env):
    service, repo, _, photo, members = env
    repo.seed(replace(photo, confirmed_member_ids=frozenset([members[0]])))
    edit = service.create(photo.id, members[1], EditSettings())
    with pytest.raises(EditError) as error:
        service.approve(edit["id"], members[1])
    assert error.value.code == "NOT_APPROVER"


@pytest.mark.parametrize("changes,reason", [
    ({"confirmed_member_ids": frozenset()}, "NO_CONFIRMED_MEMBERS"),
    ({"has_unresolved_faces": True}, "UNRESOLVED_FACES"),
    ({"analysis_status": "failed"}, "ANALYSIS_NOT_READY"),
    ({"analysis_status": "processing"}, "ANALYSIS_NOT_READY"),
])
def test_unknown_uncertain_and_unanalyzed_photos_do_not_become_final(env, changes, reason):
    service, repo, _, photo, members = env
    repo.seed(replace(photo, **changes))
    edit = service.create(photo.id, members[0], EditSettings())
    assert edit["is_final"] is False
    assert edit["approval_blocked_reason"] == reason
    with pytest.raises(EditError):
        service.approve(edit["id"], members[0])


def test_no_face_requires_uploader_explicit_approval(env):
    service, repo, _, photo, members = env
    repo.seed(replace(photo, face_count=0, shot_type="no_face", confirmed_member_ids=frozenset()))
    edit = service.create(photo.id, members[1], EditSettings())
    assert edit["required_member_ids"] == [members[0]]
    assert not edit["is_final"]
    assert service.approve(edit["id"], members[0])["is_final"]


@pytest.mark.parametrize("change", ["add", "exclude", "leave"])
def test_subject_and_member_changes_clear_all_existing_approvals(env, change):
    service, repo, _, photo, members = env
    edit = service.create(photo.id, members[0], EditSettings())
    for member in members:
        service.approve(edit["id"], member)
    if change == "add":
        added = str(uuid4())
        updated = replace(photo, active_member_ids=photo.active_member_ids | {added}, confirmed_member_ids=photo.confirmed_member_ids | {added})
    else:
        updated = replace(photo, confirmed_member_ids=frozenset([members[0]]), active_member_ids=frozenset([members[0]]) if change == "leave" else photo.active_member_ids)
    # Role 3 must perform the photo/member mutation and this hook in ONE transaction.
    with repo.transaction(photo.id) as tx:
        tx.replace_photo(updated)
        invalidate_approvals(tx)
    result = service.list(photo.id, members[0])
    assert result["final_edit_id"] is None
    assert result["versions"][0]["approval_count"] == 0
    repo.seed(photo)  # re-adding a member must not resurrect old approvals
    assert service.list(photo.id, members[0])["final_edit_id"] is None


def test_parent_must_be_from_same_photo(env):
    service, repo, storage, photo, members = env
    other, _ = seed_photo(repo, storage, members=members)
    parent = service.create(other.id, members[0], EditSettings())
    with pytest.raises(EditError) as error:
        service.create(photo.id, members[0], EditSettings(), parent["id"])
    assert error.value.code == "INVALID_PARENT"
    assert service.list(photo.id, members[0])["versions"] == []


@pytest.mark.parametrize("failure", ["storage", "commit"])
def test_failed_save_leaves_no_version_and_preserves_original(env, failure):
    service, repo, storage, photo, members = env
    before = (storage.root / photo.s3_key).read_bytes()
    if failure == "storage":
        storage.fail_write = True
    else:
        repo.fail_commit = True
    with pytest.raises(EditError) as error:
        service.create(photo.id, members[0], EditSettings())
    assert error.value.status == 503
    repo.fail_commit = False
    assert service.list(photo.id, members[0])["versions"] == []
    assert not list(storage.root.rglob("edit-*.jpg"))
    assert (storage.root / photo.s3_key).read_bytes() == before


def test_concurrent_versions_and_approvals_do_not_duplicate(env):
    service, _, storage, photo, members = env
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: service.create(photo.id, members[0], EditSettings()), range(4)))
    assert sorted(row["number"] for row in rows) == [1, 2, 3, 4]
    assert len(list(storage.root.rglob("edit-*.jpg"))) == 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: service.approve(rows[0]["id"], members[0]), range(4)))
    row = next(row for row in service.list(photo.id, members[0])["versions"] if row["id"] == rows[0]["id"])
    assert row["approval_count"] == 1


def test_missing_photo_and_edit_are_404(env):
    service, _, _, _, members = env
    for call in [lambda: service.list(str(uuid4()), members[0]), lambda: service.approve(str(uuid4()), members[0])]:
        with pytest.raises(EditError) as error:
            call()
        assert error.value.status == 404

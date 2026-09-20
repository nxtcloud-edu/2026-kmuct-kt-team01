from __future__ import annotations

import io

import pytest

from backend.app.edit_adapters import BackendEditStorage
from backend.app.storage import LocalStorage
from backend.app.storage import validate_key


@pytest.mark.parametrize(
    "key",
    ["/absolute.jpg", "../escape.jpg", "safe/../escape.jpg", "safe\\bad.jpg", "safe/\x00bad"],
)
def test_storage_key_rejects_unsafe_paths(key: str) -> None:
    with pytest.raises(ValueError):
        validate_key(key)


def test_storage_key_accepts_photo_contract_path() -> None:
    key = "albums/album-id/photos/photo-id/original.jpg"
    assert validate_key(key) == key


def test_edit_storage_maps_role5_key_and_never_overwrites(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    adapter = BackendEditStorage(storage)
    role5_key = "edits/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002/edit-1.jpg"
    canonical = "albums/00000000-0000-0000-0000-000000000001/photos/00000000-0000-0000-0000-000000000002/edit-1.jpg"
    adapter.write_edit(role5_key, io.BytesIO(b"first"))
    assert storage.get(canonical) == b"first"
    with pytest.raises(FileExistsError):
        adapter.write_edit(role5_key, io.BytesIO(b"second"))
    assert storage.get(canonical) == b"first"

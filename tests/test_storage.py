from __future__ import annotations

import pytest

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

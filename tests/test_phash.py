from __future__ import annotations

import io
import random

from PIL import Image
from sqlalchemy import select

from backend.app.models import Photo
from backend.app.phash import (
    DUPLICATE_HAMMING_MAX,
    HASH_HEX_LENGTH,
    compute_dhash,
    hamming_distance,
    looks_like_duplicate,
)
from backend.app.worker import process_one
from tests.test_api import create_album, make_client


def blocky_image(seed: int, size: tuple[int, int] = (240, 176)) -> Image.Image:
    """씬마다 다른 저주파 패턴. 재압축에는 견디고 다른 장면끼리는 확실히 갈린다."""
    rng = random.Random(seed)
    small = Image.new("L", (9, 8))
    small.putdata([rng.randrange(256) for _ in range(72)])
    return small.resize(size, Image.NEAREST).convert("RGB")


def encoded(image: Image.Image, quality: int = 90) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality)
    return output.getvalue()


def test_dhash_survives_recompression_and_resize():
    original = blocky_image(seed=1)
    reference = compute_dhash(encoded(original, quality=95))
    assert reference is not None
    assert len(reference) == HASH_HEX_LENGTH

    recompressed = compute_dhash(encoded(original, quality=35))
    smaller = compute_dhash(encoded(original.resize((120, 88), Image.LANCZOS)))

    assert hamming_distance(reference, recompressed) <= DUPLICATE_HAMMING_MAX
    assert hamming_distance(reference, smaller) <= DUPLICATE_HAMMING_MAX
    assert looks_like_duplicate(reference, recompressed)
    assert looks_like_duplicate(reference, smaller)


def test_dhash_keeps_different_scenes_apart():
    first = compute_dhash(encoded(blocky_image(seed=1)))
    second = compute_dhash(encoded(blocky_image(seed=2)))

    assert hamming_distance(first, second) > DUPLICATE_HAMMING_MAX
    assert looks_like_duplicate(first, second) is False


def test_missing_hashes_are_never_treated_as_duplicates():
    """해시가 없다는 것은 '모른다'는 뜻이다. 같다고 추측하면 남의 사진이 묶인다."""
    assert hamming_distance(None, "0000000000000000") is None
    assert hamming_distance("short", "0000000000000000") is None
    assert looks_like_duplicate(None, None) is False
    assert looks_like_duplicate(None, "0000000000000000") is False


def test_non_image_bytes_yield_no_hash():
    assert compute_dhash(b"not an image at all") is None


def test_duplicate_photos_are_grouped_even_without_capture_time(tmp_path, monkeypatch) -> None:
    """EXIF 촬영 시각이 없는 사진은 3초 규칙으로는 못 묶인다. 해시가 그걸 메운다."""
    client, app = make_client(tmp_path)
    album = create_album(client)
    duplicate = encoded(blocky_image(seed=7), quality=92)
    resaved = encoded(blocky_image(seed=7), quality=40)
    different = encoded(blocky_image(seed=8), quality=92)

    upload = client.post(
        f"/api/albums/{album['album_id']}/photos",
        files=[
            ("files", ("first.jpg", duplicate, "image/jpeg")),
            ("files", ("second.jpg", resaved, "image/jpeg")),
            ("files", ("other.jpg", different, "image/jpeg")),
        ],
    ).json()
    ids = [result["photo"]["id"] for result in upload["results"]]
    assert len(ids) == 3

    def fake_analyze(*_):
        return {
            "faces": [],
            "face_count": 2,
            "shot_type": "group",
            "tags": [],
            "quality": {},
            "best_score": 50.0,
            "provider": "contract-fixture",
            "mode": "mock",
            "capture": {"captured_at": None},
        }

    monkeypatch.setattr("backend.app.worker.analyze", fake_analyze)
    for _ in ids:
        assert process_one(app.state.session_factory, app.state.storage) is True

    with app.state.session_factory() as db:
        photos = [db.get(Photo, photo_id) for photo_id in ids]
        assert all(photo.captured_at is None for photo in photos)
        assert photos[0].burst_group_id is not None
        assert photos[0].burst_group_id == photos[1].burst_group_id
        assert photos[2].burst_group_id is None
        # 묶인 두 장 중 한 장만 대표로 남고, 다른 장면은 그대로 보인다.
        assert [photo.is_best for photo in photos].count(True) == 2
        assert photos[2].is_best is True
        assert db.scalar(select(Photo.phash).where(Photo.id == ids[0])) is not None

"""지각 해시(dHash)로 '내용이 거의 같은 사진'을 찾는다.

연사 묶기(worker.recompute_bursts)는 EXIF 촬영 시각 3초 규칙만 쓰기 때문에
EXIF 가 없는 사진(카톡으로 받은 사진, 스크린샷, 편집본)이나 3초를 넘겨 다시 찍은
같은 장면을 못 잡는다. 여기서 만드는 해시가 그 빈틈을 메운다.

외부 호출이 없다. Pillow 로 64비트를 계산할 뿐이라 사진 1장당 비용이 사실상 0이다.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

__all__ = ["HASH_HEX_LENGTH", "compute_dhash", "hamming_distance", "looks_like_duplicate"]

# 9x8 로 줄여 가로 방향 인접 픽셀 밝기를 비교하면 64비트가 나온다 → 16자리 16진수.
_WIDTH = 9
_HEIGHT = 8
HASH_HEX_LENGTH = 16

# 64비트 중 몇 비트까지 달라도 같은 사진으로 볼지. 작게 잡으면 재촬영본을 놓치고,
# 크게 잡으면 서로 다른 사진이 묶인다. 6은 리사이즈·재압축·약한 보정은 잡고
# 구도가 바뀐 사진은 남기는 지점이다.
DUPLICATE_HAMMING_MAX = 6


def compute_dhash(image_bytes: bytes) -> str | None:
    """사진 바이트에서 dHash 16진수 문자열을 만든다. 읽을 수 없으면 None.

    업로드를 막지 않는 부가 기능이므로 실패는 값 없음으로 돌려준다.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source)
            image = image.convert("L").resize((_WIDTH, _HEIGHT), Image.Resampling.LANCZOS)
            pixels = list(image.getdata())
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None

    bits = 0
    for row in range(_HEIGHT):
        offset = row * _WIDTH
        for column in range(_WIDTH - 1):
            bits <<= 1
            if pixels[offset + column] > pixels[offset + column + 1]:
                bits |= 1
    return f"{bits:0{HASH_HEX_LENGTH}x}"


def hamming_distance(left: str | None, right: str | None) -> int | None:
    """두 해시가 몇 비트 다른지. 한쪽이라도 없거나 형식이 다르면 None(비교 불가)."""
    if not left or not right or len(left) != len(right):
        return None
    try:
        return bin(int(left, 16) ^ int(right, 16)).count("1")
    except ValueError:
        return None


def looks_like_duplicate(left: str | None, right: str | None, threshold: int = DUPLICATE_HAMMING_MAX) -> bool:
    """비교할 수 없으면 False. 없는 정보를 '같다'로 추측하지 않는다."""
    distance = hamming_distance(left, right)
    return distance is not None and distance <= threshold

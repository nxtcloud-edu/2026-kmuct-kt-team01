"""테스트 공통 설정 (역할 4가 추가).

- DB/S3/AWS 를 전혀 건드리지 않는다. 공유 RDS·데모 데이터에 손대지 않는다.
- 샘플 이미지는 Pillow 로 그 자리에서 만든 합성 이미지다(사람 얼굴 사진 아님).
"""

from __future__ import annotations

import io

import pytest
from PIL import Image


def make_image(
    width: int = 640,
    height: int = 480,
    color: tuple[int, int, int] = (120, 160, 200),
    fmt: str = "JPEG",
    exif: Image.Exif | None = None,
) -> bytes:
    """테스트용 합성 이미지. 저장소에 실사진을 두지 않기 위한 장치다."""
    buffer = io.BytesIO()
    img = Image.new("RGB", (width, height), color)
    if exif is not None:
        img.save(buffer, format=fmt, exif=exif)
    else:
        img.save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def jpeg_bytes() -> bytes:
    return make_image()


@pytest.fixture
def other_jpeg_bytes() -> bytes:
    return make_image(color=(30, 200, 90))


@pytest.fixture(autouse=True)
def clean_analysis_env(monkeypatch):
    """테스트가 개발자 로컬 환경변수에 영향을 받지 않게 한다."""
    for key in (
        "FACE_PROVIDER",
        "AWS_REGION",
        "SIMILARITY_THRESHOLD",
        "CANDIDATE_MARGIN",
        "MOCK_MANIFEST_PATH",
        "MOCK_SYNTHETIC_MATCH",
        "S3_BUCKET",
        "SUMMARY_PROVIDER",
        "BEDROCK_MODEL_ID",
    ):
        monkeypatch.delenv(key, raising=False)

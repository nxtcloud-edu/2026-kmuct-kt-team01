"""quality.py 테스트 (역할 4). AWS 호출 없음, DB 접근 없음."""

from __future__ import annotations

import io
from datetime import datetime

import pytest
from PIL import Image

from backend.app.quality import (
    MAX_IMAGE_BYTES,
    MIN_IMAGE_SIDE,
    AnalysisError,
    compute_best_score,
    extract_capture_metadata,
    face_metrics,
    inspect_image,
    iou,
    map_labels_to_tags,
    prepare_image,
    shot_type_for,
)
from tests.conftest import make_image


# --------------------------------------------------------------------------
# 이미지 검사 / 전처리
# --------------------------------------------------------------------------
def test_inspect_image_reads_mime_size_hash(jpeg_bytes):
    info = inspect_image(jpeg_bytes)
    assert info.mime == "image/jpeg"
    assert (info.width, info.height) == (640, 480)
    assert len(info.content_hash) == 64
    assert info.byte_size == len(jpeg_bytes)


def test_png_is_supported():
    info = inspect_image(make_image(fmt="PNG"))
    assert info.mime == "image/png"


def test_non_jpeg_png_is_rejected():
    with pytest.raises(AnalysisError) as err:
        inspect_image(b"GIF89a" + b"\x00" * 100)
    assert err.value.code == "UNSUPPORTED_FORMAT"
    assert err.value.retryable is False


def test_empty_image_is_rejected():
    with pytest.raises(AnalysisError) as err:
        inspect_image(b"")
    assert err.value.code == "EMPTY_IMAGE"


def test_too_small_image_is_rejected():
    tiny = make_image(width=MIN_IMAGE_SIDE - 1, height=200)
    with pytest.raises(AnalysisError) as err:
        prepare_image(tiny)
    assert err.value.code == "IMAGE_TOO_SMALL"


def test_small_image_passes_through_unchanged(jpeg_bytes):
    prepared = prepare_image(jpeg_bytes)
    assert prepared.data is jpeg_bytes
    assert prepared.downscaled is False
    assert prepared.warnings == []


def test_oversized_image_is_downscaled_and_warned():
    # 노이즈로 채워 JPEG 압축이 잘 안 되게 만들어 5MB를 넘긴다.
    import os

    noise = os.urandom(4000 * 3000 * 3)
    buffer = io.BytesIO()
    Image.frombytes("RGB", (4000, 3000), noise).save(buffer, format="JPEG", quality=100)
    big = buffer.getvalue()
    assert len(big) > MAX_IMAGE_BYTES

    prepared = prepare_image(big)
    assert prepared.downscaled is True
    assert prepared.sent_byte_size <= MAX_IMAGE_BYTES
    assert prepared.scale < 1.0
    assert any("작은 얼굴" in w for w in prepared.warnings)
    # 원본 사실은 그대로 보존한다
    assert prepared.original.byte_size == len(big)


# --------------------------------------------------------------------------
# IoU
# --------------------------------------------------------------------------
def test_iou_identical_boxes_is_one():
    b = {"Left": 0.1, "Top": 0.1, "Width": 0.2, "Height": 0.2}
    assert iou(b, b) == pytest.approx(1.0)


def test_iou_disjoint_boxes_is_zero():
    a = {"Left": 0.0, "Top": 0.0, "Width": 0.2, "Height": 0.2}
    b = {"Left": 0.5, "Top": 0.5, "Width": 0.2, "Height": 0.2}
    assert iou(a, b) == 0.0


def test_iou_half_overlap_is_one_third():
    a = {"Left": 0.0, "Top": 0.0, "Width": 0.2, "Height": 0.2}
    b = {"Left": 0.1, "Top": 0.0, "Width": 0.2, "Height": 0.2}
    assert iou(a, b) == pytest.approx(1 / 3)


def test_iou_accepts_lowercase_keys():
    a = {"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2}
    b = {"Left": 0.1, "Top": 0.1, "Width": 0.2, "Height": 0.2}
    assert iou(a, b) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# 태그 매핑
# --------------------------------------------------------------------------
def test_supported_labels_map_to_korean():
    labels = [{"Name": n} for n in ("Mountain", "Food", "Coffee Shop", "Night", "Flower", "Forest", "City")]
    assert map_labels_to_tags(labels) == ["산", "음식", "카페", "야경", "꽃", "숲", "도시"]


def test_common_scene_labels_are_translated_and_unknown_places_are_dropped():
    assert map_labels_to_tags([
        {"Name": "Person"},
        {"Name": "Indoors"},
        {"Name": "Laptop"},
        {"Name": "Dog"},
        {"Name": "Haeundae Beach Resort"},
    ]) == ["실내", "노트북", "반려동물"]


def test_duplicate_tags_collapse():
    assert map_labels_to_tags([{"Name": "Sea"}, {"Name": "Ocean"}, {"Name": "Beach"}]) == ["바다"]


# --------------------------------------------------------------------------
# 품질 지표
# --------------------------------------------------------------------------
def _face(sharpness, brightness, eyes_value, eyes_conf):
    return {
        "Quality": {"Sharpness": sharpness, "Brightness": brightness},
        "EyesOpen": {"Value": eyes_value, "Confidence": eyes_conf},
    }


def test_face_metrics_averages_quality():
    metrics = face_metrics([_face(80, 60, True, 99), _face(60, 80, True, 99)])
    assert metrics["sharpness"] == 70.0
    assert metrics["brightness"] == 70.0
    assert metrics["eyes_open_ratio"] == 1.0


def test_eyes_open_requires_confidence_90():
    metrics = face_metrics(
        [
            _face(80, 60, True, 99),  # 눈 뜸 (확신)
            _face(80, 60, True, 55),  # 눈 뜸이지만 확신 부족 -> 제외
            _face(80, 60, False, 99),  # 눈 감음
            _face(80, 60, True, 90),  # 경계값 90 포함
        ]
    )
    assert metrics["eyes_open_ratio"] == 0.5


def test_face_metrics_without_faces_is_zero():
    assert face_metrics([]) == {"sharpness": 0.0, "brightness": 0.0, "eyes_open_ratio": 0.0}


def test_best_score_formula():
    # 80*0.5 + 0.5*100*0.4 + 70*0.1 = 40 + 20 + 7
    assert compute_best_score({"sharpness": 80, "brightness": 70, "eyes_open_ratio": 0.5}) == 67.0


def test_best_score_caps_brightness_at_100():
    a = compute_best_score({"sharpness": 0, "brightness": 100, "eyes_open_ratio": 0})
    b = compute_best_score({"sharpness": 0, "brightness": 250, "eyes_open_ratio": 0})
    assert a == b == 10.0


def test_open_eyes_beat_closed_eyes_at_equal_sharpness():
    """데모 핵심: 연사 중 눈 안 감은 컷이 위로 올라와야 한다."""
    open_eyes = compute_best_score({"sharpness": 70, "brightness": 70, "eyes_open_ratio": 1.0})
    closed = compute_best_score({"sharpness": 70, "brightness": 70, "eyes_open_ratio": 0.0})
    assert open_eyes > closed


def test_shot_type_mapping():
    assert shot_type_for(0) == "no_face"
    assert shot_type_for(1) == "solo"
    assert shot_type_for(2) == "group"
    assert shot_type_for(7) == "group"


# --------------------------------------------------------------------------
# EXIF
# --------------------------------------------------------------------------
def test_no_exif_means_no_capture_time(jpeg_bytes):
    meta = extract_capture_metadata(jpeg_bytes)
    assert meta.captured_at is None
    assert meta.captured_at_source is None
    assert meta.gps is None
    assert meta.place is None


def test_exif_datetime_is_parsed():
    exif = Image.Exif()
    exif[306] = "2026:09:20 14:03:07"
    meta = extract_capture_metadata(make_image(exif=exif))
    assert meta.captured_at == "2026-09-20T14:03:07"
    assert meta.captured_at_source == "exif:DateTime"
    assert any("시간대" in note for note in meta.notes)


def test_exif_gps_is_converted_to_decimal():
    exif = Image.Exif()
    gps = {1: "N", 2: (37, 33, 0), 3: "E", 4: (126, 58, 0)}
    exif[34853] = gps
    meta = extract_capture_metadata(make_image(exif=exif))
    assert meta.gps is not None
    assert meta.gps["lat"] == pytest.approx(37.55, abs=1e-4)
    assert meta.gps["lon"] == pytest.approx(126.9667, abs=1e-4)
    # 외부 위치 조회 설정이 없으므로 장소 이름은 지어내지 않는다
    assert meta.place is None
    assert meta.place_reason == "REVERSE_GEOCODING_NOT_CONFIGURED"


def test_capture_metadata_is_json_serializable(jpeg_bytes):
    import json

    json.dumps(extract_capture_metadata(jpeg_bytes).to_dict(), ensure_ascii=False)

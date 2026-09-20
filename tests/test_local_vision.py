"""local_vision.py 테스트 (역할 4).

conftest.py 방침과 같다: 실사진을 저장소에 두지 않는다. 얼굴 탐지/비교 모델
자체의 정확도는 Pillow 합성 이미지로 검증할 수 없으므로(진짜 얼굴이 아니라서)
여기서는 계약(입출력 모양·오류 코드)과, 진짜 이미지 없이도 결정론적으로 검증
가능한 부분(색상 휴리스틱, 얼굴 영역 제외 마스크, similarity 보정 함수)만 본다.
실제 얼굴 인식 정확도는 이 테스트의 책임이 아니다(mock 과 마찬가지로 미측정).
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.app import local_vision as lv
from backend.app.quality import AnalysisError
from tests.conftest import make_image


def _encode(bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr)
    assert ok
    return buf.tobytes()


def _solid(h: int, w: int, bgr_color: tuple[int, int, int]) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = bgr_color
    return img


# --------------------------------------------------------------------------
# DetectFaces / CompareFaces — 계약과 오류 변환
# --------------------------------------------------------------------------
def test_detect_faces_on_faceless_image_returns_empty_list():
    assert lv.detect_faces(make_image()) == []


def test_detect_faces_on_garbage_bytes_raises_invalid_image():
    with pytest.raises(AnalysisError) as err:
        lv.detect_faces(b"not an image")
    assert err.value.code == "INVALID_IMAGE"


def test_compare_faces_raises_invalid_parameter_when_source_has_no_face():
    """소스(기준 셀카)에 얼굴이 없으면 Rekognition의 InvalidParameterException과
    같은 자리(INVALID_PARAMETER)로 떨어져야 analysis.py 의 멤버-스킵 로직이 먹는다."""
    with pytest.raises(AnalysisError) as err:
        lv.compare_faces(make_image(), make_image(), similarity_threshold=50.0)
    assert err.value.code == "INVALID_PARAMETER"


def test_similarity_score_is_50_at_the_sface_decision_boundary():
    assert lv._similarity_score(lv._SFACE_COSINE_DECISION) == pytest.approx(50.0, abs=0.01)


def test_similarity_score_increases_with_cosine():
    low = lv._similarity_score(0.0)
    mid = lv._similarity_score(lv._SFACE_COSINE_DECISION)
    high = lv._similarity_score(0.9)
    assert low < mid < high
    assert 0.0 <= low <= 100.0
    assert 0.0 <= high <= 100.0


def test_missing_model_files_raise_dependency_missing(monkeypatch):
    monkeypatch.setattr(lv, "_detector", None)
    monkeypatch.setattr(lv, "_YUNET_PATH", lv.MODELS_DIR / "does-not-exist.onnx")
    with pytest.raises(AnalysisError) as err:
        lv.detect_faces(make_image())
    assert err.value.code == "DEPENDENCY_MISSING"


# --------------------------------------------------------------------------
# DetectLabels — 색상·질감 휴리스틱
# --------------------------------------------------------------------------
def test_sea_scene_is_detected_from_color_composition():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:160] = (235, 206, 135)  # BGR: 위쪽 옅은 하늘색
    img[160:] = (180, 140, 60)  # BGR: 아래쪽 짙은 청록(바다)
    labels = lv.detect_labels(_encode(img), min_confidence=50)
    names = {label["Name"] for label in labels}
    assert "sea" in names


def test_forest_scene_needs_both_green_and_texture():
    rng = np.random.default_rng(1)
    green_flat = _solid(480, 640, (40, 120, 40))
    labels_flat = lv.detect_labels(_encode(green_flat), min_confidence=50)
    assert "forest" not in {label["Name"] for label in labels_flat}

    noisy = green_flat.astype(np.int16) + rng.integers(-60, 60, green_flat.shape)
    green_textured = np.clip(noisy, 0, 255).astype(np.uint8)
    labels_textured = lv.detect_labels(_encode(green_textured), min_confidence=50)
    assert "forest" in {label["Name"] for label in labels_textured}


def test_city_scene_needs_straight_lines():
    gray_flat = _solid(480, 640, (170, 170, 170))
    assert "city" not in {
        label["Name"] for label in lv.detect_labels(_encode(gray_flat), min_confidence=50)
    }

    grid = gray_flat.copy()
    for x in range(0, 640, 30):
        cv2.line(grid, (x, 0), (x, 480), (40, 40, 40), 3)
    for y in range(0, 480, 25):
        cv2.line(grid, (0, y), (640, y), (40, 40, 40), 3)
    assert "city" in {label["Name"] for label in lv.detect_labels(_encode(grid), min_confidence=50)}


def test_low_confidence_labels_are_dropped_by_default_threshold():
    """min_confidence 를 지정하지 않으면(기본 80) 애매한 신호는 아예 안 나온다 —
    없는 태그를 지어내지 않는다는 quality.py 의 기존 원칙과 같다."""
    weak = _solid(480, 640, (150, 150, 150))
    weak[200:280, 280:360] = (200, 230, 255)  # 작은 밝은 점 하나 정도로는 확신 부족
    labels = lv.detect_labels(_encode(weak))  # 기본 min_confidence=80
    assert labels == []


# --------------------------------------------------------------------------
# 얼굴 영역 제외 마스크 — 피부색이 '노을' 색상대와 겹치는 문제의 회귀 테스트
# --------------------------------------------------------------------------
def test_face_boxes_are_excluded_from_scene_color_statistics():
    """상단 2/3 전체를 '노을' 색으로 채우면 face_boxes 없이는 노을로 잡혀야 하고,
    그 영역 전체를 얼굴 박스로 넘기면(제외되어) 더 이상 잡히면 안 된다."""
    img = _solid(480, 640, (60, 120, 230))  # BGR 따뜻한 주황
    without_mask = lv.detect_labels(_encode(img), min_confidence=50)
    assert "sunset" in {label["Name"] for label in without_mask}

    full_top_two_thirds_box = {"Left": 0.0, "Top": 0.0, "Width": 1.0, "Height": 2.0 / 3.0}
    with_mask = lv.detect_labels(
        _encode(img), min_confidence=50, face_boxes=[full_top_two_thirds_box]
    )
    assert "sunset" not in {label["Name"] for label in with_mask}


def test_face_boxes_with_zero_size_are_ignored_without_crashing():
    img = _solid(480, 640, (60, 120, 230))
    labels = lv.detect_labels(
        _encode(img), min_confidence=50, face_boxes=[{"Left": 0.5, "Top": 0.5, "Width": 0.0, "Height": 0.0}]
    )
    assert "sunset" in {label["Name"] for label in labels}

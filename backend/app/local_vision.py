"""ZZIK 로컬(오프라인) 얼굴·장면 분석 백엔드 (역할 4 소유).

AWS Rekognition 권한이 없을 때 FACE_PROVIDER=local 로 바꾸면 analysis.py 가
boto3 대신 이 모듈을 쓴다. AWS를 전혀 호출하지 않는다.

무엇으로 대신하는가
  DetectFaces / CompareFaces
    OpenCV YuNet(얼굴 탐지) + SFace(128차원 얼굴 임베딩). 둘 다 OpenCV Zoo가
    공개한 사전학습 모델이라 실제 얼굴 인식에 가까운 품질을 낸다(사람이 만든
    게 아니라 학습된 모델). Sharpness/Brightness는 얼굴 영역 픽셀에서 직접
    계산하고, EyesOpen은 눈 검출기(Haar cascade)가 눈을 찾았는지로 근사한다
    — Rekognition의 EyesOpen만큼 정교하진 않다(눈 검출 실패 ≠ 감은 눈).

  DetectLabels
    학습된 분류기가 아니라 색상·질감 규칙 기반 추정이다(HSV 색 분포, 엣지
    밀도, 직선 검출). Rekognition만큼 정확하지 않으니 참고용으로만 쓴다.
    확신이 없으면 태그를 안 붙이는 쪽으로 보수적으로 짰다(가짜 태그보다
    태그 없음이 낫다는 quality.py의 기존 원칙과 같다).

모델 파일: backend/models/
  face_detection_yunet_2023mar.onnx    (~230KB)
  face_recognition_sface_2021dec.onnx  (~37MB)
  haarcascade_eye.xml                  (~340KB)
  scripts/download_models.sh 로 다시 받을 수 있다. 파일이 없으면
  AnalysisError(DEPENDENCY_MISSING) 를 올린다(조용히 다른 걸로 안 바꾼다).

의존성: opencv-python-headless, numpy (requirements.txt)
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Mapping

from .quality import MAX_COMPARE_TARGET_FACES, AnalysisError

__all__ = [
    "detect_faces",
    "compare_faces",
    "detect_labels",
    "MODELS_DIR",
]

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
_YUNET_PATH = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
_SFACE_PATH = MODELS_DIR / "face_recognition_sface_2021dec.onnx"
_EYE_CASCADE_PATH = MODELS_DIR / "haarcascade_eye.xml"

# YuNet 저장소가 권장하는 기본값.
_DETECT_SCORE_THRESHOLD = 0.6
_DETECT_NMS_THRESHOLD = 0.3
_DETECT_TOP_K = 5000

# SFace 공식 권장 판정 경계(cosine, LFW 기준 FAR=1e-3). 이 값을 0~100 점수의
# 중간(50점)으로 두는 로지스틱 보정을 쓴다 — Rekognition의 Similarity(0~100,
# 기본 임계 90)와 같은 감각으로 SIMILARITY_THRESHOLD/CANDIDATE_MARGIN 설정을
# 그대로 재사용하기 위해서다.
_SFACE_COSINE_DECISION = 0.363
_SFACE_LOGISTIC_K = 10.0

_EYES_OPEN_CONFIDENCE_WHEN_DETECTED = 96.0
_EYES_OPEN_CONFIDENCE_WHEN_NOT_DETECTED = 55.0  # 미검출 ≠ 감음. 확신을 낮게 둔다.

_CACHE_MAX = 16

_lock = threading.Lock()
_detector = None
_recognizer = None
_eye_cascade = None
_target_cache: "OrderedDict[str, tuple[list, list]]" = OrderedDict()
_source_cache: "OrderedDict[str, Any]" = OrderedDict()


# --------------------------------------------------------------------------
# 모델 로딩 (프로세스당 한 번만)
# --------------------------------------------------------------------------
def _cv2():
    try:
        import cv2  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 의존성 누락 환경
        raise AnalysisError(
            "DEPENDENCY_MISSING",
            "서버에 로컬 분석 라이브러리(opencv-python)가 설치되어 있지 않습니다",
            retryable=False,
            details={"package": "opencv-python-headless"},
        ) from exc
    import cv2

    return cv2


def _require_model_files() -> None:
    missing = [str(p) for p in (_YUNET_PATH, _SFACE_PATH, _EYE_CASCADE_PATH) if not p.exists()]
    if missing:
        raise AnalysisError(
            "DEPENDENCY_MISSING",
            "로컬 분석 모델 파일이 없습니다 (scripts/download_models.sh 실행 필요)",
            retryable=False,
            details={"missing": missing},
        )


def _get_detector(cv2):
    global _detector
    if _detector is None:
        with _lock:
            if _detector is None:
                _require_model_files()
                _detector = cv2.FaceDetectorYN_create(
                    str(_YUNET_PATH),
                    "",
                    (320, 320),
                    score_threshold=_DETECT_SCORE_THRESHOLD,
                    nms_threshold=_DETECT_NMS_THRESHOLD,
                    top_k=_DETECT_TOP_K,
                )
    return _detector


def _get_recognizer(cv2):
    global _recognizer
    if _recognizer is None:
        with _lock:
            if _recognizer is None:
                _require_model_files()
                _recognizer = cv2.FaceRecognizerSF_create(str(_SFACE_PATH), "")
    return _recognizer


def _get_eye_cascade(cv2):
    global _eye_cascade
    if _eye_cascade is None:
        with _lock:
            if _eye_cascade is None:
                _require_model_files()
                cascade = cv2.CascadeClassifier(str(_EYE_CASCADE_PATH))
                if cascade.empty():
                    raise AnalysisError(
                        "DEPENDENCY_MISSING", "눈 검출 모델을 불러오지 못했습니다", retryable=False
                    )
                _eye_cascade = cascade
    return _eye_cascade


# --------------------------------------------------------------------------
# 공통 유틸
# --------------------------------------------------------------------------
def _decode(cv2, image_bytes: bytes):
    import numpy as np

    array = np.frombuffer(image_bytes, dtype="uint8")
    img = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if img is None:
        raise AnalysisError("INVALID_IMAGE", "이미지를 읽을 수 없습니다", retryable=False)
    return img


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _detect_raw(cv2, img) -> list:
    detector = _get_detector(cv2)
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(img)
    return [] if faces is None else list(faces)


def _cache_put(cache: "OrderedDict[str, Any]", key: str, value: Any) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _CACHE_MAX:
        cache.popitem(last=False)


# --------------------------------------------------------------------------
# DetectFaces
# --------------------------------------------------------------------------
def _quality_for_face(cv2, img, x: int, y: int, w: int, h: int) -> dict[str, Any]:
    ih, iw = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(iw, x + w), min(ih, y + h)
    if x1 <= x0 or y1 <= y0:
        return {
            "Quality": {"Sharpness": 0.0, "Brightness": 0.0},
            "EyesOpen": {"Value": False, "Confidence": _EYES_OPEN_CONFIDENCE_WHEN_NOT_DETECTED},
        }

    crop_gray = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(crop_gray, cv2.CV_64F).var())
    # 경험적 스케일: 또렷한 얼굴 사진의 분산은 대략 500~2000대라 /10 로 0~100 근처에 맞춘다.
    sharpness = round(min(100.0, lap_var / 10.0), 4)
    brightness = round(float(crop_gray.mean()) / 255.0 * 100.0, 4)

    eye_cascade = _get_eye_cascade(cv2)
    min_side = max(8, min(w, h) // 8)
    eyes = eye_cascade.detectMultiScale(
        crop_gray, scaleFactor=1.05, minNeighbors=5, minSize=(min_side, min_side)
    )
    eyes_open = len(eyes) >= 1
    return {
        "Quality": {"Sharpness": sharpness, "Brightness": brightness},
        "EyesOpen": {
            "Value": eyes_open,
            "Confidence": _EYES_OPEN_CONFIDENCE_WHEN_DETECTED
            if eyes_open
            else _EYES_OPEN_CONFIDENCE_WHEN_NOT_DETECTED,
        },
    }


def detect_faces(image_bytes: bytes) -> list[dict[str, Any]]:
    """Rekognition DetectFaces(Attributes=['ALL']) 의 FaceDetails 와 같은 모양으로 돌려준다."""
    cv2 = _cv2()
    img = _decode(cv2, image_bytes)
    ih, iw = img.shape[:2]
    rows = _detect_raw(cv2, img)

    details: list[dict[str, Any]] = []
    for row in rows:
        x, y, w, h, score = (float(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[-1]))
        extra = _quality_for_face(cv2, img, int(round(x)), int(round(y)), int(round(w)), int(round(h)))
        details.append(
            {
                "BoundingBox": {
                    "Left": _clamp01(x / iw),
                    "Top": _clamp01(y / ih),
                    "Width": _clamp01(w / iw),
                    "Height": _clamp01(h / ih),
                },
                "Confidence": round(_clamp01(score) * 100.0, 4),
                **extra,
            }
        )
    return details


# --------------------------------------------------------------------------
# CompareFaces
# --------------------------------------------------------------------------
def _similarity_score(cosine: float) -> float:
    """SFace cosine(-1~1) 을 Rekognition Similarity(0~100) 감각으로 로지스틱 보정한다."""
    score = 100.0 / (1.0 + math.exp(-_SFACE_LOGISTIC_K * (cosine - _SFACE_COSINE_DECISION)))
    return round(score, 4)


def _source_embedding(cv2, recognizer, source_bytes: bytes):
    key = hashlib.sha256(source_bytes).hexdigest()
    cached = _source_cache.get(key)
    if cached is not None:
        _source_cache.move_to_end(key)
        return cached

    source_img = _decode(cv2, source_bytes)
    rows = _detect_raw(cv2, source_img)
    if not rows:
        raise AnalysisError(
            "INVALID_PARAMETER",
            "이미지에서 비교할 얼굴을 찾지 못했습니다",
            retryable=False,
        )
    best_row = max(rows, key=lambda r: float(r[-1]))
    embedding = recognizer.feature(recognizer.alignCrop(source_img, best_row))
    _cache_put(_source_cache, key, embedding)
    return embedding


def _target_rows_and_embeddings(cv2, recognizer, target_bytes: bytes):
    key = hashlib.sha256(target_bytes).hexdigest()
    cached = _target_cache.get(key)
    if cached is not None:
        _target_cache.move_to_end(key)
        return cached

    target_img = _decode(cv2, target_bytes)
    rows = _detect_raw(cv2, target_img)
    if len(rows) > MAX_COMPARE_TARGET_FACES:
        rows = sorted(rows, key=lambda r: float(r[-1]), reverse=True)[:MAX_COMPARE_TARGET_FACES]
    embeddings = [recognizer.feature(recognizer.alignCrop(target_img, row)) for row in rows]
    value = (rows, embeddings)
    _cache_put(_target_cache, key, value)
    return value


def compare_faces(source_bytes: bytes, target_bytes: bytes, similarity_threshold: float) -> list[dict[str, Any]]:
    """Rekognition CompareFaces 의 FaceMatches 와 같은 모양으로 돌려준다.

    source_bytes(기준 셀카)에 얼굴이 여러 개면 가장 confident 한 얼굴 하나를 쓴다
    (validate_reference 가 등록 시점에 1개인지 이미 확인하지만, analyze() 는 다시
    확인하지 않고 넘어온 그대로 쓰기 때문에 여기서도 방어한다).
    """
    cv2 = _cv2()
    recognizer = _get_recognizer(cv2)

    source_embedding = _source_embedding(cv2, recognizer, source_bytes)
    target_img = _decode(cv2, target_bytes)
    ih, iw = target_img.shape[:2]
    target_rows, target_embeddings = _target_rows_and_embeddings(cv2, recognizer, target_bytes)

    matches: list[dict[str, Any]] = []
    for row, embedding in zip(target_rows, target_embeddings):
        cosine = float(recognizer.match(source_embedding, embedding, cv2.FaceRecognizerSF_FR_COSINE))
        score = _similarity_score(cosine)
        if score < similarity_threshold:
            continue
        x, y, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
        matches.append(
            {
                "Similarity": score,
                "Face": {
                    "BoundingBox": {
                        "Left": _clamp01(x / iw),
                        "Top": _clamp01(y / ih),
                        "Width": _clamp01(w / iw),
                        "Height": _clamp01(h / ih),
                    }
                },
            }
        )
    return matches


# --------------------------------------------------------------------------
# DetectLabels — 색상·질감 휴리스틱 (학습된 분류기가 아니다)
# --------------------------------------------------------------------------
def _hue_ratio(
    region,
    lo: int,
    hi: int,
    s_min: int = 40,
    v_min: int = 40,
    s_max: int = 255,
    v_max: int = 255,
) -> float:
    import numpy as np

    h, s, v, valid = region
    if hi >= lo:
        hue_mask = (h >= lo) & (h <= hi)
    else:  # 색상환이 0/179 에서 겹치는 red 구간
        hue_mask = (h >= lo) | (h <= hi)
    mask = hue_mask & (s >= s_min) & (s <= s_max) & (v >= v_min) & (v <= v_max) & valid
    denom = int(np.count_nonzero(valid))
    return float(np.count_nonzero(mask)) / denom if denom else 0.0


def _region_channels(hsv, y0: int, y1: int, x0: int, x1: int, valid_full=None):
    """valid_full: 전체 이미지 크기의 bool 마스크(True=계산에 포함). None 이면 전부 포함."""
    import numpy as np

    crop = hsv[y0:y1, x0:x1]
    valid = np.ones(crop.shape[:2], dtype=bool) if valid_full is None else valid_full[y0:y1, x0:x1]
    return crop[:, :, 0], crop[:, :, 1], crop[:, :, 2], valid


def _build_exclude_mask(h: int, w: int, face_boxes):
    """얼굴 + 목/어깨 추정 영역을 제외 마스크로 만든다.

    살구색 피부는 '노을' 따뜻한 색상대와, 청바지·셔츠는 '바다' 파란 색상대와 겹친다.
    장면 태그는 인물이 아니라 배경을 보고 판단해야 하므로 사람으로 짐작되는 영역을
    장면 색상 통계에서 미리 뺀다(정밀한 사람 분할이 아니라 얼굴 박스를 넉넉히 부풀린
    근사치다).
    """
    if not face_boxes:
        return None
    import numpy as np

    mask = np.zeros((h, w), dtype=bool)
    for box in face_boxes:
        left = float(box.get("Left", 0.0)) * w
        top = float(box.get("Top", 0.0)) * h
        width = float(box.get("Width", 0.0)) * w
        height = float(box.get("Height", 0.0)) * h
        if width <= 0 or height <= 0:
            continue
        cx = left + width / 2.0
        ex_w = width * 2.4
        ex_h = height * 3.6
        x0 = int(max(0, cx - ex_w / 2))
        x1 = int(min(w, cx + ex_w / 2))
        y0 = int(max(0, top - height * 0.3))
        y1 = int(min(h, top + ex_h))
        mask[y0:y1, x0:x1] = True
    return mask


def _straight_line_ratio(cv2, gray, edges, valid_full=None) -> float:
    h, w = gray.shape[:2]
    if valid_full is not None:
        edges = cv2.bitwise_and(edges, edges, mask=valid_full.astype("uint8") * 255)
    min_len = max(20, int(min(h, w) * 0.15))
    lines = cv2.HoughLinesP(edges, 1, math.pi / 180, threshold=70, minLineLength=min_len, maxLineGap=8)
    if lines is None:
        return 0.0
    total_len = 0.0
    for line in lines[:, 0, :]:
        x1, y1, x2, y2 = line
        total_len += math.hypot(x2 - x1, y2 - y1)
    return min(1.0, total_len / (h * w) ** 0.5 / 20.0)


def _point_light_ratio(cv2, np, v_channel, valid_full=None) -> float:
    """작은(전체의 2% 미만) 밝은 덩어리들의 비율 — 야간 조명 신호."""
    bright = (v_channel > 210)
    if valid_full is not None:
        bright = bright & valid_full
    bright = bright.astype("uint8") * 255
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
    total = int(np.count_nonzero(valid_full)) if valid_full is not None else v_channel.size
    if total == 0:
        return 0.0
    ratio = 0.0
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area / total < 0.02:
            ratio += area / total
    return ratio


def detect_labels(
    image_bytes: bytes, *, min_confidence: float = 80.0, face_boxes: list[Mapping[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Rekognition DetectLabels 의 Labels 와 같은 모양([{Name, Confidence}])으로 돌려준다.

    학습된 이미지 분류기가 아니라 HSV 색 분포·엣지·직선 검출 규칙 기반 추정이다.
    확신이 낮으면(min_confidence 미만) 아예 포함하지 않는다 — 없는 태그를 지어내지 않는다.

    face_boxes 를 주면(analysis.py 가 DetectFaces 결과의 BoundingBox 를 넘긴다) 그
    영역(+목/어깨 추정치)을 장면 색상 통계에서 뺀다. 사람 피부색이 '노을'의 따뜻한
    색상대와 겹쳐서, 얼굴을 빼지 않으면 인물 사진마다 엉뚱하게 노을/바다 태그가 붙는다.
    """
    cv2 = _cv2()
    import numpy as np

    img = _decode(cv2, image_bytes)
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 160)
    exclude = _build_exclude_mask(h, w, face_boxes)
    valid_full = ~exclude if exclude is not None else None

    full = _region_channels(hsv, 0, h, 0, w, valid_full)
    top = _region_channels(hsv, 0, h // 3, 0, w, valid_full)
    top_two_thirds = _region_channels(hsv, 0, (2 * h) // 3, 0, w, valid_full)
    bottom_two_thirds = _region_channels(hsv, h // 3, h, 0, w, valid_full)
    center = _region_channels(hsv, h // 4, (3 * h) // 4, w // 4, (3 * w) // 4, valid_full)

    def warm(region, s_min=60, v_min=50):
        return _hue_ratio(region, 170, 8, s_min, v_min) + _hue_ratio(region, 8, 33, s_min, v_min)

    green_ratio_of = lambda region: _hue_ratio(region, 33, 85, 35, 35)
    blue_ratio_of = lambda region: _hue_ratio(region, 85, 130, 25, 40)
    purple_pink_ratio_of = lambda region: _hue_ratio(region, 130, 169, 50, 50)

    v_full_channel, valid_full_arr = full[2], full[3]
    valid_count = int(np.count_nonzero(valid_full_arr))
    v_mean = float(v_full_channel[valid_full_arr].mean()) if valid_count else 0.0
    dark_ratio = float(np.count_nonzero((v_full_channel < 60) & valid_full_arr)) / valid_count if valid_count else 0.0
    point_light_ratio = _point_light_ratio(cv2, np, v_full_channel, valid_full_arr)
    edge_ratio = float(np.count_nonzero(edges.astype(bool) & valid_full_arr)) / valid_count if valid_count else 0.0
    straight_ratio = _straight_line_ratio(cv2, gray, edges, valid_full_arr)
    s_full_channel = full[1]
    desat_ratio = float(np.count_nonzero((s_full_channel < 60) & valid_full_arr)) / valid_count if valid_count else 0.0

    warm_top2 = warm(top_two_thirds)
    warm_center = warm(center, s_min=60, v_min=50)
    warm_full = warm(full)
    green_full = green_ratio_of(full)
    blue_bottom2 = blue_ratio_of(bottom_two_thirds)
    blue_top = blue_ratio_of(top)
    vivid_full = warm(full, s_min=140, v_min=110) + purple_pink_ratio_of(full)
    # 따뜻한 색이 중앙에 몰려 있는 정도 — 클로즈업 피사체(음식 등)일수록 1에 가깝다.
    centrality = _clamp(warm_center / max(warm_full, 1e-6), 0.0, 2.0) / 2.0

    # 물(하단)의 질감: 수면은 육지·건물보다 엣지가 적다.
    bottom_valid = valid_full_arr[h // 3 :, :]
    bottom_edges = edges.astype(bool)[h // 3 :, :] & bottom_valid
    bottom_valid_count = int(np.count_nonzero(bottom_valid))
    bottom_edge_ratio = float(np.count_nonzero(bottom_edges)) / bottom_valid_count if bottom_valid_count else 0.0

    scores: dict[str, float] = {}

    # 야경: 전체적으로 어둡고, 작은 밝은 점(조명)들이 있다.
    scores["night"] = (
        _clamp((dark_ratio - 0.30) / 0.5, 0.0, 1.0) * 70.0
        + _clamp(point_light_ratio / 0.012, 0.0, 1.0) * 30.0
    )

    # 노을: 상단 2/3에 따뜻한 색이 넓게 퍼져 있고, 너무 어둡거나 하얗게 날아가지 않았다.
    plausible_v = 1.0 if 60.0 <= v_mean <= 215.0 else 0.5
    scores["sunset"] = _clamp(warm_top2 / 0.30, 0.0, 1.0) * 100.0 * plausible_v

    # 바다: 하단 2/3가 파란/청록 계열이고 엣지(질감)가 적다(잔잔한 수면).
    sea_texture_gate = 1.0 if bottom_edge_ratio < 0.12 else 0.5
    scores["sea"] = _clamp(blue_bottom2 / 0.28, 0.0, 1.0) * 100.0 * sea_texture_gate

    # 산: 상단에 하늘(파랑/밝은 무채색)이 있고 하단에 채도가 과하지 않은 녹색/흙빛 지형이
    # 넓게 퍼져 있으며, 인공 직선은 적고, 한가운데 클로즈업 피사체(음식 등)가 아니다.
    earthy_bottom = green_ratio_of(bottom_two_thirds) + _hue_ratio(
        bottom_two_thirds, 8, 33, s_min=15, v_min=40, s_max=150
    )
    top_valid_count = int(np.count_nonzero(top[3]))
    hazy_sky_top = (
        float(np.count_nonzero((top[1] < 40) & (top[2] > 150) & top[3])) / top_valid_count
        if top_valid_count
        else 0.0
    )
    sky_signal = _clamp((blue_top + hazy_sky_top) / 0.20, 0.0, 1.0)
    low_manmade = 1.0 - _clamp(straight_ratio / 0.15, 0.0, 1.0)
    not_closeup = 1.0 - centrality
    scores["mountain"] = (
        _clamp(earthy_bottom / 0.22, 0.0, 1.0) * sky_signal * low_manmade * not_closeup * 100.0
    )

    # 숲: 초록이 넓고 엣지(잎·가지 질감)가 많다.
    scores["forest"] = _clamp(green_full / 0.35, 0.0, 1.0) * _clamp(edge_ratio / 0.12, 0.0, 1.0) * 100.0

    # 꽃: 초록 배경 위에 작고 선명한 색 덩어리(꽃잎)가 있다 — 화면 전체를 덮지는 않는다.
    green_context_gate = max(0.4, _clamp(green_full / 0.12, 0.0, 1.0))
    scores["flower"] = _clamp(vivid_full / 0.05, 0.0, 1.0) * green_context_gate * 100.0

    # 음식: 따뜻한 색이 중앙에 몰려 있고(클로즈업), 자연 배경(초록/하늘)이 적다.
    green_penalty = 1.0 - _clamp(green_full / 0.25, 0.0, 1.0)
    blue_penalty = 1.0 - _clamp(blue_bottom2 / 0.25, 0.0, 1.0)
    scores["food"] = _clamp(warm_center / 0.35, 0.0, 1.0) * green_penalty * blue_penalty * centrality * 100.0

    # 카페: 실내 톤(은은한 갈색·중간 밝기, 채도가 너무 높지 않음)이고 트인 하늘이 없다.
    # 가장 약한 신호라 보수적으로 잡는다.
    neutral_warm = _hue_ratio(full, 10, 30, s_min=20, v_min=50, s_max=140, v_max=200)
    indoor_v_gate = 1.0 if 50.0 <= v_mean <= 190.0 else 0.4
    no_sky_gate = 1.0 - _clamp(blue_top / 0.15, 0.0, 1.0)
    scores["cafe"] = _clamp(neutral_warm / 0.28, 0.0, 1.0) * indoor_v_gate * no_sky_gate * 90.0

    # 도시: 직선(건물·창문)이 많고 채도가 낮은(콘크리트·유리) 픽셀이 많다.
    scores["city"] = (
        _clamp(straight_ratio / 0.04, 0.0, 1.0)
        * _clamp(desat_ratio / 0.40, 0.0, 1.0)
        * (1.0 - _clamp(green_full / 0.30, 0.0, 1.0))
        * 100.0
    )

    labels = [
        {"Name": name, "Confidence": round(_clamp(score, 0.0, 100.0), 4)}
        for name, score in scores.items()
        if score >= min_confidence
    ]
    labels.sort(key=lambda entry: entry["Confidence"], reverse=True)
    return labels

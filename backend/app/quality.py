"""ZZIK 이미지 메타데이터·품질 계산 (역할 4 소유).

이 모듈은 AWS를 호출하지 않는 순수 계산 계층이다.
analysis.py 가 이 모듈을 쓰고, 3번(백엔드)도 필요하면 직접 호출할 수 있다.

여기서 하지 않는 것:
  - DB 접근, S3 접근, API 라우팅, worker 트랜잭션 (3번 몫)
  - 얼굴 임베딩 계산 (Rekognition 이 한다)
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "AnalysisError",
    "ImageInfo",
    "PreparedImage",
    "CaptureMetadata",
    "MAX_IMAGE_BYTES",
    "MIN_IMAGE_SIDE",
    "MAX_COMPARE_TARGET_FACES",
    "LABEL_TAG_MAP",
    "inspect_image",
    "prepare_image",
    "iou",
    "map_labels_to_tags",
    "face_metrics",
    "compute_best_score",
    "extract_capture_metadata",
]


# --------------------------------------------------------------------------
# 오류 타입
# --------------------------------------------------------------------------
class AnalysisError(Exception):
    """분석 계층의 단일 오류 타입.

    계약: AnalysisError(code, message_ko, retryable)
    analysis.py 에서 re-export 하므로 `from app.analysis import AnalysisError` 도 동작한다.
    (quality.py 가 하위 계층이라 정의만 여기 둔다. 순환 import 회피 목적.)

    to_dict() 는 공통 JSON 오류 형식 {code, message, details?} 을 그대로 돌려준다.
    """

    def __init__(
        self,
        code: str,
        message_ko: str,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message_ko}")
        self.code = code
        self.message_ko = message_ko
        self.retryable = bool(retryable)
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message_ko}
        details = dict(self.details)
        details["retryable"] = self.retryable
        payload["details"] = details
        return payload

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return f"AnalysisError(code={self.code!r}, retryable={self.retryable})"


# --------------------------------------------------------------------------
# 입력 제한 (Rekognition raw bytes 기준)
# --------------------------------------------------------------------------
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MIN_IMAGE_SIDE = 80
# CompareFaces 는 대상 이미지에서 최대 100개 얼굴만 비교한다.
MAX_COMPARE_TARGET_FACES = 100

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _require_pil():
    try:
        from PIL import Image, ImageOps  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 의존성 누락 환경
        raise AnalysisError(
            "DEPENDENCY_MISSING",
            "서버에 이미지 처리 라이브러리(Pillow)가 설치되어 있지 않습니다",
            retryable=False,
            details={"package": "pillow"},
        ) from exc
    from PIL import Image, ImageOps

    return Image, ImageOps


# --------------------------------------------------------------------------
# 이미지 검사 / 전처리
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ImageInfo:
    mime: str
    width: int
    height: int
    byte_size: int
    content_hash: str  # sha256 hex


@dataclass
class PreparedImage:
    """Rekognition 에 실제로 보낼 바이트와, 원본에 대한 사실 기록."""

    data: bytes
    original: ImageInfo
    sent_byte_size: int
    downscaled: bool = False
    scale: float = 1.0
    warnings: list[str] = field(default_factory=list)


def _sniff_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if image_bytes.startswith(_PNG_MAGIC):
        return "image/png"
    raise AnalysisError(
        "UNSUPPORTED_FORMAT",
        "JPEG 또는 PNG 파일만 업로드할 수 있습니다",
        retryable=False,
    )


def inspect_image(image_bytes: bytes) -> ImageInfo:
    """포맷·크기·해시를 읽는다. 업로드 저장 전에 3번이 써도 되는 함수다."""
    if not image_bytes:
        raise AnalysisError("EMPTY_IMAGE", "이미지 데이터가 비어 있습니다", retryable=False)

    mime = _sniff_mime(image_bytes)
    Image, _ = _require_pil()
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size
    except AnalysisError:
        raise
    except Exception as exc:
        raise AnalysisError(
            "INVALID_IMAGE",
            "이미지를 읽을 수 없습니다",
            retryable=False,
        ) from exc

    return ImageInfo(
        mime=mime,
        width=int(width),
        height=int(height),
        byte_size=len(image_bytes),
        content_hash=hashlib.sha256(image_bytes).hexdigest(),
    )


def prepare_image(image_bytes: bytes) -> PreparedImage:
    """Rekognition 입력 제한(5MB, 최소 80px)에 맞춘다.

    5MB 를 넘으면 축소해서 보내고, 축소 사실과 "작은 얼굴이 사라질 수 있음"을
    warnings 에 남긴다. 축소 사실을 숨기지 않는다.
    """
    info = inspect_image(image_bytes)

    if info.width < MIN_IMAGE_SIDE or info.height < MIN_IMAGE_SIDE:
        raise AnalysisError(
            "IMAGE_TOO_SMALL",
            f"이미지가 너무 작습니다 (가로·세로 각각 최소 {MIN_IMAGE_SIDE}px 필요)",
            retryable=False,
            details={"width": info.width, "height": info.height},
        )

    if info.byte_size <= MAX_IMAGE_BYTES:
        return PreparedImage(
            data=image_bytes,
            original=info,
            sent_byte_size=info.byte_size,
        )

    data, scale, warnings = _downscale_to_limit(image_bytes, info)
    return PreparedImage(
        data=data,
        original=info,
        sent_byte_size=len(data),
        downscaled=True,
        scale=scale,
        warnings=warnings,
    )


def _downscale_to_limit(image_bytes: bytes, info: ImageInfo) -> tuple[bytes, float, list[str]]:
    Image, ImageOps = _require_pil()
    warnings = [
        "원본이 5MB를 넘어 축소한 뒤 분석했습니다. 축소로 작은 얼굴이 탐지되지 않았을 수 있습니다.",
    ]

    scale = 1.0
    # 원본 바이트를 여러 벌 들고 있지 않도록 매 시도마다 즉시 버린다 (t3.small, RAM 2GB).
    for _ in range(8):
        scale *= 0.75
        target_w = max(MIN_IMAGE_SIDE, int(info.width * scale))
        target_h = max(MIN_IMAGE_SIDE, int(info.height * scale))
        buffer = io.BytesIO()
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img.thumbnail((target_w, target_h), Image.LANCZOS)
            img.save(buffer, format="JPEG", quality=85, optimize=True)
        candidate = buffer.getvalue()
        del buffer
        if len(candidate) <= MAX_IMAGE_BYTES:
            return candidate, scale, warnings
        del candidate

    raise AnalysisError(
        "IMAGE_TOO_LARGE",
        "이미지가 너무 커서 분석 크기로 줄이지 못했습니다",
        retryable=False,
        details={"byte_size": info.byte_size, "limit": MAX_IMAGE_BYTES},
    )


# --------------------------------------------------------------------------
# 박스 대응 (IoU)
# --------------------------------------------------------------------------
def _box_tuple(box: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """Rekognition BoundingBox({Left,Top,Width,Height}) 또는 소문자 키를 받는다."""
    left = float(box.get("Left", box.get("left", 0.0)))
    top = float(box.get("Top", box.get("top", 0.0)))
    width = float(box.get("Width", box.get("width", 0.0)))
    height = float(box.get("Height", box.get("height", 0.0)))
    return left, top, width, height


def iou(box_a: Mapping[str, Any], box_b: Mapping[str, Any]) -> float:
    """정규화 좌표 박스 두 개의 IoU. 대응 실패 시 0.0."""
    ax, ay, aw, ah = _box_tuple(box_a)
    bx, by, bw, bh = _box_tuple(box_b)
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0

    inter_left = max(ax, bx)
    inter_top = max(ay, by)
    inter_right = min(ax + aw, bx + bw)
    inter_bottom = min(ay + ah, by + bh)
    if inter_right <= inter_left or inter_bottom <= inter_top:
        return 0.0

    inter = (inter_right - inter_left) * (inter_bottom - inter_top)
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return inter / union


def normalize_box(box: Mapping[str, Any]) -> dict[str, float]:
    """응답에 싣는 박스 형식(소문자 키, 0~1 정규화)."""
    left, top, width, height = _box_tuple(box)
    return {"left": left, "top": top, "width": width, "height": height}


# --------------------------------------------------------------------------
# 라벨 → 한글 태그
# --------------------------------------------------------------------------
# 매핑에 없는 라벨은 버린다. 이미지에서 특정 해변·식당 이름을 지어내지 않는다.
LABEL_TAG_MAP: dict[str, str] = {
    "selfie": "셀카",
    "portrait": "셀카",
    "indoors": "실내",
    "interior design": "실내",
    "room": "실내",
    "office": "회의",
    "meeting": "회의",
    "conference room": "회의",
    "classroom": "교실",
    "laptop": "노트북",
    "computer": "노트북",
    "electronics": "전자기기",
    "event": "행사",
    "convention": "행사",
    "outdoors": "야외",
    "nature": "자연",
    "landscape": "자연",
    "building": "건물",
    "architecture": "건물",
    "car": "자동차",
    "vehicle": "자동차",
    "animal": "동물",
    "pet": "반려동물",
    "dog": "반려동물",
    "cat": "반려동물",
    "sea": "바다",
    "ocean": "바다",
    "beach": "바다",
    "mountain": "산",
    "food": "음식",
    "meal": "음식",
    "dish": "음식",
    "beverage": "음료",
    "drink": "음료",
    "cafe": "카페",
    "coffee shop": "카페",
    "night": "야경",
    "sunset": "노을",
    "flower": "꽃",
    "forest": "숲",
    "city": "도시",
    "snow": "눈",
    "rain": "비",
}


def map_labels_to_tags(labels: Iterable[Mapping[str, Any]]) -> list[str]:
    """DetectLabels 결과를 한글 태그로 바꾼다. 지원 라벨만 남기고 중복을 없앤다."""
    tags: list[str] = []
    for label in labels or []:
        name = str(label.get("Name", "")).strip().lower()
        tag = LABEL_TAG_MAP.get(name)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


# --------------------------------------------------------------------------
# 품질 지표
# --------------------------------------------------------------------------
EYES_OPEN_MIN_CONFIDENCE = 90.0


def face_metrics(face_details: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """DetectFaces(Attributes=['ALL']) 결과에서 품질 3종을 계산한다. 추가 AI 호출 없음."""
    faces = list(face_details or [])
    if not faces:
        return {"sharpness": 0.0, "brightness": 0.0, "eyes_open_ratio": 0.0}

    sharpness_values: list[float] = []
    brightness_values: list[float] = []
    eyes_open = 0

    for face in faces:
        quality = face.get("Quality") or {}
        if "Sharpness" in quality and quality["Sharpness"] is not None:
            sharpness_values.append(float(quality["Sharpness"]))
        if "Brightness" in quality and quality["Brightness"] is not None:
            brightness_values.append(float(quality["Brightness"]))

        eyes = face.get("EyesOpen") or {}
        if bool(eyes.get("Value")) and float(eyes.get("Confidence", 0.0)) >= EYES_OPEN_MIN_CONFIDENCE:
            eyes_open += 1

    return {
        "sharpness": _mean(sharpness_values),
        "brightness": _mean(brightness_values),
        "eyes_open_ratio": round(eyes_open / len(faces), 4),
    }


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def compute_best_score(quality: Mapping[str, Any]) -> float:
    """연사 그룹 안에서의 *상대 비교용* 점수. 절대 품질 점수가 아니다.

    best_score = sharpness*0.5 + eyes_open_ratio*100*0.4 + min(brightness, 100)*0.1
    """
    sharpness = float(quality.get("sharpness", 0.0) or 0.0)
    brightness = float(quality.get("brightness", 0.0) or 0.0)
    eyes_open_ratio = float(quality.get("eyes_open_ratio", 0.0) or 0.0)
    score = sharpness * 0.5 + eyes_open_ratio * 100 * 0.4 + min(brightness, 100.0) * 0.1
    return round(score, 4)


def shot_type_for(face_count: int) -> str:
    """단체샷 자동 분리는 전부 이 한 줄에서 끝난다."""
    if face_count <= 0:
        return "no_face"
    if face_count == 1:
        return "solo"
    return "group"


# --------------------------------------------------------------------------
# 촬영 메타데이터 (EXIF)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CaptureMetadata:
    captured_at: str | None  # ISO 8601, EXIF 는 시간대 정보가 없어 naive 로 둔다
    captured_at_source: str | None  # 'exif:DateTimeOriginal' | 'exif:DateTime' | None
    gps: dict[str, float] | None
    place: None  # 외부 위치 조회 설정이 없으므로 항상 미제공
    place_reason: str
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "captured_at_source": self.captured_at_source,
            "gps": self.gps,
            "place": self.place,
            "place_reason": self.place_reason,
            "notes": list(self.notes),
        }


_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME = 306
_EXIF_GPS_IFD = 34853


def extract_capture_metadata(image_bytes: bytes) -> CaptureMetadata:
    """EXIF 에서 촬영 시각·GPS 를 읽는다. 없으면 없다고 한다. 추측하지 않는다."""
    notes: list[str] = []
    captured_at: str | None = None
    captured_at_source: str | None = None
    gps: dict[str, float] | None = None

    Image, _ = _require_pil()
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            exif = img.getexif()
    except Exception:
        return CaptureMetadata(
            captured_at=None,
            captured_at_source=None,
            gps=None,
            place=None,
            place_reason="REVERSE_GEOCODING_NOT_CONFIGURED",
            notes=["EXIF를 읽지 못했습니다"],
        )

    if not exif:
        notes.append("EXIF 정보 없음")
    else:
        raw_dt = None
        try:
            sub_ifd = exif.get_ifd(0x8769)
        except Exception:
            sub_ifd = {}
        if sub_ifd and sub_ifd.get(_EXIF_DATETIME_ORIGINAL):
            raw_dt = sub_ifd.get(_EXIF_DATETIME_ORIGINAL)
            captured_at_source = "exif:DateTimeOriginal"
        elif exif.get(_EXIF_DATETIME_ORIGINAL):
            raw_dt = exif.get(_EXIF_DATETIME_ORIGINAL)
            captured_at_source = "exif:DateTimeOriginal"
        elif exif.get(_EXIF_DATETIME):
            raw_dt = exif.get(_EXIF_DATETIME)
            captured_at_source = "exif:DateTime"

        captured_at = _parse_exif_datetime(raw_dt)
        if raw_dt and captured_at is None:
            captured_at_source = None
            notes.append("EXIF 촬영 시각 형식을 해석하지 못했습니다")
        if captured_at:
            notes.append("EXIF 촬영 시각에는 시간대 정보가 없습니다")
        else:
            notes.append("촬영 시각 없음")

        try:
            gps_ifd = exif.get_ifd(_EXIF_GPS_IFD)
        except Exception:
            gps_ifd = {}
        gps = _parse_gps(gps_ifd)
        if gps is None:
            notes.append("GPS 정보 없음")

    return CaptureMetadata(
        captured_at=captured_at,
        captured_at_source=captured_at_source,
        gps=gps,
        place=None,
        place_reason="REVERSE_GEOCODING_NOT_CONFIGURED",
        notes=notes,
    )


def _parse_exif_datetime(raw: Any) -> str | None:
    if not raw:
        return None
    text = str(raw).strip().rstrip("\x00")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return None


def _ratio(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(value[0]) / float(value[1])
        except Exception:
            return None


def _parse_gps(gps_ifd: Mapping[int, Any] | None) -> dict[str, float] | None:
    if not gps_ifd:
        return None
    lat = _dms_to_degrees(gps_ifd.get(2), gps_ifd.get(1))
    lon = _dms_to_degrees(gps_ifd.get(4), gps_ifd.get(3))
    if lat is None or lon is None:
        return None
    return {"lat": round(lat, 6), "lon": round(lon, 6)}


def _dms_to_degrees(dms: Any, ref: Any) -> float | None:
    if not dms:
        return None
    try:
        degrees, minutes, seconds = (_ratio(part) for part in dms)
    except Exception:
        return None
    if degrees is None or minutes is None or seconds is None:
        return None
    value = degrees + minutes / 60.0 + seconds / 3600.0
    if str(ref).strip().upper() in {"S", "W"}:
        value = -value
    return value

"""ZZIK 사진 분석 모듈 (역할 4 소유).

3번(백엔드)이 호출하는 공개 함수는 두 개다.

    validate_reference(image_bytes) -> {provider, mode, face_count}
    analyze(image_bytes, album_id, members) -> {...}

여기서 하지 않는 것:
  - DB 읽기/쓰기, S3 업로드, API 라우터, worker 트랜잭션 (전부 3번 몫)
  - 얼굴 임베딩 자체 구현 (Rekognition 이 한다)

환경변수:
  FACE_PROVIDER        rekognition | mock   (기본 mock)
  AWS_REGION           기본 us-east-1
  SIMILARITY_THRESHOLD 기본 90.0
  CANDIDATE_MARGIN     기본 5.0
  MOCK_MANIFEST_PATH   mock 정답 manifest 경로 (기본 backend/samples/mock_manifest.json)

자동 폴백은 없다. FACE_PROVIDER=rekognition 인데 AWS 인증이 실패하면
mock 성공으로 바꾸지 않고 AnalysisError 를 올린다.

Access Key 를 코드에 넣지 않는다. boto3 에는 region_name 만 주고
자격증명은 표준 체인(EC2 인스턴스 역할)에 맡긴다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .quality import (
    MAX_COMPARE_TARGET_FACES,
    AnalysisError,
    compute_best_score,
    extract_capture_metadata,
    face_metrics,
    inspect_image,
    iou,
    map_labels_to_tags,
    normalize_box,
    prepare_image,
    shot_type_for,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AnalysisError",
    "Settings",
    "load_settings",
    "validate_reference",
    "analyze",
    "PROVIDER_REKOGNITION",
    "PROVIDER_MOCK",
    "MODE_LIVE",
    "MODE_MOCK",
    "AUTH_MESSAGE_KO",
]

PROVIDER_REKOGNITION = "rekognition"
PROVIDER_MOCK = "mock"

# 사진 응답의 mode 값. 화면은 mode == 'mock' 일 때 "샘플 분석" 배지를 띄운다.
MODE_LIVE = "live"
MODE_MOCK = "mock"

# 인증·권한 오류는 원문을 노출하지 않고 이 문구로 통일한다.
AUTH_MESSAGE_KO = "AWS 분석 권한을 확인해 주세요"

# 매치 박스와 DetectFaces 박스를 대응시키는 최소 IoU
FACE_MATCH_MIN_IOU = 0.4

_DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "samples" / "mock_manifest.json"


# --------------------------------------------------------------------------
# 설정
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    provider: str
    region: str
    similarity_threshold: float
    candidate_margin: float
    manifest_path: Path
    mock_synthetic_match: bool

    @property
    def candidate_threshold(self) -> float:
        """CompareFaces 에 넘길 값. 후보를 넓게 받고 나중에 거른다."""
        return max(0.0, self.similarity_threshold - self.candidate_margin)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = env if env is not None else os.environ

    provider = (env.get("FACE_PROVIDER") or PROVIDER_MOCK).strip().lower()
    if provider not in {PROVIDER_REKOGNITION, PROVIDER_MOCK}:
        raise AnalysisError(
            "CONFIG_INVALID",
            "FACE_PROVIDER 설정이 올바르지 않습니다 (rekognition 또는 mock)",
            retryable=False,
            details={"face_provider": provider},
        )

    manifest = env.get("MOCK_MANIFEST_PATH")
    return Settings(
        provider=provider,
        region=(env.get("AWS_REGION") or "us-east-1").strip(),
        similarity_threshold=_float_env(env, "SIMILARITY_THRESHOLD", 90.0),
        candidate_margin=_float_env(env, "CANDIDATE_MARGIN", 5.0),
        manifest_path=Path(manifest) if manifest else _DEFAULT_MANIFEST,
        mock_synthetic_match=(env.get("MOCK_SYNTHETIC_MATCH", "1").strip().lower()
                              not in {"0", "false", "no"}),
    )


def _float_env(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise AnalysisError(
            "CONFIG_INVALID",
            f"{key} 설정이 숫자가 아닙니다",
            retryable=False,
            details={key: raw},
        ) from None


# --------------------------------------------------------------------------
# boto3 클라이언트 (테스트에서 이 함수를 monkeypatch 한다)
# --------------------------------------------------------------------------
def _rekognition_client(region: str):
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - 의존성 누락 환경
        raise AnalysisError(
            "DEPENDENCY_MISSING",
            "서버에 boto3 가 설치되어 있지 않습니다",
            retryable=False,
            details={"package": "boto3"},
        ) from exc
    # 자격증명은 표준 체인(EC2 인스턴스 역할)에 맡긴다. 키를 넣지 않는다.
    return boto3.client("rekognition", region_name=region)


# --------------------------------------------------------------------------
# AWS 예외 → AnalysisError
# --------------------------------------------------------------------------
_RETRYABLE_AWS_CODES = {
    "ThrottlingException",
    "Throttling",
    "ThrottledException",
    "TooManyRequestsException",
    "ProvisionedThroughputExceededException",
    "InternalServerError",
    "InternalError",
    "ServiceUnavailable",
    "ServiceUnavailableException",
    "RequestTimeout",
    "RequestTimeoutException",
}

_AUTH_AWS_CODES = {
    "AccessDenied",
    "AccessDeniedException",
    "UnrecognizedClientException",
    "InvalidClientTokenId",
    "InvalidSignatureException",
    "ExpiredToken",
    "ExpiredTokenException",
    "AuthFailure",
    "UnauthorizedOperation",
    "MissingAuthenticationToken",
}

_IMAGE_AWS_CODES = {
    "InvalidImageFormatException": ("INVALID_IMAGE", "이미지 형식을 인식하지 못했습니다"),
    "ImageTooLargeException": ("IMAGE_TOO_LARGE", "이미지가 분석 가능한 크기를 넘었습니다"),
    "InvalidParameterException": (
        "INVALID_PARAMETER",
        "이미지에서 비교할 얼굴을 찾지 못했습니다",
    ),
}

# 멤버 하나 때문에 사진 전체 분석을 실패시키지 않을 오류들
_MEMBER_SKIPPABLE_CODES = {"INVALID_PARAMETER", "INVALID_IMAGE", "IMAGE_TOO_LARGE", "IMAGE_TOO_SMALL"}


def _botocore_exceptions():
    try:
        import botocore.exceptions as be
    except ImportError:  # pragma: no cover
        return None
    return be


def _translate_aws_error(exc: BaseException, operation: str) -> AnalysisError:
    if isinstance(exc, AnalysisError):
        return exc

    be = _botocore_exceptions()
    if be is not None:
        auth_types = tuple(
            cls
            for cls in (
                getattr(be, "NoCredentialsError", None),
                getattr(be, "PartialCredentialsError", None),
                getattr(be, "CredentialRetrievalError", None),
                getattr(be, "MetadataRetrievalError", None),
            )
            if cls is not None
        )
        if auth_types and isinstance(exc, auth_types):
            logger.warning("Rekognition %s 인증 실패 (%s)", operation, type(exc).__name__)
            return AnalysisError(
                "AWS_AUTH",
                AUTH_MESSAGE_KO,
                retryable=False,
                details={"operation": operation},
            )

        conn_types = tuple(
            cls
            for cls in (
                getattr(be, "EndpointConnectionError", None),
                getattr(be, "ConnectTimeoutError", None),
                getattr(be, "ReadTimeoutError", None),
                getattr(be, "ConnectionClosedError", None),
                getattr(be, "ConnectionError", None),
            )
            if cls is not None
        )
        if conn_types and isinstance(exc, conn_types):
            logger.warning("Rekognition %s 연결 실패 (%s)", operation, type(exc).__name__)
            return AnalysisError(
                "AWS_UNAVAILABLE",
                "AWS 분석 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요",
                retryable=True,
                details={"operation": operation},
            )

        client_error = getattr(be, "ClientError", None)
        if client_error is not None and isinstance(exc, client_error):
            code = str((getattr(exc, "response", {}) or {}).get("Error", {}).get("Code", ""))
            if code in _AUTH_AWS_CODES:
                # 원문 메시지를 밖으로 내보내지 않는다.
                logger.warning("Rekognition %s 권한 오류 (code=%s)", operation, code)
                return AnalysisError(
                    "AWS_AUTH",
                    AUTH_MESSAGE_KO,
                    retryable=False,
                    details={"operation": operation},
                )
            if code in _RETRYABLE_AWS_CODES:
                logger.warning("Rekognition %s 일시 오류 (code=%s)", operation, code)
                return AnalysisError(
                    "AWS_THROTTLED" if "Throttl" in code or "TooMany" in code else "AWS_UNAVAILABLE",
                    "AWS 분석이 일시적으로 지연되고 있습니다. 다시 시도해 주세요",
                    retryable=True,
                    details={"operation": operation, "aws_code": code},
                )
            if code in _IMAGE_AWS_CODES:
                mapped_code, message = _IMAGE_AWS_CODES[code]
                return AnalysisError(
                    mapped_code,
                    message,
                    retryable=False,
                    details={"operation": operation, "aws_code": code},
                )
            logger.warning("Rekognition %s 오류 (code=%s)", operation, code)
            return AnalysisError(
                "ANALYSIS_FAILED",
                "사진 분석에 실패했습니다",
                retryable=False,
                details={"operation": operation, "aws_code": code},
            )

    if isinstance(exc, TimeoutError):
        return AnalysisError(
            "AWS_UNAVAILABLE",
            "AWS 분석 요청이 시간 초과되었습니다. 다시 시도해 주세요",
            retryable=True,
            details={"operation": operation},
        )

    logger.exception("Rekognition %s 예상치 못한 오류", operation)
    return AnalysisError(
        "ANALYSIS_FAILED",
        "사진 분석에 실패했습니다",
        retryable=False,
        details={"operation": operation},
    )


def _call(client, operation: str, method: str, **kwargs) -> dict[str, Any]:
    try:
        return getattr(client, method)(**kwargs)
    except Exception as exc:  # noqa: BLE001 - 전부 AnalysisError 로 정규화한다
        raise _translate_aws_error(exc, operation) from exc


# --------------------------------------------------------------------------
# 공개 함수 1: 기준 인물(셀카) 검증
# --------------------------------------------------------------------------
def validate_reference(image_bytes: bytes, *, settings: Settings | None = None) -> dict[str, Any]:
    """셀카 1장이 기준 얼굴로 쓸 수 있는지 확인한다.

    얼굴 0개 -> AnalysisError('NO_FACE')
    얼굴 2개 이상 -> AnalysisError('MULTIPLE_FACES')   (서로 다른 코드다)
    """
    settings = settings or load_settings()
    started = time.perf_counter()

    if settings.provider == PROVIDER_MOCK:
        face_count, _entry = _mock_reference_face_count(image_bytes, settings)
        provider, mode = PROVIDER_MOCK, MODE_MOCK
    else:
        prepared = prepare_image(image_bytes)
        client = _rekognition_client(settings.region)
        response = _call(
            client,
            "DetectFaces",
            "detect_faces",
            Image={"Bytes": prepared.data},
            Attributes=["DEFAULT"],
        )
        face_count = len(response.get("FaceDetails") or [])
        provider, mode = PROVIDER_REKOGNITION, MODE_LIVE

    if face_count == 0:
        raise AnalysisError(
            "NO_FACE",
            "사진에서 얼굴을 찾지 못했습니다. 얼굴이 잘 보이는 셀카로 다시 시도해 주세요",
            retryable=False,
            details={"provider": provider, "mode": mode, "face_count": 0},
        )
    if face_count > 1:
        raise AnalysisError(
            "MULTIPLE_FACES",
            "사진에 얼굴이 여러 개입니다. 본인 얼굴만 나온 사진으로 다시 시도해 주세요",
            retryable=False,
            details={"provider": provider, "mode": mode, "face_count": face_count},
        )

    return {
        "provider": provider,
        "mode": mode,
        "face_count": face_count,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


# --------------------------------------------------------------------------
# 공개 함수 2: 사진 분석
# --------------------------------------------------------------------------
def analyze(
    image_bytes: bytes,
    album_id: str,
    members: Sequence[Mapping[str, Any]] | None = None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """사진 1장을 분석한다.

    members 각 항목:
        {"id": "<member uuid>", ...}  + 기준 얼굴 위치를 아래 중 하나로 준다
          - "reference_bytes": bytes
          - "reference_s3": {"bucket": ..., "key": ...}
          - "reference_bucket" + "reference_key"
        기준 얼굴이 없거나 위치를 알 수 없는 멤버는 건너뛰고 skipped_members 에 기록한다.

    반환 dict 는 계약대로 faces / face_count / shot_type / tags / quality /
    best_score / provider / mode / calls / elapsed_ms 를 포함한다.
    """
    settings = settings or load_settings()
    members = list(members or [])

    if settings.provider == PROVIDER_MOCK:
        return _analyze_mock(image_bytes, album_id, members, settings)
    return _analyze_rekognition(image_bytes, album_id, members, settings)


def _analyze_rekognition(
    image_bytes: bytes,
    album_id: str,
    members: list[Mapping[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    started = time.perf_counter()
    warnings: list[str] = []
    calls = {"detect_faces": 0, "compare_faces": 0, "detect_labels": 0}

    prepared = prepare_image(image_bytes)
    warnings.extend(prepared.warnings)
    client = _rekognition_client(settings.region)

    # 1) DetectFaces 를 먼저 부른다.
    detect = _call(
        client,
        "DetectFaces",
        "detect_faces",
        Image={"Bytes": prepared.data},
        Attributes=["ALL"],
    )
    calls["detect_faces"] += 1
    face_details = list(detect.get("FaceDetails") or [])
    face_count = len(face_details)

    if face_count > MAX_COMPARE_TARGET_FACES:
        warnings.append(
            f"얼굴이 {face_count}개로 CompareFaces 비교 한도({MAX_COMPARE_TARGET_FACES}개)를 넘습니다. "
            "일부 얼굴은 인물 매칭에서 빠질 수 있습니다."
        )

    # 2) 얼굴이 있을 때만 CompareFaces. 얼굴 0개 이미지에서는 부르지 않는다.
    candidates: dict[int, list[tuple[float, str]]] = {}
    skipped_members: list[dict[str, str]] = []

    if face_count > 0:
        for member in members:
            member_id = str(member.get("id") or "").strip()
            if not member_id:
                continue
            source_image, skip_reason = _member_source_image(member)
            if source_image is None:
                skipped_members.append({"member_id": member_id, "reason": skip_reason or "NO_REFERENCE"})
                continue
            calls["compare_faces"] += 1
            try:
                compare = _call(
                    client,
                    "CompareFaces",
                    "compare_faces",
                    SourceImage=source_image,
                    TargetImage={"Bytes": prepared.data},
                    SimilarityThreshold=settings.candidate_threshold,
                    QualityFilter="AUTO",
                )
            except AnalysisError as exc:
                if exc.code in _MEMBER_SKIPPABLE_CODES:
                    # 기준 셀카에 얼굴이 없는 등 그 멤버만의 문제. 사진 전체는 계속 분석한다.
                    skipped_members.append({"member_id": member_id, "reason": exc.code})
                    continue
                raise

            for match in compare.get("FaceMatches") or []:
                similarity = float(match.get("Similarity") or 0.0)
                match_box = (match.get("Face") or {}).get("BoundingBox") or {}
                face_index = _best_iou_face(match_box, face_details)
                if face_index is None:
                    continue
                candidates.setdefault(face_index, []).append((similarity, member_id))

    faces, matched_member_ids = _resolve_faces(face_details, candidates, settings)

    # 3) DetectLabels — 장면 태그
    labels = _call(
        client,
        "DetectLabels",
        "detect_labels",
        Image={"Bytes": prepared.data},
        MaxLabels=30,
        MinConfidence=80,
    )
    calls["detect_labels"] += 1
    tags = map_labels_to_tags(labels.get("Labels") or [])

    quality = face_metrics(face_details)
    capture = extract_capture_metadata(image_bytes)

    return {
        "faces": faces,
        "face_count": face_count,
        "shot_type": shot_type_for(face_count),
        "tags": tags,
        "quality": quality,
        "best_score": compute_best_score(quality),
        "provider": PROVIDER_REKOGNITION,
        "mode": MODE_LIVE,
        "calls": {**calls, "total": sum(calls.values())},
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        # 계약 밖 부가 정보 (3번이 저장 여부를 결정한다)
        "matched_member_ids": matched_member_ids,
        "skipped_members": skipped_members,
        "warnings": warnings,
        "image": {
            "mime": prepared.original.mime,
            "width": prepared.original.width,
            "height": prepared.original.height,
            "byte_size": prepared.original.byte_size,
            "content_hash": prepared.original.content_hash,
            "downscaled_for_analysis": prepared.downscaled,
        },
        "capture": capture.to_dict(),
    }


def _member_source_image(member: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """CompareFaces 의 SourceImage 를 만든다. 만들 수 없으면 (None, 사유)."""
    raw = member.get("reference_bytes")
    if raw:
        try:
            prepared = prepare_image(raw)
        except AnalysisError as exc:
            return None, exc.code
        return {"Bytes": prepared.data}, None

    s3 = member.get("reference_s3") or {}
    bucket = member.get("reference_bucket") or s3.get("bucket") or os.environ.get("S3_BUCKET")
    key = member.get("reference_key") or s3.get("key")
    if bucket and key:
        return {"S3Object": {"Bucket": str(bucket), "Name": str(key)}}, None

    if key and not bucket:
        return None, "NO_REFERENCE_BUCKET"
    return None, "NO_REFERENCE"


def _best_iou_face(match_box: Mapping[str, Any], face_details: Sequence[Mapping[str, Any]]) -> int | None:
    """CompareFaces 매치 박스를 DetectFaces 얼굴에 IoU >= 0.4 로 대응시킨다."""
    best_index: int | None = None
    best_score = 0.0
    for index, face in enumerate(face_details):
        score = iou(match_box, face.get("BoundingBox") or {})
        if score > best_score:
            best_score = score
            best_index = index
    if best_index is None or best_score < FACE_MATCH_MIN_IOU:
        return None
    return best_index


def _resolve_faces(
    face_details: Sequence[Mapping[str, Any]],
    candidates: Mapping[int, list[tuple[float, str]]],
    settings: Settings,
) -> tuple[list[dict[str, Any]], list[str]]:
    """확정 / 불확실 / 미등록을 구분한다. 억지로 배정하지 않는다.

    확정 조건: 1위 similarity >= THRESHOLD 이고, 2위가 있으면 (1위 - 2위) >= MARGIN.
    그리고 같은 member_id 가 두 얼굴에 붙지 않도록 similarity 높은 쪽부터 그리디 배정한다.
    """
    sorted_candidates: dict[int, list[tuple[float, str]]] = {}
    for index, rows in candidates.items():
        # 같은 멤버가 여러 매치로 들어오면 최고 similarity 하나만 남긴다.
        best_per_member: dict[str, float] = {}
        for similarity, member_id in rows:
            if similarity > best_per_member.get(member_id, -1.0):
                best_per_member[member_id] = similarity
        sorted_candidates[index] = sorted(
            ((sim, mid) for mid, sim in best_per_member.items()),
            key=lambda row: (-row[0], row[1]),
        )

    proposals: list[tuple[float, int, str]] = []
    for index, rows in sorted_candidates.items():
        if not rows:
            continue
        top_sim, top_member = rows[0]
        if top_sim < settings.similarity_threshold:
            continue
        if len(rows) > 1 and (top_sim - rows[1][0]) < settings.candidate_margin:
            continue  # 1·2위가 붙어 있으면 사람 판단에 맡긴다
        proposals.append((top_sim, index, top_member))

    proposals.sort(key=lambda row: (-row[0], row[1]))
    assigned: dict[int, tuple[str, float]] = {}
    used_members: set[str] = set()
    for similarity, index, member_id in proposals:
        if index in assigned or member_id in used_members:
            continue
        assigned[index] = (member_id, similarity)
        used_members.add(member_id)

    faces: list[dict[str, Any]] = []
    for index, detail in enumerate(face_details):
        rows = sorted_candidates.get(index, [])
        entry: dict[str, Any] = {
            "box": normalize_box(detail.get("BoundingBox") or {}),
            "member_id": None,
            "similarity": None,
            "uncertain": False,
            "detection_confidence": round(float(detail.get("Confidence") or 0.0), 4),
        }
        if index in assigned:
            member_id, similarity = assigned[index]
            entry["member_id"] = member_id
            entry["similarity"] = round(similarity, 4)
            entry["status"] = "matched"
        elif rows:
            entry["uncertain"] = True
            entry["status"] = "uncertain"
            entry["candidates"] = [
                {"member_id": mid, "similarity": round(sim, 4)} for sim, mid in rows[:3]
            ]
        else:
            # 등록된 기준 인물 중 누구와도 후보조차 안 걸린 얼굴 = 미등록 인물
            entry["status"] = "unregistered"
        faces.append(entry)

    return faces, sorted(used_members)


# --------------------------------------------------------------------------
# mock 제공자
# --------------------------------------------------------------------------
# mock 은 AWS 를 전혀 부르지 않고 파일 해시를 시드로 결정론적 결과를 만든다.
# 반환 dict 의 mode 는 항상 'mock' 이라 화면에서 "샘플 분석" 으로 구분된다.
#
# mock_source:
#   'manifest'  - samples/mock_manifest.json 에 등록된 샘플. 사람이 적어 넣은 정답이다.
#   'synthetic' - 등록되지 않은 사진. 해시로 만든 가짜값이며 실제 인물 매칭이 아니다.
#                 얼굴마다 synthetic=True 가 붙는다.
_MOCK_TAG_POOL = ["바다", "산", "음식", "카페", "야경", "노을", "꽃", "숲", "도시"]
_MOCK_SYNTHETIC_WARNING = "mock 모드 합성 결과입니다. 실제 얼굴 인식·인물 매칭이 아닙니다."


def _load_manifest(settings: Settings) -> dict[str, Any]:
    path = settings.manifest_path
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(
            "MOCK_MANIFEST_INVALID",
            "mock 샘플 manifest 를 읽지 못했습니다",
            retryable=False,
            details={"path": str(path)},
        ) from exc
    entries = data.get("samples") or {}
    return entries if isinstance(entries, dict) else {}


def _mock_entry(image_bytes: bytes, settings: Settings) -> tuple[str, dict[str, Any] | None]:
    content_hash = hashlib.sha256(image_bytes).hexdigest()
    entry = _load_manifest(settings).get(content_hash)
    return content_hash, entry if isinstance(entry, dict) else None


def _mock_reference_face_count(image_bytes: bytes, settings: Settings) -> tuple[int, dict | None]:
    _hash, entry = _mock_entry(image_bytes, settings)
    if entry is not None and "reference_face_count" in entry:
        return int(entry["reference_face_count"]), entry
    if entry is not None and "face_count" in entry:
        return int(entry["face_count"]), entry
    # 등록되지 않은 셀카는 mock 에서 얼굴 1개로 본다(실제 탐지 결과가 아니다).
    return 1, entry


def _analyze_mock(
    image_bytes: bytes,
    album_id: str,
    members: list[Mapping[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    started = time.perf_counter()
    content_hash, entry = _mock_entry(image_bytes, settings)
    rng = random.Random(int(content_hash[:16], 16))

    # 이미지 자체는 실제로 읽는다(형식·크기 검증은 mock 에서도 진짜로 한다).
    info = inspect_image(image_bytes)
    capture = extract_capture_metadata(image_bytes)

    member_ids = [str(m.get("id")) for m in members if m.get("id")]
    warnings: list[str] = []

    if entry is not None:
        mock_source = "manifest"
        face_count = int(entry.get("face_count", 0))
        tags = list(entry.get("tags") or [])
        quality = dict(entry.get("quality") or _mock_quality(rng, face_count))
        slots = list(entry.get("member_slots") or [])
        assigned = [member_ids[i] if 0 <= i < len(member_ids) else None for i in slots]
        assigned += [None] * max(0, face_count - len(assigned))
        synthetic = False
    else:
        mock_source = "synthetic"
        synthetic = True
        face_count = rng.choice([0, 1, 1, 2, 2, 3])
        tags = rng.sample(_MOCK_TAG_POOL, k=rng.choice([0, 1, 2]))
        quality = _mock_quality(rng, face_count)
        if settings.mock_synthetic_match and member_ids:
            pool = list(member_ids)
            rng.shuffle(pool)
            assigned = [pool[i] if i < len(pool) else None for i in range(face_count)]
        else:
            assigned = [None] * face_count
        warnings.append(_MOCK_SYNTHETIC_WARNING)

    faces: list[dict[str, Any]] = []
    matched: list[str] = []
    for index in range(face_count):
        member_id = assigned[index] if index < len(assigned) else None
        face: dict[str, Any] = {
            "box": _mock_box(rng),
            "member_id": member_id,
            "similarity": round(rng.uniform(91.0, 99.0), 4) if member_id else None,
            "uncertain": False,
            "detection_confidence": round(rng.uniform(95.0, 99.9), 4),
            "status": "matched" if member_id else "unregistered",
        }
        if synthetic:
            face["synthetic"] = True
        if member_id:
            matched.append(member_id)
        faces.append(face)

    return {
        "faces": faces,
        "face_count": face_count,
        "shot_type": shot_type_for(face_count),
        "tags": tags,
        "quality": quality,
        "best_score": compute_best_score(quality),
        "provider": PROVIDER_MOCK,
        "mode": MODE_MOCK,
        "calls": {"detect_faces": 0, "compare_faces": 0, "detect_labels": 0, "total": 0},
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "matched_member_ids": sorted(set(matched)),
        "skipped_members": [],
        "warnings": warnings,
        "mock_source": mock_source,
        "image": {
            "mime": info.mime,
            "width": info.width,
            "height": info.height,
            "byte_size": info.byte_size,
            "content_hash": info.content_hash,
            "downscaled_for_analysis": False,
        },
        "capture": capture.to_dict(),
    }


def _mock_quality(rng: random.Random, face_count: int) -> dict[str, float]:
    # 실제 제공자와 같은 규칙: 품질 지표는 얼굴에서만 나온다. 얼굴이 없으면 0이다.
    if face_count == 0:
        return {"sharpness": 0.0, "brightness": 0.0, "eyes_open_ratio": 0.0}
    opened = sum(1 for _ in range(face_count) if rng.random() > 0.25)
    return {
        "sharpness": round(rng.uniform(20.0, 95.0), 4),
        "brightness": round(rng.uniform(30.0, 90.0), 4),
        "eyes_open_ratio": round(opened / face_count, 4),
    }


def _mock_box(rng: random.Random) -> dict[str, float]:
    width = round(rng.uniform(0.08, 0.25), 4)
    height = round(rng.uniform(0.08, 0.25), 4)
    return {
        "left": round(rng.uniform(0.0, 1.0 - width), 4),
        "top": round(rng.uniform(0.0, 1.0 - height), 4),
        "width": width,
        "height": height,
    }

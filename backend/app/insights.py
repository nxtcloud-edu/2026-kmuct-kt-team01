"""ZZIK 여행 요약 (역할 4 소유, T3 부가 기능).

앨범의 집계 사실만 모아 Bedrock 위의 Claude 를 **1회** 호출해 3줄 요약을 받는다.
대표 사진 5장은 LLM 이 아니라 여기 파이썬 코드가 고른다(검증 가능해야 하므로).

analysis.py / quality.py 와 분리한 이유: 분석 경로(worker 의 사진 1장당 핫패스)에
Bedrock 클라이언트와 프롬프트를 섞지 않기 위해서다. 소유는 역할 4다.

여기서 하지 않는 것: DB 접근, API 라우터. 3번이 집계해서 넘겨주고 결과를 저장한다.

환경변수:
  SUMMARY_PROVIDER   bedrock | mock | off   (기본 mock, 자동 폴백 없음)
  AWS_REGION         기본 us-east-1
  BEDROCK_MODEL_ID   기본 anthropic.claude-opus-5
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .quality import AnalysisError

logger = logging.getLogger(__name__)

__all__ = [
    "SummarySettings",
    "load_summary_settings",
    "summarize_album",
    "select_highlights",
    "build_facts",
]

PROVIDER_BEDROCK = "bedrock"
PROVIDER_MOCK = "mock"
PROVIDER_OFF = "off"

MODE_LIVE = "live"
MODE_MOCK = "mock"
MODE_OFF = "off"

DEFAULT_MODEL_ID = "anthropic.claude-opus-5"
AUTH_MESSAGE_KO = "AWS 분석 권한을 확인해 주세요"

HIGHLIGHT_COUNT = 5
MAX_SUMMARY_LINES = 3
MAX_LINE_CHARS = 60

# 모델에게 주는 지시. 제공된 집계 사실 밖으로 나가지 못하게 못을 박는다.
_SYSTEM_PROMPT = """너는 여행 공유 앨범의 사진 통계를 한국어 3줄로 요약한다.

지켜야 할 규칙:
- 아래 JSON 으로 주어진 사실만 쓴다. 주어지지 않은 것은 쓰지 않는다.
- 특정 해변·식당·카페·도시의 고유 이름을 지어내지 않는다. 태그에 있는 단어만 쓴다.
- 사람 이름은 주어진 멤버 이름만 쓴다.
- 사진 장수·날짜는 주어진 숫자를 그대로 쓴다. 계산하거나 추정하지 않는다.
- 각 줄은 한 문장, 60자 이내. 과장하지 말고 담백하게 쓴다.
- 사실이 부족하면 부족한 대로 짧게 쓴다. 채워 넣지 않는다."""


@dataclass(frozen=True)
class SummarySettings:
    provider: str
    region: str
    model_id: str


def load_summary_settings(env: Mapping[str, str] | None = None) -> SummarySettings:
    env = env if env is not None else os.environ
    provider = (env.get("SUMMARY_PROVIDER") or PROVIDER_MOCK).strip().lower()
    if provider not in {PROVIDER_BEDROCK, PROVIDER_MOCK, PROVIDER_OFF}:
        raise AnalysisError(
            "CONFIG_INVALID",
            "SUMMARY_PROVIDER 설정이 올바르지 않습니다 (bedrock, mock, off)",
            retryable=False,
            details={"summary_provider": provider},
        )
    return SummarySettings(
        provider=provider,
        region=(env.get("AWS_REGION") or "us-east-1").strip(),
        model_id=(env.get("BEDROCK_MODEL_ID") or DEFAULT_MODEL_ID).strip(),
    )


# --------------------------------------------------------------------------
# 대표 사진 고르기 — LLM 을 쓰지 않는다
# --------------------------------------------------------------------------
def select_highlights(
    photos: Sequence[Mapping[str, Any]],
    count: int = HIGHLIGHT_COUNT,
) -> list[dict[str, Any]]:
    """대표 사진을 규칙으로 고른다. 이유를 같이 돌려주어 사람이 검증할 수 있게 한다.

    규칙(순서대로):
      1. 분석이 끝나고(best_score 있음) 연사에서 탈락하지 않은(is_best != False) 사진만 후보
      2. 아직 안 나온 태그를 가진 사진을 우선 (장면 다양성)
      3. 같은 조건이면 best_score 높은 순
    best_score 는 연사 그룹 안의 상대 비교용 점수다. 절대 품질이 아니다.
    """
    candidates = [
        p
        for p in photos or []
        if p.get("best_score") is not None and p.get("is_best", True) is not False
    ]
    candidates.sort(key=lambda p: (-float(p.get("best_score") or 0.0), str(p.get("id"))))

    chosen: list[dict[str, Any]] = []
    seen_tags: set[str] = set()
    seen_shot_types: set[str] = set()

    remaining = list(candidates)
    while remaining and len(chosen) < count:
        pick = None
        for photo in remaining:
            tags = set(photo.get("tags") or [])
            shot_type = str(photo.get("shot_type") or "unknown")
            if (tags - seen_tags) or (shot_type not in seen_shot_types):
                pick = photo
                break
        if pick is None:
            pick = remaining[0]

        tags = set(pick.get("tags") or [])
        shot_type = str(pick.get("shot_type") or "unknown")
        reasons = []
        if tags - seen_tags:
            reasons.append("새 장면 태그: " + ", ".join(sorted(tags - seen_tags)))
        if shot_type not in seen_shot_types:
            reasons.append(f"샷 종류: {shot_type}")
        reasons.append(f"상대 점수 {float(pick.get('best_score') or 0.0):.1f}")

        seen_tags |= tags
        seen_shot_types.add(shot_type)
        chosen.append({"photo_id": str(pick.get("id")), "reason": " / ".join(reasons)})
        remaining.remove(pick)

    return chosen


# --------------------------------------------------------------------------
# 모델에 넘길 사실만 추리기
# --------------------------------------------------------------------------
def build_facts(album: Mapping[str, Any]) -> dict[str, Any]:
    """모델에 넘길 집계 사실. 사진 자체나 개별 파일명은 넘기지 않는다."""
    photos = list(album.get("photos") or [])

    tag_counts: dict[str, int] = dict(album.get("tag_counts") or {})
    shot_type_counts: dict[str, int] = dict(album.get("shot_type_counts") or {})
    if not tag_counts or not shot_type_counts:
        for photo in photos:
            for tag in photo.get("tags") or []:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            shot = str(photo.get("shot_type") or "unknown")
            shot_type_counts[shot] = shot_type_counts.get(shot, 0) + 1

    captured = sorted(str(p["captured_at"]) for p in photos if p.get("captured_at"))
    date_range = dict(album.get("date_range") or {})
    if not date_range:
        date_range = {
            "start": captured[0] if captured else None,
            "end": captured[-1] if captured else None,
        }
    if date_range.get("start") is None:
        # 촬영 시각이 없는 앨범이다. 날짜를 지어내지 않는다.
        date_range = {"start": None, "end": None, "note": "촬영 시각 정보 없음"}

    return {
        "album_name": album.get("name"),
        "photo_count": int(album.get("photo_count") or len(photos)),
        "member_names": [str(n) for n in (album.get("member_names") or [])],
        "tag_counts": tag_counts,
        "shot_type_counts": shot_type_counts,
        "date_range": date_range,
    }


# --------------------------------------------------------------------------
# 공개 함수
# --------------------------------------------------------------------------
def summarize_album(
    album: Mapping[str, Any],
    *,
    settings: SummarySettings | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """앨범 1개를 3줄로 요약하고 대표 사진을 고른다. Bedrock 호출은 최대 1회다.

    반환:
      {summary_lines, highlights, provider, mode, model_id, calls, elapsed_ms,
       usage, facts, warnings}

    summary_lines 는 **모델이 쓴 문장**이다. 사실 검증을 거친 문장이 아니므로
    화면에 "AI 요약"으로 표시한다.
    """
    settings = settings or load_summary_settings()
    started = time.perf_counter()
    facts = build_facts(album)
    highlights = select_highlights(album.get("photos") or [])

    base = {
        "highlights": highlights,
        "facts": facts,
        "model_id": None,
        "usage": None,
        "warnings": [],
    }

    if settings.provider == PROVIDER_OFF:
        return {
            **base,
            "summary_lines": [],
            "provider": PROVIDER_OFF,
            "mode": MODE_OFF,
            "calls": {"bedrock_invoke": 0},
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "warnings": ["SUMMARY_PROVIDER=off 이므로 요약을 생성하지 않았습니다."],
        }

    if settings.provider == PROVIDER_MOCK:
        return {
            **base,
            "summary_lines": _mock_summary_lines(facts),
            "provider": PROVIDER_MOCK,
            "mode": MODE_MOCK,
            "calls": {"bedrock_invoke": 0},
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "warnings": [
                "샘플 요약입니다. 모델을 호출하지 않고 집계 숫자로 문장을 만들었습니다.",
            ],
        }

    lines, usage = _bedrock_summary_lines(facts, settings, client)
    return {
        **base,
        "summary_lines": lines,
        "provider": PROVIDER_BEDROCK,
        "mode": MODE_LIVE,
        "model_id": settings.model_id,
        "calls": {"bedrock_invoke": 1},
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "usage": usage,
    }


def _mock_summary_lines(facts: Mapping[str, Any]) -> list[str]:
    """모델 없이 집계 숫자만으로 만든 문장. 지어낸 내용이 없다."""
    photo_count = facts.get("photo_count") or 0
    members = facts.get("member_names") or []
    tags = sorted(
        (facts.get("tag_counts") or {}).items(), key=lambda kv: (-kv[1], kv[0])
    )
    shot_counts = facts.get("shot_type_counts") or {}

    lines = [f"사진 {photo_count}장을 모았습니다."]
    if members:
        lines[0] = f"{len(members)}명이 사진 {photo_count}장을 모았습니다."
    if tags:
        top = ", ".join(name for name, _ in tags[:3])
        lines.append(f"가장 많이 찍힌 장면은 {top}입니다.")
    else:
        lines.append("장면 태그가 붙은 사진은 아직 없습니다.")
    group = int(shot_counts.get("group") or 0)
    solo = int(shot_counts.get("solo") or 0)
    lines.append(f"단체샷 {group}장, 혼자 나온 사진 {solo}장입니다.")
    return lines[:MAX_SUMMARY_LINES]


# --------------------------------------------------------------------------
# Bedrock 호출
# --------------------------------------------------------------------------
_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_lines": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": MAX_SUMMARY_LINES,
            "maxItems": MAX_SUMMARY_LINES,
        }
    },
    "required": ["summary_lines"],
    "additionalProperties": False,
}


def _bedrock_client(settings: SummarySettings):
    try:
        from anthropic import AnthropicBedrockMantle
    except ImportError as exc:
        raise AnalysisError(
            "DEPENDENCY_MISSING",
            "서버에 anthropic SDK 가 설치되어 있지 않습니다",
            retryable=False,
            details={"package": "anthropic[bedrock]"},
        ) from exc
    # 자격증명은 표준 AWS 체인(EC2 인스턴스 역할). 키를 넣지 않는다.
    return AnthropicBedrockMantle(aws_region=settings.region)


def _bedrock_summary_lines(
    facts: Mapping[str, Any],
    settings: SummarySettings,
    client: Any | None,
) -> tuple[list[str], dict[str, Any] | None]:
    client = client or _bedrock_client(settings)
    payload = json.dumps(facts, ensure_ascii=False, sort_keys=True)

    try:
        response = client.messages.create(
            model=settings.model_id,
            max_tokens=4000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": _SUMMARY_SCHEMA},
            },
        )
    except Exception as exc:  # noqa: BLE001 - 전부 AnalysisError 로 정규화
        raise _translate_summary_error(exc) from exc

    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason == "refusal":
        raise AnalysisError(
            "SUMMARY_REFUSED",
            "요약 생성이 거절되었습니다",
            retryable=False,
            details={"stop_reason": stop_reason},
        )
    if stop_reason == "max_tokens":
        raise AnalysisError(
            "SUMMARY_TRUNCATED",
            "요약이 중간에 잘렸습니다. 다시 시도해 주세요",
            retryable=True,
            details={"stop_reason": stop_reason},
        )

    text = next(
        (block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"),
        None,
    )
    if not text:
        raise AnalysisError("SUMMARY_EMPTY", "요약 결과가 비어 있습니다", retryable=True)

    try:
        data = json.loads(text)
        raw_lines = list(data["summary_lines"])
    except (ValueError, KeyError, TypeError) as exc:
        raise AnalysisError(
            "SUMMARY_INVALID",
            "요약 결과 형식이 올바르지 않습니다",
            retryable=True,
        ) from exc

    lines = [str(line).strip()[:MAX_LINE_CHARS] for line in raw_lines if str(line).strip()]
    if not lines:
        raise AnalysisError("SUMMARY_EMPTY", "요약 결과가 비어 있습니다", retryable=True)

    usage = getattr(response, "usage", None)
    usage_dict = (
        {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
        if usage is not None
        else None
    )
    return lines[:MAX_SUMMARY_LINES], usage_dict


def _translate_summary_error(exc: BaseException) -> AnalysisError:
    if isinstance(exc, AnalysisError):
        return exc

    try:
        import anthropic
    except ImportError:  # pragma: no cover - 위에서 이미 걸린다
        anthropic = None

    if anthropic is not None:
        # 좁은 것부터 넓은 것 순서로 본다.
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            logger.warning("Bedrock 요약 권한 오류 (%s)", type(exc).__name__)
            return AnalysisError("AWS_AUTH", AUTH_MESSAGE_KO, retryable=False)
        if isinstance(exc, anthropic.NotFoundError):
            logger.warning("Bedrock 요약 모델을 찾지 못함 (%s)", type(exc).__name__)
            return AnalysisError(
                "SUMMARY_MODEL_UNAVAILABLE",
                "요약 모델을 사용할 수 없습니다. BEDROCK_MODEL_ID 와 모델 접근 권한을 확인해 주세요",
                retryable=False,
            )
        if isinstance(exc, anthropic.RateLimitError):
            return AnalysisError(
                "SUMMARY_THROTTLED",
                "요약 요청이 일시적으로 지연되고 있습니다. 다시 시도해 주세요",
                retryable=True,
            )
        if isinstance(exc, anthropic.APIStatusError):
            status = getattr(exc, "status_code", 0) or 0
            return AnalysisError(
                "SUMMARY_FAILED",
                "여행 요약 생성에 실패했습니다",
                retryable=status >= 500,
                details={"status_code": status},
            )
        if isinstance(exc, anthropic.APIConnectionError):
            return AnalysisError(
                "SUMMARY_UNAVAILABLE",
                "요약 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요",
                retryable=True,
            )

    try:
        import botocore.exceptions as be

        credential_errors = tuple(
            cls
            for cls in (
                getattr(be, "NoCredentialsError", None),
                getattr(be, "PartialCredentialsError", None),
            )
            if cls is not None
        )
        if credential_errors and isinstance(exc, credential_errors):
            logger.warning("Bedrock 요약 자격증명 없음 (%s)", type(exc).__name__)
            return AnalysisError("AWS_AUTH", AUTH_MESSAGE_KO, retryable=False)
    except ImportError:  # pragma: no cover
        pass

    logger.exception("Bedrock 요약 예상치 못한 오류")
    return AnalysisError("SUMMARY_FAILED", "여행 요약 생성에 실패했습니다", retryable=False)

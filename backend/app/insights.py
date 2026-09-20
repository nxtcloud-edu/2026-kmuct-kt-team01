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
    "parse_search_query",
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


# --------------------------------------------------------------------------
# 자연어 검색 구조화 (T3 8-b)
# --------------------------------------------------------------------------
# "바다에서 찍은 단체샷" -> {"tags": ["바다"], "shot_type": "group"}
# **검색 자체는 하지 않는다.** 구조화된 필터만 돌려주고 SQL 은 3번이 짠다.
# 임베딩·벡터 인프라를 만들지 않는다.

SHOT_TYPES = ("any", "solo", "group", "no_face")

# quality.LABEL_TAG_MAP 이 만들어 내는 한글 태그 9종. 이 밖의 태그는 만들지 않는다.
SEARCH_TAGS = ("바다", "산", "음식", "카페", "야경", "노을", "꽃", "숲", "도시")

# mock(규칙) 파서용 한국어 단서. 모델 없이도 데모가 돌아가게 한다.
_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "바다": ("바다", "해변", "해수욕장", "오션", "파도"),
    "산": ("산", "등산", "산속", "정상"),
    "음식": ("음식", "먹", "밥", "맛집", "요리"),
    "카페": ("카페", "커피"),
    "야경": ("야경", "밤", "야간"),
    "노을": ("노을", "석양", "일몰"),
    "꽃": ("꽃", "벚꽃", "꽃밭"),
    "숲": ("숲", "수목원", "나무"),
    "도시": ("도시", "시내", "빌딩", "거리"),
}
_GROUP_KEYWORDS = ("단체", "다같이", "다 같이", "함께", "여럿", "모두", "전부", "우리")
_SOLO_KEYWORDS = ("혼자", "솔로", "독사진", "단독", "셀카")
_NO_FACE_KEYWORDS = ("사람 없", "사람없", "풍경만", "인물 없", "인물없")
_BEST_KEYWORDS = ("베스트", "잘 나온", "잘나온", "제일 좋", "가장 좋", "대표")

_SEARCH_SYSTEM_PROMPT = """너는 사진 검색어를 구조화된 필터로 바꾼다. 검색을 직접 하지 않는다.

출력 규칙:
- tags 는 주어진 목록에 있는 값만 쓴다. 목록에 없는 장소·음식·지명은 절대 만들지 않는다.
- shot_type 은 여러 명이 나온 사진이면 group, 한 명이면 solo,
  사람이 없는 사진이면 no_face, 언급이 없으면 any 다.
- member_names 는 주어진 멤버 이름 목록에 있는 이름만 쓴다. 없으면 빈 배열이다.
- only_best 는 "베스트", "잘 나온 것만" 처럼 대표 컷만 원할 때 true 다.
- 확실하지 않으면 넣지 않는다. 비워 두는 편이 틀리게 채우는 것보다 낫다."""

_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {"type": "array", "items": {"type": "string", "enum": list(SEARCH_TAGS)}},
        "shot_type": {"type": "string", "enum": list(SHOT_TYPES)},
        "member_names": {"type": "array", "items": {"type": "string"}},
        "only_best": {"type": "boolean"},
    },
    "required": ["tags", "shot_type", "member_names", "only_best"],
    "additionalProperties": False,
}


def parse_search_query(
    query: str,
    *,
    member_names: Sequence[str] = (),
    settings: SummarySettings | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """자연어 검색어를 {tags, shot_type, member_names, only_best} 로 바꾼다.

    반환값은 그대로 SQL WHERE 로 옮길 수 있는 필터다. 검색 결과가 아니다.
      tags         AND 조건으로 쓴다 (photos.tags 에 전부 포함)
      shot_type    'any' 면 조건을 걸지 않는다
      member_names photo_members 조인 조건. 앨범에 실제로 있는 이름만 돌려준다
      only_best    True 면 photos.is_best 조건 추가

    provider 가 mock/off 면 모델을 부르지 않고 한국어 키워드 규칙으로 파싱한다.
    """
    settings = settings or load_summary_settings()
    started = time.perf_counter()
    text = (query or "").strip()
    known_names = [str(name) for name in member_names or []]

    if not text:
        raise AnalysisError("EMPTY_QUERY", "검색어가 비어 있습니다", retryable=False)

    if settings.provider == PROVIDER_BEDROCK:
        filters, usage = _bedrock_search_filters(text, known_names, settings, client)
        provider, mode, calls = PROVIDER_BEDROCK, MODE_LIVE, 1
    else:
        filters, usage = _rule_search_filters(text, known_names), None
        provider, mode, calls = PROVIDER_MOCK, MODE_MOCK, 0

    filters = _sanitize_filters(filters, known_names)
    return {
        **filters,
        "query": text,
        "provider": provider,
        "mode": mode,
        "model_id": settings.model_id if calls else None,
        "calls": {"bedrock_invoke": calls},
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "usage": usage,
    }


def _sanitize_filters(filters: Mapping[str, Any], known_names: Sequence[str]) -> dict[str, Any]:
    """모델이 무엇을 반환하든 허용된 값만 남긴다. 지어낸 태그·이름은 버린다."""
    tags = [t for t in (filters.get("tags") or []) if t in SEARCH_TAGS]
    shot_type = filters.get("shot_type")
    if shot_type not in SHOT_TYPES:
        shot_type = "any"
    names = [n for n in (filters.get("member_names") or []) if n in known_names]
    return {
        "tags": sorted(dict.fromkeys(tags), key=SEARCH_TAGS.index),
        "shot_type": shot_type,
        "member_names": sorted(dict.fromkeys(names)),
        "only_best": bool(filters.get("only_best")),
        "understood": bool(tags or shot_type != "any" or names or filters.get("only_best")),
    }


def _rule_search_filters(text: str, known_names: Sequence[str]) -> dict[str, Any]:
    """모델 없이 키워드로만 파싱한다. 결정론적이고 지어내지 않는다."""
    lowered = text.lower()
    tags = [tag for tag, words in _TAG_KEYWORDS.items() if any(w in lowered for w in words)]

    shot_type = "any"
    if any(w in lowered for w in _NO_FACE_KEYWORDS):
        shot_type = "no_face"
    elif any(w in lowered for w in _GROUP_KEYWORDS):
        shot_type = "group"
    elif any(w in lowered for w in _SOLO_KEYWORDS):
        shot_type = "solo"

    names = [name for name in known_names if name and name in text]
    return {
        "tags": tags,
        "shot_type": shot_type,
        "member_names": names,
        "only_best": any(w in lowered for w in _BEST_KEYWORDS),
    }


def _bedrock_search_filters(
    text: str,
    known_names: Sequence[str],
    settings: SummarySettings,
    client: Any | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    client = client or _bedrock_client(settings)
    payload = json.dumps(
        {
            "query": text,
            "allowed_tags": list(SEARCH_TAGS),
            "allowed_shot_types": list(SHOT_TYPES),
            "album_member_names": list(known_names),
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    try:
        response = client.messages.create(
            model=settings.model_id,
            max_tokens=2000,
            system=_SEARCH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": _SEARCH_SCHEMA},
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise _translate_summary_error(exc) from exc

    if getattr(response, "stop_reason", None) == "refusal":
        raise AnalysisError("SEARCH_REFUSED", "검색어 해석이 거절되었습니다", retryable=False)

    block = next(
        (b.text for b in getattr(response, "content", []) if getattr(b, "type", None) == "text"),
        None,
    )
    if not block:
        raise AnalysisError("SEARCH_EMPTY", "검색어를 해석하지 못했습니다", retryable=True)
    try:
        filters = json.loads(block)
    except ValueError as exc:
        raise AnalysisError(
            "SEARCH_INVALID", "검색어 해석 결과 형식이 올바르지 않습니다", retryable=True
        ) from exc

    usage = getattr(response, "usage", None)
    usage_dict = (
        {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
        if usage is not None
        else None
    )
    return filters, usage_dict

"""OpenAI-compatible multimodal gateway enrichment for photo analysis.

Face identity remains owned by the configured FACE_PROVIDER.  When enabled,
this module replaces only scene tags and general image-quality estimates.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from .quality import AnalysisError, compute_best_score, inspect_image

PROVIDER_OFF = "off"
PROVIDER_GATEWAY = "gateway"
MODE_HYBRID = "hybrid"


@dataclass(frozen=True)
class GatewaySettings:
    provider: str
    api_base: str
    api_key: str
    model_id: str
    timeout_seconds: float


def load_gateway_settings(env: Mapping[str, str] | None = None) -> GatewaySettings:
    env = env if env is not None else os.environ
    provider = (env.get("VISION_PROVIDER") or PROVIDER_OFF).strip().lower()
    if provider not in {PROVIDER_OFF, PROVIDER_GATEWAY}:
        raise AnalysisError(
            "CONFIG_INVALID",
            "VISION_PROVIDER 설정이 올바르지 않습니다 (off 또는 gateway)",
            retryable=False,
        )

    api_base = (env.get("VISION_API_BASE") or "").strip().rstrip("/")
    api_key = (env.get("VISION_API_KEY") or "").strip()
    model_id = (env.get("VISION_MODEL_ID") or "").strip()
    try:
        timeout_seconds = float(env.get("VISION_TIMEOUT_SECONDS") or "45")
    except ValueError:
        raise AnalysisError(
            "CONFIG_INVALID", "VISION_TIMEOUT_SECONDS 설정이 숫자가 아닙니다", retryable=False
        ) from None

    if provider == PROVIDER_GATEWAY:
        parsed = urlparse(api_base)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AnalysisError(
                "CONFIG_INVALID", "VISION_API_BASE는 HTTPS 주소여야 합니다", retryable=False
            )
        if not api_key or not model_id:
            raise AnalysisError(
                "CONFIG_INVALID",
                "VISION_API_KEY와 VISION_MODEL_ID가 필요합니다",
                retryable=False,
            )
        if timeout_seconds <= 0:
            raise AnalysisError(
                "CONFIG_INVALID", "VISION_TIMEOUT_SECONDS는 0보다 커야 합니다", retryable=False
            )

    return GatewaySettings(provider, api_base, api_key, model_id, timeout_seconds)


def enrich_analysis(
    result: dict[str, Any],
    image_bytes: bytes,
    *,
    settings: GatewaySettings | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    settings = settings or load_gateway_settings()
    if settings.provider == PROVIDER_OFF:
        return result

    info = inspect_image(image_bytes)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": settings.model_id,
        "temperature": 0,
        "max_tokens": 400,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You classify travel photos. Return one JSON object only with keys tags and quality. "
                    "tags must contain 0-8 short Korean scene or activity labels. quality must contain "
                    "sharpness and brightness as numbers from 0 to 100, and eyes_open_ratio from 0 to 1. "
                    "Do not identify people and do not infer sensitive traits."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "이 여행 사진을 분류해 주세요."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{info.mime};base64,{encoded}"},
                    },
                ],
            },
        ],
    }

    owns_client = client is None
    client = client or httpx.Client(timeout=settings.timeout_seconds)
    try:
        response = client.post(
            f"{settings.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {settings.api_key}"},
            json=payload,
        )
    except httpx.TimeoutException as exc:
        raise AnalysisError("GATEWAY_TIMEOUT", "AI 사진 분류 시간이 초과됐습니다", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise AnalysisError("GATEWAY_CONNECTION", "AI 사진 분류 서버에 연결할 수 없습니다", retryable=True) from exc
    finally:
        if owns_client:
            client.close()

    if response.status_code in {401, 403}:
        raise AnalysisError("GATEWAY_AUTH", "AI 게이트웨이 인증을 확인해 주세요", retryable=False)
    if response.status_code == 429 or response.status_code >= 500:
        raise AnalysisError("GATEWAY_UNAVAILABLE", "AI 사진 분류 서버가 일시적으로 사용할 수 없습니다", retryable=True)
    if response.status_code >= 400:
        raise AnalysisError("GATEWAY_REQUEST", "AI 사진 분류 요청을 처리하지 못했습니다", retryable=False)

    parsed = _parse_response(response)
    enriched = dict(result)
    enriched["tags"] = _tags(parsed.get("tags"))
    enriched["quality"] = _quality(parsed.get("quality"))
    enriched["best_score"] = compute_best_score(enriched["quality"])
    enriched["provider"] = f"{result.get('provider') or 'unknown'}+gateway"
    enriched["mode"] = MODE_HYBRID
    calls = dict(result.get("calls") or {})
    calls["vision_classify"] = 1
    calls["total"] = int(calls.get("total") or 0) + 1
    enriched["calls"] = calls
    enriched["vision_model_id"] = settings.model_id
    warnings = list(result.get("warnings") or [])
    warnings.append("장면·품질은 외부 AI가 분석했고 얼굴 매칭은 FACE_PROVIDER 결과를 유지했습니다")
    enriched["warnings"] = warnings
    return enriched


def _parse_response(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
        text = str(content).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(text)
    except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise AnalysisError(
            "GATEWAY_RESPONSE", "AI 사진 분류 응답 형식이 올바르지 않습니다", retryable=False
        ) from exc
    if not isinstance(parsed, dict):
        raise AnalysisError("GATEWAY_RESPONSE", "AI 사진 분류 응답 형식이 올바르지 않습니다", retryable=False)
    return parsed


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AnalysisError("GATEWAY_RESPONSE", "AI 사진 태그 형식이 올바르지 않습니다", retryable=False)
    tags: list[str] = []
    for item in value:
        tag = str(item).strip()[:30]
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:8]


def _quality(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        raise AnalysisError("GATEWAY_RESPONSE", "AI 사진 품질 형식이 올바르지 않습니다", retryable=False)
    try:
        sharpness = min(100.0, max(0.0, float(value["sharpness"])))
        brightness = min(100.0, max(0.0, float(value["brightness"])))
        eyes_open_ratio = min(1.0, max(0.0, float(value["eyes_open_ratio"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisError("GATEWAY_RESPONSE", "AI 사진 품질 형식이 올바르지 않습니다", retryable=False) from exc
    return {
        "sharpness": round(sharpness, 4),
        "brightness": round(brightness, 4),
        "eyes_open_ratio": round(eyes_open_ratio, 4),
    }

from __future__ import annotations

import io
import ssl

import httpx
import pytest
from PIL import Image

from backend.app.quality import AnalysisError
from backend.app.vision_gateway import (
    GatewaySettings,
    enrich_analysis,
    load_gateway_settings,
)


def _image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 80), color=(100, 140, 180)).save(output, format="JPEG")
    return output.getvalue()


def test_gateway_is_off_by_default():
    settings = load_gateway_settings({})
    result = {"provider": "mock", "mode": "mock"}
    assert enrich_analysis(result, b"unused", settings=settings) is result


def test_gateway_requires_https_key_and_model():
    with pytest.raises(AnalysisError) as exc:
        load_gateway_settings({"VISION_PROVIDER": "gateway", "VISION_API_BASE": "http://example.test/v1"})
    assert exc.value.code == "CONFIG_INVALID"


def test_gateway_replaces_tags_but_keeps_face_provider_quality():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://gateway.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        payload = __import__("json").loads(request.content)
        assert payload["model"] == "bedrock-haiku"
        image_url = payload["messages"][1]["content"][1]["image_url"]["url"]
        assert image_url.startswith("data:image/jpeg;base64,")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"tags":["바다","노을","바다"]}'
                        }
                    }
                ]
            },
        )

    settings = GatewaySettings("gateway", "https://gateway.test/v1", "secret", "bedrock-haiku", 5)
    measured_quality = {"sharpness": 91.5, "brightness": 60.0, "eyes_open_ratio": 1.0}
    base = {
        "provider": "mock",
        "mode": "mock",
        "tags": ["합성"],
        "quality": dict(measured_quality),
        "best_score": 77.75,
        "calls": {"total": 0},
        "warnings": [],
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = enrich_analysis(base, _image_bytes(), settings=settings, client=client)

    assert result["tags"] == ["바다", "노을"]
    # 품질 지표와 베스트컷 점수는 얼굴 공급자의 실측값을 그대로 유지한다.
    assert result["quality"] == measured_quality
    assert result["best_score"] == 77.75
    assert result["provider"] == "mock+gateway"
    assert result["mode"] == "hybrid"
    assert result["calls"] == {"total": 1, "vision_classify": 1}
    assert result["vision_model_id"] == "bedrock-haiku"


def test_gateway_auth_error_is_not_retryable():
    settings = GatewaySettings("gateway", "https://gateway.test/v1", "bad", "bedrock-haiku", 5)
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "invalid"}))
    with httpx.Client(transport=transport) as client, pytest.raises(AnalysisError) as exc:
        enrich_analysis({"provider": "mock"}, _image_bytes(), settings=settings, client=client)
    assert exc.value.code == "GATEWAY_AUTH"
    assert exc.value.retryable is False


def test_tls_verification_is_on_unless_explicitly_disabled():
    base_env = {
        "VISION_PROVIDER": "gateway",
        "VISION_API_BASE": "https://gateway.test/v1",
        "VISION_API_KEY": "secret",
        "VISION_MODEL_ID": "bedrock-haiku",
    }
    assert load_gateway_settings(base_env).verify_tls is True
    assert load_gateway_settings({**base_env, "VISION_VERIFY_TLS": "false"}).verify_tls is False
    assert load_gateway_settings({**base_env, "VISION_VERIFY_TLS": "0"}).verify_tls is False


def test_certificate_failure_is_reported_as_config_problem_not_a_retry():
    """자체서명 인증서를 만나면 재시도해도 소용없다. 조치 방법을 코드로 구분해 알린다."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("certificate verify failed") from ssl.SSLCertVerificationError(
            "self-signed certificate"
        )

    settings = GatewaySettings("gateway", "https://gateway.test/v1", "secret", "bedrock-haiku", 5)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AnalysisError) as exc:
            enrich_analysis({"provider": "mock"}, _image_bytes(), settings=settings, client=client)

    assert exc.value.code == "GATEWAY_TLS"
    assert exc.value.retryable is False

"""insights.py 테스트 (역할 4, T3 여행 요약).

Bedrock 을 실제로 호출하지 않는다. 가짜 클라이언트로 요청 인자·응답 처리·오류 변환만 본다.
실제 Bedrock 호출은 이 세션에서 하지 않았다(미검증).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.app.insights import (
    AUTH_MESSAGE_KO,
    DEFAULT_MODEL_ID,
    AnalysisError,
    build_facts,
    load_summary_settings,
    select_highlights,
    summarize_album,
)


# --------------------------------------------------------------------------
# 가짜 Anthropic(Bedrock) 클라이언트
# --------------------------------------------------------------------------
class FakeMessages:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.messages = FakeMessages(response, error)


def text_response(payload, *, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False))],
        usage=SimpleNamespace(input_tokens=321, output_tokens=64),
    )


@pytest.fixture
def album():
    return {
        "name": "부산 여행",
        "photo_count": 4,
        "member_names": ["지민", "현우"],
        "photos": [
            {"id": "p1", "best_score": 90.0, "shot_type": "group", "tags": ["바다"],
             "captured_at": "2026-09-18T10:00:00", "is_best": True},
            {"id": "p2", "best_score": 80.0, "shot_type": "group", "tags": ["바다"],
             "captured_at": "2026-09-18T10:00:01", "is_best": False},
            {"id": "p3", "best_score": 70.0, "shot_type": "solo", "tags": ["카페"],
             "captured_at": "2026-09-18T13:00:00", "is_best": True},
            {"id": "p4", "best_score": None, "shot_type": "unknown", "tags": [],
             "captured_at": None, "is_best": True},
        ],
    }


# --------------------------------------------------------------------------
# 설정
# --------------------------------------------------------------------------
def test_default_summary_provider_is_mock():
    assert load_summary_settings({}).provider == "mock"


def test_default_model_id_and_region():
    settings = load_summary_settings({"SUMMARY_PROVIDER": "bedrock"})
    assert settings.model_id == DEFAULT_MODEL_ID
    assert settings.region == "us-east-1"


def test_invalid_summary_provider_is_rejected():
    with pytest.raises(AnalysisError) as err:
        load_summary_settings({"SUMMARY_PROVIDER": "gemini"})
    assert err.value.code == "CONFIG_INVALID"


# --------------------------------------------------------------------------
# 대표 사진 선정 (LLM 미사용)
# --------------------------------------------------------------------------
def test_highlights_skip_unanalyzed_and_burst_losers(album):
    picks = [h["photo_id"] for h in select_highlights(album["photos"])]
    assert "p2" not in picks  # is_best=False -> 연사 탈락 컷
    assert "p4" not in picks  # best_score 없음 -> 아직 분석 안 됨
    assert picks == ["p1", "p3"]


def test_highlights_prefer_scene_diversity():
    photos = [
        {"id": "a", "best_score": 99.0, "shot_type": "solo", "tags": ["바다"]},
        {"id": "b", "best_score": 98.0, "shot_type": "solo", "tags": ["바다"]},
        {"id": "c", "best_score": 50.0, "shot_type": "solo", "tags": ["산"]},
    ]
    picks = [h["photo_id"] for h in select_highlights(photos, count=2)]
    # 점수만 보면 a, b 지만 장면이 겹치므로 새 태그를 가진 c 가 먼저 온다
    assert picks == ["a", "c"]


def test_highlights_are_capped_and_have_reasons():
    photos = [
        {"id": f"p{i}", "best_score": float(100 - i), "shot_type": "solo", "tags": [f"t{i}"]}
        for i in range(10)
    ]
    picks = select_highlights(photos)
    assert len(picks) == 5
    assert all(pick["reason"] for pick in picks)


def test_highlight_selection_is_deterministic(album):
    assert select_highlights(album["photos"]) == select_highlights(album["photos"])


# --------------------------------------------------------------------------
# 사실 집계
# --------------------------------------------------------------------------
def test_build_facts_counts_tags_and_shot_types(album):
    facts = build_facts(album)
    assert facts["tag_counts"] == {"바다": 2, "카페": 1}
    assert facts["shot_type_counts"] == {"group": 2, "solo": 1, "unknown": 1}
    assert facts["member_names"] == ["지민", "현우"]
    assert facts["date_range"]["start"] == "2026-09-18T10:00:00"


def test_build_facts_does_not_invent_dates():
    facts = build_facts({"name": "무제", "photos": [{"id": "p1", "tags": [], "shot_type": "solo"}]})
    assert facts["date_range"]["start"] is None
    assert facts["date_range"]["end"] is None
    assert facts["date_range"]["note"] == "촬영 시각 정보 없음"


def test_facts_exclude_filenames_and_raw_photo_rows(album):
    facts = build_facts(album)
    assert "photos" not in facts
    assert set(facts) == {
        "album_name",
        "photo_count",
        "member_names",
        "tag_counts",
        "shot_type_counts",
        "date_range",
    }


# --------------------------------------------------------------------------
# mock / off
# --------------------------------------------------------------------------
def test_mock_summary_uses_only_real_numbers(album):
    result = summarize_album(album, settings=load_summary_settings({"SUMMARY_PROVIDER": "mock"}))
    assert result["mode"] == "mock"
    assert result["calls"]["bedrock_invoke"] == 0
    assert result["warnings"]
    joined = " ".join(result["summary_lines"])
    assert "4장" in joined
    assert "2명" in joined
    assert "단체샷 2장" in joined


def test_off_provider_returns_no_lines_but_keeps_highlights(album):
    result = summarize_album(album, settings=load_summary_settings({"SUMMARY_PROVIDER": "off"}))
    assert result["summary_lines"] == []
    assert result["mode"] == "off"
    assert [h["photo_id"] for h in result["highlights"]] == ["p1", "p3"]


# --------------------------------------------------------------------------
# bedrock 경로 (가짜 클라이언트)
# --------------------------------------------------------------------------
def test_bedrock_called_once_with_expected_request(album):
    client = FakeClient(text_response({"summary_lines": ["한 줄", "두 줄", "세 줄"]}))
    settings = load_summary_settings({"SUMMARY_PROVIDER": "bedrock"})
    result = summarize_album(album, settings=settings, client=client)

    assert result["summary_lines"] == ["한 줄", "두 줄", "세 줄"]
    assert result["calls"]["bedrock_invoke"] == 1
    assert result["mode"] == "live"
    assert result["model_id"] == DEFAULT_MODEL_ID
    assert result["usage"] == {"input_tokens": 321, "output_tokens": 64}

    kwargs = client.messages.kwargs
    assert kwargs["model"] == DEFAULT_MODEL_ID
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["output_config"]["effort"] == "low"
    # 모델에는 집계 사실만 보낸다
    sent = json.loads(kwargs["messages"][0]["content"])
    assert set(sent) == set(build_facts(album))


def test_bedrock_lines_are_trimmed_to_three(album):
    client = FakeClient(text_response({"summary_lines": ["a", "b", "c", "d", "e"]}))
    result = summarize_album(
        album, settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}), client=client
    )
    assert result["summary_lines"] == ["a", "b", "c"]


def test_long_line_is_truncated(album):
    client = FakeClient(text_response({"summary_lines": ["가" * 200, "b", "c"]}))
    result = summarize_album(
        album, settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}), client=client
    )
    assert len(result["summary_lines"][0]) == 60


def test_refusal_stop_reason_is_surfaced(album):
    client = FakeClient(text_response({"summary_lines": ["a", "b", "c"]}, stop_reason="refusal"))
    with pytest.raises(AnalysisError) as err:
        summarize_album(
            album, settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}), client=client
        )
    assert err.value.code == "SUMMARY_REFUSED"


def test_truncated_output_is_retryable(album):
    client = FakeClient(text_response({"summary_lines": ["a", "b", "c"]}, stop_reason="max_tokens"))
    with pytest.raises(AnalysisError) as err:
        summarize_album(
            album, settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}), client=client
        )
    assert err.value.code == "SUMMARY_TRUNCATED"
    assert err.value.retryable is True


def test_malformed_json_is_reported_not_guessed(album):
    bad = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="요약: 좋았습니다")],
        usage=None,
    )
    with pytest.raises(AnalysisError) as err:
        summarize_album(
            album,
            settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}),
            client=FakeClient(bad),
        )
    assert err.value.code == "SUMMARY_INVALID"


# --------------------------------------------------------------------------
# 오류 변환
# --------------------------------------------------------------------------
def _anthropic_error(cls_name, status_code):
    import httpx
    import anthropic

    cls = getattr(anthropic, cls_name)
    request = httpx.Request("POST", "https://bedrock.example/v1/messages")
    response = httpx.Response(status_code, request=request, json={"error": {"message": "arn:aws:iam::1:role/secret"}})
    return cls("boom", response=response, body=None)


@pytest.mark.parametrize(
    "cls_name,status,code,retryable",
    [
        ("AuthenticationError", 401, "AWS_AUTH", False),
        ("PermissionDeniedError", 403, "AWS_AUTH", False),
        ("NotFoundError", 404, "SUMMARY_MODEL_UNAVAILABLE", False),
        ("RateLimitError", 429, "SUMMARY_THROTTLED", True),
        ("InternalServerError", 500, "SUMMARY_FAILED", True),
    ],
)
def test_api_errors_are_translated(album, cls_name, status, code, retryable):
    client = FakeClient(error=_anthropic_error(cls_name, status))
    with pytest.raises(AnalysisError) as err:
        summarize_album(
            album, settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}), client=client
        )
    assert err.value.code == code
    assert err.value.retryable is retryable
    assert "arn:aws:iam" not in json.dumps(err.value.to_dict(), ensure_ascii=False)


def test_auth_error_message_is_unified(album):
    client = FakeClient(error=_anthropic_error("PermissionDeniedError", 403))
    with pytest.raises(AnalysisError) as err:
        summarize_album(
            album, settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}), client=client
        )
    assert err.value.message_ko == AUTH_MESSAGE_KO


def test_missing_credentials_is_not_silently_mocked(album):
    from botocore.exceptions import NoCredentialsError

    client = FakeClient(error=NoCredentialsError())
    with pytest.raises(AnalysisError) as err:
        summarize_album(
            album, settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}), client=client
        )
    assert err.value.code == "AWS_AUTH"
    assert err.value.retryable is False


# --------------------------------------------------------------------------
# 자연어 검색 구조화 (T3 8-b)
# --------------------------------------------------------------------------
from backend.app.insights import SEARCH_TAGS, parse_search_query  # noqa: E402


def rule_settings():
    return load_summary_settings({"SUMMARY_PROVIDER": "mock"})


def test_rule_parser_handles_the_demo_query():
    result = parse_search_query("바다에서 찍은 단체샷", settings=rule_settings())
    assert result["tags"] == ["바다"]
    assert result["shot_type"] == "group"
    assert result["only_best"] is False
    assert result["understood"] is True
    assert result["calls"]["bedrock_invoke"] == 0
    assert result["mode"] == "mock"


def test_rule_parser_detects_solo_and_best():
    result = parse_search_query("혼자 나온 사진 중에 잘 나온 것만", settings=rule_settings())
    assert result["shot_type"] == "solo"
    assert result["only_best"] is True


def test_rule_parser_detects_no_face():
    result = parse_search_query("사람 없는 풍경 사진", settings=rule_settings())
    assert result["shot_type"] == "no_face"


def test_rule_parser_matches_only_real_member_names():
    result = parse_search_query("지민이 나온 카페 사진", member_names=["지민", "현우"], settings=rule_settings())
    assert result["member_names"] == ["지민"]
    assert result["tags"] == ["카페"]


def test_unknown_query_is_reported_as_not_understood():
    result = parse_search_query("어제 그거", settings=rule_settings())
    assert result["tags"] == []
    assert result["shot_type"] == "any"
    assert result["understood"] is False


def test_empty_query_is_rejected():
    with pytest.raises(AnalysisError) as err:
        parse_search_query("   ", settings=rule_settings())
    assert err.value.code == "EMPTY_QUERY"


def test_bedrock_search_sends_allowed_values_and_calls_once():
    client = FakeClient(
        text_response(
            {"tags": ["바다"], "shot_type": "group", "member_names": [], "only_best": False}
        )
    )
    result = parse_search_query(
        "바닷가에서 다 같이",
        member_names=["지민"],
        settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}),
        client=client,
    )
    assert result["tags"] == ["바다"]
    assert result["shot_type"] == "group"
    assert result["calls"]["bedrock_invoke"] == 1

    sent = json.loads(client.messages.kwargs["messages"][0]["content"])
    assert sent["allowed_tags"] == list(SEARCH_TAGS)
    assert sent["album_member_names"] == ["지민"]
    schema = client.messages.kwargs["output_config"]["format"]["schema"]
    assert schema["properties"]["tags"]["items"]["enum"] == list(SEARCH_TAGS)


def test_invented_tag_or_name_from_model_is_discarded():
    """모델이 목록 밖 태그나 없는 사람 이름을 내도 버린다."""
    client = FakeClient(
        text_response(
            {
                "tags": ["바다", "해운대 해수욕장", "치킨"],
                "shot_type": "무엇",
                "member_names": ["지민", "존재하지않는사람"],
                "only_best": True,
            }
        )
    )
    result = parse_search_query(
        "해운대에서",
        member_names=["지민"],
        settings=load_summary_settings({"SUMMARY_PROVIDER": "bedrock"}),
        client=client,
    )
    assert result["tags"] == ["바다"]
    assert result["shot_type"] == "any"  # 허용 목록 밖 값은 any 로 떨어뜨린다
    assert result["member_names"] == ["지민"]


def test_search_result_is_a_filter_not_search_results():
    result = parse_search_query("바다 단체샷", settings=rule_settings())
    assert "photo_ids" not in result
    assert "results" not in result
    assert set(SEARCH_TAGS) >= set(result["tags"])

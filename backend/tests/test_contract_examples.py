"""3번(백엔드)이 그대로 쓸 수 있는 계약 예시를 실행해서 검증한다.

docs/contracts/role-4-analysis.md 에 적은 예시와 같은 형태인지 지키는 테스트다.
"""

from __future__ import annotations

import json

import pytest

from app.analysis import MODE_MOCK, AnalysisError, analyze, load_settings, validate_reference
from app.quality import inspect_image
from conftest import make_image
from test_analysis import FakeRekognition, box, face


def test_live_group_photo_example(jpeg_bytes, monkeypatch):
    """3번 worker 가 받게 될 실제(rekognition) 응답 형태."""
    from app import analysis

    face_a, face_b = box(0.10, 0.20, 0.15, 0.20), box(0.55, 0.22, 0.14, 0.19)
    ref_a = make_image(width=200, height=200, color=(10, 20, 30))
    ref_b = make_image(width=200, height=200, color=(200, 20, 30))
    client = FakeRekognition(
        faces=[
            face(face_a, sharpness=88.0, brightness=72.0, eyes_open=True, eyes_conf=99.0),
            face(face_b, sharpness=62.0, brightness=68.0, eyes_open=False, eyes_conf=98.0),
        ],
        compare={
            ref_a: [{"Similarity": 97.4, "Face": {"BoundingBox": face_a}}],
            ref_b: [{"Similarity": 95.1, "Face": {"BoundingBox": face_b}}],
        },
        labels=[{"Name": "Sea", "Confidence": 99.1}, {"Name": "Person", "Confidence": 99.9}],
    )
    monkeypatch.setattr(analysis, "_rekognition_client", lambda region: client)

    settings = load_settings({"FACE_PROVIDER": "rekognition"})
    result = analyze(
        jpeg_bytes,
        "album-uuid",
        [{"id": "member-a", "reference_bytes": ref_a}, {"id": "member-b", "reference_bytes": ref_b}],
        settings=settings,
    )

    assert result["shot_type"] == "group"
    assert result["face_count"] == 2
    assert result["tags"] == ["바다"]
    assert result["matched_member_ids"] == ["member-a", "member-b"]
    assert result["quality"]["sharpness"] == 75.0
    assert result["quality"]["eyes_open_ratio"] == 0.5
    # 75*0.5 + 0.5*100*0.4 + 70*0.1 = 37.5 + 20 + 7
    assert result["best_score"] == 64.5
    assert result["calls"] == {
        "detect_faces": 1,
        "compare_faces": 2,
        "detect_labels": 1,
        "total": 4,
    }
    # 응답 전체가 JSON 으로 DB/API 에 실릴 수 있어야 한다
    json.dumps(result, ensure_ascii=False)


def test_error_payload_matches_common_json_error_shape(jpeg_bytes):
    settings = load_settings({"FACE_PROVIDER": "mock", "MOCK_SYNTHETIC_MATCH": "0"})
    no_face = make_image(color=(5, 5, 5))

    import json as _json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "m.json"
        manifest.write_text(
            _json.dumps({"samples": {inspect_image(no_face).content_hash: {"face_count": 0}}}),
            encoding="utf-8",
        )
        settings = load_settings(
            {"FACE_PROVIDER": "mock", "MOCK_MANIFEST_PATH": str(manifest)}
        )
        with pytest.raises(AnalysisError) as err:
            validate_reference(no_face, settings=settings)

    payload = err.value.to_dict()
    assert set(payload) == {"code", "message", "details"}
    assert payload["code"] == "NO_FACE"
    assert payload["details"]["retryable"] is False
    json.dumps(payload, ensure_ascii=False)


def test_mock_response_is_labelled_for_the_ui(jpeg_bytes):
    """화면이 '샘플 분석' 배지를 띄울 수 있도록 mode 가 반드시 실린다."""
    settings = load_settings({"FACE_PROVIDER": "mock"})
    result = analyze(jpeg_bytes, "album-uuid", [{"id": "member-a"}], settings=settings)
    assert result["mode"] == MODE_MOCK
    assert result["provider"] == "mock"
    reference = validate_reference(jpeg_bytes, settings=settings)
    assert reference["mode"] == MODE_MOCK

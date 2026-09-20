"""samples.py 테스트 (역할 4, mock 샘플 manifest 관리).

파일 시스템만 쓴다. DB·S3·AWS 를 건드리지 않는다.
"""

from __future__ import annotations

import json

import pytest

from backend.app.analysis import analyze, load_settings
from backend.app.samples import (
    SUPPORTED_TAGS,
    AnalysisError,
    add_sample,
    digest_of,
    list_samples,
    load_manifest,
    main,
    remove_sample,
)
from tests.conftest import make_image


@pytest.fixture
def manifest(tmp_path):
    return tmp_path / "mock_manifest.json"


def sample_kwargs(**overrides):
    base = dict(
        source="2026-09-20 팀에서 직접 촬영",
        license="피사체 2인 구두 동의",
        face_count=2,
    )
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# 출처·허락을 비워 둘 수 없다
# --------------------------------------------------------------------------
def test_source_is_required(manifest, jpeg_bytes):
    with pytest.raises(AnalysisError) as err:
        add_sample(jpeg_bytes, **sample_kwargs(source="  "), manifest_path=manifest)
    assert err.value.code == "SAMPLE_FIELD_REQUIRED"
    assert err.value.details["field"] == "source"


def test_license_is_required(manifest, jpeg_bytes):
    with pytest.raises(AnalysisError) as err:
        add_sample(jpeg_bytes, **sample_kwargs(license=""), manifest_path=manifest)
    assert err.value.code == "SAMPLE_FIELD_REQUIRED"
    assert err.value.details["field"] == "license"


def test_nothing_is_written_when_validation_fails(manifest, jpeg_bytes):
    with pytest.raises(AnalysisError):
        add_sample(jpeg_bytes, **sample_kwargs(source=""), manifest_path=manifest)
    assert not manifest.exists()


# --------------------------------------------------------------------------
# 입력 검증
# --------------------------------------------------------------------------
def test_non_image_is_rejected(manifest):
    with pytest.raises(AnalysisError) as err:
        add_sample(b"GIF89a" + b"\x00" * 50, **sample_kwargs(), manifest_path=manifest)
    assert err.value.code == "UNSUPPORTED_FORMAT"


def test_negative_face_count_is_rejected(manifest, jpeg_bytes):
    with pytest.raises(AnalysisError) as err:
        add_sample(jpeg_bytes, **sample_kwargs(face_count=-1), manifest_path=manifest)
    assert err.value.code == "SAMPLE_FACE_COUNT_INVALID"


def test_unsupported_tag_is_rejected(manifest, jpeg_bytes):
    with pytest.raises(AnalysisError) as err:
        add_sample(jpeg_bytes, **sample_kwargs(), tags=["해운대"], manifest_path=manifest)
    assert err.value.code == "SAMPLE_TAG_UNSUPPORTED"


def test_supported_tags_are_deduped(manifest, jpeg_bytes):
    _digest, entry = add_sample(
        jpeg_bytes, **sample_kwargs(), tags=["바다", "바다", "산"], manifest_path=manifest
    )
    assert entry["tags"] == ["바다", "산"]
    assert set(entry["tags"]) <= set(SUPPORTED_TAGS)


# --------------------------------------------------------------------------
# 등록 / 조회 / 취소
# --------------------------------------------------------------------------
def test_add_records_hash_and_provenance(manifest, jpeg_bytes):
    digest, entry = add_sample(
        jpeg_bytes, **sample_kwargs(), label="단체샷 A", tags=["바다"], manifest_path=manifest
    )
    assert digest == digest_of(jpeg_bytes)
    assert entry["source"] and entry["license"]
    assert entry["image"]["mime"] == "image/jpeg"

    stored = json.loads(manifest.read_text(encoding="utf-8"))
    assert list(stored["samples"]) == [digest]


def test_duplicate_needs_force(manifest, jpeg_bytes):
    add_sample(jpeg_bytes, **sample_kwargs(), manifest_path=manifest)
    with pytest.raises(AnalysisError) as err:
        add_sample(jpeg_bytes, **sample_kwargs(), manifest_path=manifest)
    assert err.value.code == "SAMPLE_ALREADY_REGISTERED"

    _digest, entry = add_sample(
        jpeg_bytes, **sample_kwargs(face_count=5), manifest_path=manifest, force=True
    )
    assert entry["face_count"] == 5


def test_remove_and_list(manifest, jpeg_bytes, other_jpeg_bytes):
    first, _ = add_sample(jpeg_bytes, **sample_kwargs(), manifest_path=manifest)
    add_sample(other_jpeg_bytes, **sample_kwargs(face_count=0), manifest_path=manifest)
    assert len(list_samples(manifest)) == 2

    remove_sample(first, manifest)
    remaining = list_samples(manifest)
    assert len(remaining) == 1
    assert remaining[0]["sha256"] != first


def test_remove_unknown_hash_is_reported(manifest, jpeg_bytes):
    add_sample(jpeg_bytes, **sample_kwargs(), manifest_path=manifest)
    with pytest.raises(AnalysisError) as err:
        remove_sample("0" * 64, manifest)
    assert err.value.code == "SAMPLE_NOT_FOUND"


def test_missing_manifest_reads_as_empty(manifest):
    assert load_manifest(manifest) == {"samples": {}}
    assert list_samples(manifest) == []


def test_broken_manifest_is_reported_not_ignored(manifest):
    manifest.write_text("{ not json", encoding="utf-8")
    with pytest.raises(AnalysisError) as err:
        load_manifest(manifest)
    assert err.value.code == "MOCK_MANIFEST_INVALID"


def test_manifest_without_samples_key_is_rejected(manifest):
    manifest.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    with pytest.raises(AnalysisError) as err:
        load_manifest(manifest)
    assert err.value.code == "MOCK_MANIFEST_INVALID"


# --------------------------------------------------------------------------
# analyze() 가 실제로 이 manifest 를 읽는다
# --------------------------------------------------------------------------
def test_registered_sample_is_used_by_analyze(manifest, jpeg_bytes):
    add_sample(
        jpeg_bytes,
        **sample_kwargs(face_count=3),
        tags=["카페"],
        member_slots=[0, 1, None],
        manifest_path=manifest,
    )
    settings = load_settings({"FACE_PROVIDER": "mock", "MOCK_MANIFEST_PATH": str(manifest)})
    result = analyze(jpeg_bytes, "album-1", [{"id": "m1"}, {"id": "m2"}], settings=settings)

    assert result["mock_source"] == "manifest"
    assert result["face_count"] == 3
    assert result["shot_type"] == "group"
    assert result["tags"] == ["카페"]
    assert result["matched_member_ids"] == ["m1", "m2"]
    # manifest 샘플에는 synthetic 표시가 붙지 않는다
    assert all("synthetic" not in face for face in result["faces"])


def test_unregistered_image_stays_synthetic(manifest, jpeg_bytes, other_jpeg_bytes):
    add_sample(jpeg_bytes, **sample_kwargs(), manifest_path=manifest)
    settings = load_settings({"FACE_PROVIDER": "mock", "MOCK_MANIFEST_PATH": str(manifest)})

    result = analyze(other_jpeg_bytes, "album-1", [{"id": "m1"}], settings=settings)
    assert result["mock_source"] == "synthetic"
    assert result["warnings"]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def test_cli_add_and_list(manifest, tmp_path, capsys):
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(make_image())

    code = main([
        "--manifest", str(manifest), "add", str(image_path),
        "--faces", "2", "--tags", "바다",
        "--source", "팀 직접 촬영", "--license", "피사체 동의",
    ])
    assert code == 0
    assert "등록했습니다" in capsys.readouterr().out

    assert main(["--manifest", str(manifest), "list"]) == 0
    listed = capsys.readouterr().out
    assert "팀 직접 촬영" in listed
    assert "피사체 동의" in listed


def test_cli_reports_error_without_traceback(manifest, tmp_path, capsys):
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(make_image())

    code = main([
        "--manifest", str(manifest), "add", str(image_path),
        "--faces", "1", "--tags", "해운대",
        "--source", "x", "--license", "y",
    ])
    assert code == 1
    assert "SAMPLE_TAG_UNSUPPORTED" in capsys.readouterr().err


def test_cli_missing_file_is_reported(manifest, tmp_path, capsys):
    code = main([
        "--manifest", str(manifest), "add", str(tmp_path / "nope.jpg"),
        "--faces", "1", "--source", "x", "--license", "y",
    ])
    assert code == 1
    assert "FILE_ERROR" in capsys.readouterr().err


def test_cli_list_says_when_empty(manifest, capsys):
    assert main(["--manifest", str(manifest), "list"]) == 0
    assert "synthetic" in capsys.readouterr().out

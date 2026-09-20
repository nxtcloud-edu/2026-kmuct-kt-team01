"""mock 샘플 manifest 관리 (역할 4 소유, ROLE_04 6번).

`FACE_PROVIDER=mock` 은 파일 sha256 을 시드로 결정론적 결과를 만든다. 등록되지 않은
사진은 `mock_source="synthetic"` 으로 표시되고 얼굴마다 `synthetic: true` 가 붙는다.
여기 등록한 사진만 `mock_source="manifest"` 로, **사람이 직접 적어 넣은 정답**이 된다.

이 모듈은 값을 만들어 내지 않는다. 사람이 세어서 적은 값을 해시에 묶어 저장할 뿐이다.
그래서 `source`(출처)와 `license`(사용 허락)를 반드시 받는다. 저작권/초상권이 확인되지
않은 이미지를 등록하지 않기 위해서다.

사용:
    python -m backend.app.samples add photo.jpg --faces 2 --tags 바다 \\
        --source "2026-09-20 팀 직접 촬영" --license "피사체 4인 구두 동의"
    python -m backend.app.samples list
    python -m backend.app.samples remove <sha256>

DB 를 건드리지 않는다. 이미지 파일을 저장소에 복사하지도 않는다. 해시만 적는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .quality import AnalysisError, inspect_image

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "SUPPORTED_TAGS",
    "digest_of",
    "load_manifest",
    "save_manifest",
    "add_sample",
    "remove_sample",
    "list_samples",
    "main",
]

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "samples" / "mock_manifest.json"

# quality.LABEL_TAG_MAP 이 만들어 내는 9종. 이 밖의 태그는 화면 필터에서 잡히지 않는다.
SUPPORTED_TAGS = ("바다", "산", "음식", "카페", "야경", "노을", "꽃", "숲", "도시")


def digest_of(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def load_manifest(path: Path | str | None = None) -> dict[str, Any]:
    path = Path(path) if path else DEFAULT_MANIFEST_PATH
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"samples": {}}
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(
            "MOCK_MANIFEST_INVALID",
            "mock 샘플 manifest 를 읽지 못했습니다",
            retryable=False,
            details={"path": str(path)},
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("samples"), dict):
        raise AnalysisError(
            "MOCK_MANIFEST_INVALID",
            "manifest 형식이 올바르지 않습니다 (samples 객체가 필요합니다)",
            retryable=False,
            details={"path": str(path)},
        )
    return data


def save_manifest(data: Mapping[str, Any], path: Path | str | None = None) -> Path:
    path = Path(path) if path else DEFAULT_MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def _require_text(value: str | None, field: str, why: str) -> str:
    text = (value or "").strip()
    if not text:
        raise AnalysisError(
            "SAMPLE_FIELD_REQUIRED",
            f"{field} 은(는) 반드시 적어야 합니다. {why}",
            retryable=False,
            details={"field": field},
        )
    return text


def _check_tags(tags: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags or []:
        name = str(tag).strip()
        if name not in SUPPORTED_TAGS:
            raise AnalysisError(
                "SAMPLE_TAG_UNSUPPORTED",
                f"'{name}' 은(는) 지원 태그가 아닙니다. 가능한 값: {', '.join(SUPPORTED_TAGS)}",
                retryable=False,
                details={"tag": name},
            )
        if name not in cleaned:
            cleaned.append(name)
    return cleaned


def add_sample(
    image_bytes: bytes,
    *,
    source: str,
    license: str,
    face_count: int,
    label: str | None = None,
    tags: Sequence[str] = (),
    quality: Mapping[str, float] | None = None,
    member_slots: Sequence[int | None] | None = None,
    reference_face_count: int | None = None,
    manifest_path: Path | str | None = None,
    force: bool = False,
) -> tuple[str, dict[str, Any]]:
    """샘플 1장을 manifest 에 등록한다. (sha256, 저장된 항목) 을 돌려준다.

    `source` 와 `license` 는 비워 둘 수 없다. 출처와 사용 허락을 남기기 위한 것이다.
    이미지는 실제로 열어 보고 JPEG/PNG 인지, 크기가 읽히는지 확인한다.
    """
    source = _require_text(source, "source", "이미지 출처를 남겨야 합니다.")
    license = _require_text(license, "license", "사용 허락 근거를 남겨야 합니다.")

    if not isinstance(face_count, int) or isinstance(face_count, bool) or face_count < 0:
        raise AnalysisError(
            "SAMPLE_FACE_COUNT_INVALID",
            "face_count 는 0 이상의 정수여야 합니다",
            retryable=False,
            details={"face_count": face_count},
        )

    info = inspect_image(image_bytes)  # 형식·크기 검증. 실패하면 여기서 멈춘다.
    digest = info.content_hash
    data = load_manifest(manifest_path)
    if digest in data["samples"] and not force:
        raise AnalysisError(
            "SAMPLE_ALREADY_REGISTERED",
            "이미 등록된 이미지입니다. 덮어쓰려면 --force 를 쓰세요",
            retryable=False,
            details={"sha256": digest},
        )

    entry: dict[str, Any] = {
        "label": (label or "").strip() or Path(source).name,
        "source": source,
        "license": license,
        "face_count": face_count,
        "tags": _check_tags(tags),
        "image": {"mime": info.mime, "width": info.width, "height": info.height},
    }
    if quality:
        entry["quality"] = {k: float(v) for k, v in quality.items()}
    if member_slots is not None:
        entry["member_slots"] = list(member_slots)
    if reference_face_count is not None:
        entry["reference_face_count"] = int(reference_face_count)

    data["samples"][digest] = entry
    save_manifest(data, manifest_path)
    return digest, entry


def remove_sample(digest: str, manifest_path: Path | str | None = None) -> dict[str, Any]:
    data = load_manifest(manifest_path)
    entry = data["samples"].pop(digest, None)
    if entry is None:
        raise AnalysisError(
            "SAMPLE_NOT_FOUND",
            "manifest 에 없는 해시입니다",
            retryable=False,
            details={"sha256": digest},
        )
    save_manifest(data, manifest_path)
    return entry


def list_samples(manifest_path: Path | str | None = None) -> list[dict[str, Any]]:
    data = load_manifest(manifest_path)
    return [
        {"sha256": digest, **entry}
        for digest, entry in sorted(data["samples"].items(), key=lambda kv: kv[0])
    ]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.app.samples",
        description="mock 샘플 manifest 를 관리한다. 값은 사람이 적고, 도구는 해시에 묶기만 한다.",
    )
    parser.add_argument("--manifest", help="manifest 경로 (기본: backend/samples/mock_manifest.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="이미지 1장을 등록한다")
    add.add_argument("image", help="등록할 이미지 파일")
    add.add_argument("--faces", type=int, required=True, help="사람이 직접 센 얼굴 수")
    add.add_argument("--source", required=True, help="이미지 출처 (필수)")
    add.add_argument("--license", required=True, help="사용 허락 근거 (필수)")
    add.add_argument("--label", help="사람이 읽을 이름")
    add.add_argument("--tags", nargs="*", default=[], help=f"한글 태그. 가능한 값: {', '.join(SUPPORTED_TAGS)}")
    add.add_argument("--member-slots", nargs="*", type=int, help="얼굴 순서대로 members 배열 인덱스")
    add.add_argument("--reference-faces", type=int, help="validate_reference 용 얼굴 수 (기본: --faces)")
    add.add_argument("--force", action="store_true", help="이미 등록된 이미지를 덮어쓴다")

    sub.add_parser("list", help="등록된 샘플을 보여 준다")

    remove = sub.add_parser("remove", help="등록을 취소한다")
    remove.add_argument("sha256")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    try:
        if args.command == "add":
            image_bytes = Path(args.image).read_bytes()
            digest, entry = add_sample(
                image_bytes,
                source=args.source,
                license=args.license,
                face_count=args.faces,
                label=args.label,
                tags=args.tags,
                member_slots=args.member_slots,
                reference_face_count=args.reference_faces,
                manifest_path=args.manifest,
                force=args.force,
            )
            print(f"등록했습니다: {digest}")
            print(f"  얼굴 {entry['face_count']}개 / 태그 {entry['tags'] or '없음'}")
            print(f"  출처: {entry['source']}")
            print(f"  허락: {entry['license']}")
            print("이 사진은 이제 mock 모드에서 mock_source='manifest' 로 처리됩니다.")
            return 0

        if args.command == "list":
            rows = list_samples(args.manifest)
            if not rows:
                print("등록된 샘플이 없습니다. 모든 사진이 mock_source='synthetic' 으로 처리됩니다.")
                return 0
            for row in rows:
                print(f"{row['sha256'][:16]}…  얼굴 {row['face_count']}개  {row.get('label', '')}")
                print(f"    출처: {row.get('source', '(없음)')} / 허락: {row.get('license', '(없음)')}")
            return 0

        entry = remove_sample(args.sha256, args.manifest)
        print(f"등록을 취소했습니다: {args.sha256} ({entry.get('label', '')})")
        return 0

    except AnalysisError as exc:
        print(f"{exc.code}: {exc.message_ko}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"FILE_ERROR: 파일을 읽지 못했습니다 ({exc.strerror})", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

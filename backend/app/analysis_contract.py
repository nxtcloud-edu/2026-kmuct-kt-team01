from __future__ import annotations

from typing import Any


class AnalysisUnavailable(RuntimeError):
    pass


def validate_reference(image_bytes: bytes) -> dict[str, Any]:
    try:
        from backend.app.analysis import validate_reference as implementation
    except ImportError as exc:
        raise AnalysisUnavailable("role 4 analysis module is not available") from exc
    return implementation(image_bytes)


def analyze(image_bytes: bytes, album_id: str, members: list[Any]) -> dict[str, Any]:
    try:
        from backend.app.analysis import analyze as implementation
    except ImportError as exc:
        raise AnalysisUnavailable("role 4 analysis module is not available") from exc
    return implementation(image_bytes, album_id, members)

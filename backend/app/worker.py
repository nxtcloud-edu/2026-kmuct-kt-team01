from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from backend.app.analysis_contract import AnalysisUnavailable, analyze
from backend.app.config import get_settings
from backend.app.database import make_engine, make_session_factory
from backend.app.models import (
    AnalysisStatus,
    Member,
    MemberSource,
    Photo,
    PhotoMember,
)
from backend.app.storage import S3Storage, Storage, make_storage

logger = logging.getLogger("zzik.worker")


def claim_one(db: Session) -> str | None:
    photo = db.scalar(
        select(Photo)
        .where(Photo.analysis_status == AnalysisStatus.PENDING.value)
        .order_by(Photo.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if photo is None:
        return None
    photo.analysis_status = AnalysisStatus.PROCESSING.value
    photo.analysis_error = None
    db.commit()
    return photo.id


def error_fields(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, AnalysisUnavailable):
        return "ANALYSIS_UNAVAILABLE", str(exc), False
    return (
        str(getattr(exc, "code", "ANALYSIS_FAILED")),
        str(getattr(exc, "message_ko", str(exc))),
        bool(getattr(exc, "retryable", False)),
    )


def run_analysis_with_retries(photo: Photo, image_bytes: bytes, members: list[Member]):
    for attempt in range(3):
        try:
            return analyze(image_bytes, photo.album_id, members)
        except Exception as exc:
            _, _, retryable = error_fields(exc)
            if not retryable or attempt == 2:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def analysis_members(members: list[Member], storage: Storage) -> list[dict]:
    payloads: list[dict] = []
    for member in members:
        if not member.reference_indexed or not member.reference_key:
            continue
        payload: dict = {"id": member.id}
        if isinstance(storage, S3Storage):
            payload["reference_s3"] = {
                "bucket": storage.bucket,
                "key": member.reference_key,
            }
        else:
            payload["reference_bytes"] = storage.get(member.reference_key)
        payloads.append(payload)
    return payloads


def parse_captured_at(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def comparable_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def apply_result(db: Session, photo: Photo, result: dict) -> None:
    preserved = {
        link.member_id: link
        for link in photo.member_links
        if link.source == MemberSource.MANUAL.value or link.excluded
    }
    db.execute(
        delete(PhotoMember).where(
            PhotoMember.photo_id == photo.id,
            PhotoMember.source == MemberSource.AUTO.value,
            PhotoMember.excluded.is_(False),
        )
    )
    for face in result.get("faces", []):
        if face.get("status") != "matched":
            continue
        member_id = face.get("member_id")
        if not member_id or member_id in preserved:
            continue
        db.add(
            PhotoMember(
                photo_id=photo.id,
                member_id=member_id,
                similarity=face.get("similarity"),
                source=MemberSource.AUTO.value,
                excluded=False,
            )
        )
    photo.face_count = int(result.get("face_count", 0))
    photo.shot_type = str(result.get("shot_type", "unknown"))
    photo.tags = list(result.get("tags", []))
    photo.quality = dict(result.get("quality", {}))
    photo.best_score = result.get("best_score")
    photo.provider = result.get("provider")
    photo.mode = result.get("mode")
    photo.captured_at = parse_captured_at((result.get("capture") or {}).get("captured_at"))
    photo.is_best = True
    photo.analysis_status = AnalysisStatus.DONE.value
    photo.analysis_error = None


def recompute_bursts(db: Session, album_id: str, shot_type: str) -> None:
    photos = list(
        db.scalars(
            select(Photo)
            .where(
                Photo.album_id == album_id,
                Photo.shot_type == shot_type,
                Photo.analysis_status == AnalysisStatus.DONE.value,
                Photo.captured_at.is_not(None),
            )
            .order_by(Photo.captured_at, Photo.id)
        ).all()
    )
    for photo in photos:
        photo.burst_group_id = None
        photo.is_best = True
    clusters: list[list[Photo]] = []
    for photo in photos:
        if (
            not clusters
            or comparable_time(photo.captured_at)
            - comparable_time(clusters[-1][-1].captured_at)
            > timedelta(seconds=3)
        ):
            clusters.append([photo])
        else:
            clusters[-1].append(photo)
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        group_id = str(uuid4())
        for photo in cluster:
            photo.burst_group_id = group_id
            photo.is_best = False
        best = max(
            cluster,
            key=lambda item: (
                item.best_score is not None,
                item.best_score if item.best_score is not None else float("-inf"),
                -item.created_at.timestamp(),
            ),
        )
        best.is_best = True


def process_one(session_factory, storage) -> bool:
    with session_factory() as db:
        photo_id = claim_one(db)
    if photo_id is None:
        return False

    with session_factory() as db:
        photo = db.scalar(
            select(Photo)
            .where(Photo.id == photo_id)
            .options(selectinload(Photo.member_links))
        )
        if photo is None:
            return True
        members = list(db.scalars(select(Member).where(Member.album_id == photo.album_id)).all())
        try:
            image_bytes = storage.get(photo.s3_key)
            result = run_analysis_with_retries(
                photo, image_bytes, analysis_members(members, storage)
            )
            apply_result(db, photo, result)
            db.flush()
            recompute_bursts(db, photo.album_id, photo.shot_type)
            db.commit()
        except Exception as exc:
            db.rollback()
            photo = db.get(Photo, photo_id)
            if photo is not None:
                code, _, _ = error_fields(exc)
                photo.analysis_status = AnalysisStatus.FAILED.value
                photo.analysis_error = code[:1000]
                db.commit()
            logger.exception("photo analysis failed", extra={"photo_id": photo_id})
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    session_factory = make_session_factory(make_engine(settings.database_url))
    storage = make_storage(settings)
    while True:
        if not process_one(session_factory, storage):
            time.sleep(1)


if __name__ == "__main__":
    main()

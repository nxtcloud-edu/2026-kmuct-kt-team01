from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from tempfile import TemporaryFile
from typing import BinaryIO

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.edits import EditError, EditRecord, EditSettings, PhotoSnapshot
from backend.app.models import Approval, Edit, Member, Photo, PhotoMember
from backend.app.storage import LocalStorage, S3Storage, Storage, validate_key


MAX_EDIT_SOURCE_BYTES = 25 * 1024 * 1024


class SqlAlchemyEditTransaction:
    def __init__(self, db: Session, photo: Photo | None) -> None:
        self.db = db
        self._photo = photo
        self.photo = self._snapshot(photo) if photo is not None else None

    def _snapshot(self, photo: Photo) -> PhotoSnapshot:
        active_ids = frozenset(
            self.db.scalars(select(Member.id).where(Member.album_id == photo.album_id)).all()
        )
        confirmed_ids = frozenset(
            self.db.scalars(
                select(PhotoMember.member_id).where(
                    PhotoMember.photo_id == photo.id,
                    PhotoMember.excluded.is_(False),
                )
            ).all()
        )
        approval_face_count = photo.face_count if confirmed_ids else 0
        approval_shot_type = photo.shot_type if confirmed_ids else "no_face"
        return PhotoSnapshot(
            id=photo.id,
            album_id=photo.album_id,
            uploader_member_id=photo.uploader_member_id,
            s3_key=photo.s3_key,
            analysis_status=photo.analysis_status,
            face_count=approval_face_count,
            shot_type=approval_shot_type,
            active_member_ids=active_ids,
            confirmed_member_ids=confirmed_ids,
            # The agreed policy makes only confirmed, non-excluded members approvers.
            # Uncertain/unregistered faces never become approvers or block that set.
            has_unresolved_faces=False,
            provider=photo.provider,
            mode=photo.mode,
        )

    def edits(self) -> list[EditRecord]:
        if self.photo is None:
            return []
        rows = self.db.scalars(
            select(Edit).where(Edit.photo_id == self.photo.id).order_by(Edit.number)
        ).all()
        return [
            EditRecord(
                id=row.id,
                photo_id=row.photo_id,
                author_member_id=row.author_member_id,
                parent_id=row.parent_id,
                number=row.number,
                settings=EditSettings(row.brightness, row.saturation),
                created_at=_isoformat(row.created_at),
            )
            for row in rows
        ]

    def approvals(self) -> dict[str, set[str]]:
        if self.photo is None:
            return {}
        rows = self.db.execute(
            select(Approval.edit_id, Approval.member_id)
            .join(Edit, Edit.id == Approval.edit_id)
            .where(Edit.photo_id == self.photo.id)
        ).all()
        approvals: dict[str, set[str]] = {}
        for edit_id, member_id in rows:
            approvals.setdefault(edit_id, set()).add(member_id)
        return approvals

    def add_edit(self, record: EditRecord) -> None:
        self.db.add(
            Edit(
                id=record.id,
                photo_id=record.photo_id,
                author_member_id=record.author_member_id,
                parent_id=record.parent_id,
                number=record.number,
                brightness=record.settings.brightness,
                saturation=record.settings.saturation,
                created_at=datetime.fromisoformat(record.created_at),
            )
        )
        self.db.flush()

    def add_approval(self, edit_id: str, member_id: str) -> None:
        if self.db.get(Approval, (edit_id, member_id)) is None:
            self.db.add(Approval(edit_id=edit_id, member_id=member_id))
            self.db.flush()

    def remove_approval(self, edit_id: str, member_id: str) -> None:
        self.db.execute(
            delete(Approval).where(
                Approval.edit_id == edit_id, Approval.member_id == member_id
            )
        )

    def clear_approvals(self) -> None:
        if self.photo is None:
            return
        edit_ids = select(Edit.id).where(Edit.photo_id == self.photo.id)
        self.db.execute(delete(Approval).where(Approval.edit_id.in_(edit_ids)))


class SqlAlchemyEditRepository:
    mode = "live"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    @contextmanager
    def transaction(self, photo_id: str) -> Iterator[SqlAlchemyEditTransaction]:
        db = self.session_factory()
        try:
            photo = db.scalar(
                select(Photo).where(Photo.id == photo_id).with_for_update()
            )
            yield SqlAlchemyEditTransaction(db, photo)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def photo_id_for_edit(self, edit_id: str) -> str | None:
        with self.session_factory() as db:
            return db.scalar(select(Edit.photo_id).where(Edit.id == edit_id))


class BackendEditStorage:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    @contextmanager
    def open_original(self, photo: PhotoSnapshot) -> Iterator[BinaryIO]:
        key = validate_key(photo.s3_key)
        if isinstance(self.storage, LocalStorage):
            path = self.storage._path(key)
            try:
                if path.stat().st_size > MAX_EDIT_SOURCE_BYTES:
                    raise EditError("IMAGE_TOO_LARGE", "사진은 25MB 이하만 보정할 수 있습니다.", 413)
                with path.open("rb") as source:
                    yield source
            except FileNotFoundError as exc:
                raise EditError("OBJECT_NOT_FOUND", "사진 파일을 찾을 수 없습니다.", 404) from exc
            return

        with TemporaryFile() as source:
            if isinstance(self.storage, S3Storage):
                response = self.storage.client.get_object(
                    Bucket=self.storage.bucket, Key=key
                )
                body = response["Body"]
                total = 0
                try:
                    while chunk := body.read(64 * 1024):
                        total += len(chunk)
                        if total > MAX_EDIT_SOURCE_BYTES:
                            raise EditError("IMAGE_TOO_LARGE", "사진은 25MB 이하만 보정할 수 있습니다.", 413)
                        source.write(chunk)
                finally:
                    body.close()
            else:
                data = self.storage.get(key)
                if len(data) > MAX_EDIT_SOURCE_BYTES:
                    raise EditError("IMAGE_TOO_LARGE", "사진은 25MB 이하만 보정할 수 있습니다.", 413)
                source.write(data)
            source.seek(0)
            yield source

    def write_edit(self, key: str, stream: BinaryIO) -> None:
        key = self.canonical_key(key)
        stream.seek(0)
        if isinstance(self.storage, LocalStorage):
            path = self.storage._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created = True
                with os.fdopen(descriptor, "wb") as destination:
                    shutil.copyfileobj(stream, destination, length=64 * 1024)
            except Exception:
                if created:
                    path.unlink(missing_ok=True)
                raise
            return
        if isinstance(self.storage, S3Storage):
            self.storage.client.put_object(
                Bucket=self.storage.bucket,
                Key=key,
                Body=stream,
                ContentType="image/jpeg",
                ServerSideEncryption="AES256",
                IfNoneMatch="*",
            )
            return
        raise RuntimeError("Edit storage requires LocalStorage or S3Storage")

    def delete_edit(self, key: str) -> None:
        self.storage.delete(self.canonical_key(key))

    @staticmethod
    def canonical_key(key: str) -> str:
        key = validate_key(key)
        parts = key.split("/")
        if len(parts) == 4 and parts[0] == "edits":
            album_id, photo_id, filename = parts[1:]
            return validate_key(
                f"albums/{album_id}/photos/{photo_id}/{filename}"
            )
        return key


def _isoformat(value: datetime) -> str:
    return value.isoformat()

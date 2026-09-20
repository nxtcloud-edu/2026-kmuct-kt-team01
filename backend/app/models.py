from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class AnalysisStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class ShotType(str, enum.Enum):
    UNKNOWN = "unknown"
    NO_FACE = "no_face"
    SOLO = "solo"
    GROUP = "group"


class MemberSource(str, enum.Enum):
    AUTO = "auto"
    MANUAL = "manual"


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    members: Mapped[list[Member]] = relationship(
        back_populates="album", cascade="all, delete-orphan", passive_deletes=True
    )
    photos: Mapped[list[Photo]] = relationship(
        back_populates="album", cascade="all, delete-orphan", passive_deletes=True
    )


class Member(Base):
    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    album_id: Mapped[str] = mapped_column(
        ForeignKey("albums.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    reference_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    reference_indexed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    album: Mapped[Album] = relationship(back_populates="members")
    uploaded_photos: Mapped[list[Photo]] = relationship(back_populates="uploader")
    photo_links: Mapped[list[PhotoMember]] = relationship(
        back_populates="member", cascade="all, delete-orphan", passive_deletes=True
    )


class Photo(Base):
    __tablename__ = "photos"
    __table_args__ = (
        Index("ix_photos_album_analysis_status", "album_id", "analysis_status"),
        Index("ix_photos_album_shot_type", "album_id", "shot_type"),
        CheckConstraint("byte_size >= 0", name="ck_photos_byte_size_nonnegative"),
        CheckConstraint("face_count >= 0", name="ck_photos_face_count_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    album_id: Mapped[str] = mapped_column(
        ForeignKey("albums.id", ondelete="CASCADE"), nullable=False
    )
    uploader_member_id: Mapped[str] = mapped_column(
        ForeignKey("members.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumb_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    analysis_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AnalysisStatus.PENDING.value
    )
    analysis_error: Mapped[str | None] = mapped_column(String(1000))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    provider: Mapped[str | None] = mapped_column(String(100))
    mode: Mapped[str | None] = mapped_column(String(100))
    face_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uncertain_face_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    unregistered_face_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    shot_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ShotType.UNKNOWN.value
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    quality: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    burst_group_id: Mapped[str | None] = mapped_column(String(36))
    best_score: Mapped[float | None] = mapped_column(Float)
    is_best: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    album: Mapped[Album] = relationship(back_populates="photos")
    uploader: Mapped[Member] = relationship(back_populates="uploaded_photos")
    member_links: Mapped[list[PhotoMember]] = relationship(
        back_populates="photo", cascade="all, delete-orphan", passive_deletes=True
    )
    edits: Mapped[list[Edit]] = relationship(
        back_populates="photo", cascade="all, delete-orphan", passive_deletes=True
    )


class PhotoMember(Base):
    __tablename__ = "photo_members"
    __table_args__ = (
        Index("ix_photo_members_member_id", "member_id"),
        CheckConstraint(
            "similarity IS NULL OR (similarity >= 0 AND similarity <= 100)",
            name="ck_photo_members_similarity_range",
        ),
    )

    photo_id: Mapped[str] = mapped_column(
        ForeignKey("photos.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[str] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    similarity: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MemberSource.AUTO.value
    )
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    photo: Mapped[Photo] = relationship(back_populates="member_links")
    member: Mapped[Member] = relationship(back_populates="photo_links")


class Edit(Base):
    __tablename__ = "edits"
    __table_args__ = (
        UniqueConstraint("photo_id", "number", name="uq_edits_photo_number"),
        CheckConstraint(
            "brightness >= 0.5 AND brightness <= 1.5",
            name="ck_edits_brightness_range",
        ),
        CheckConstraint(
            "saturation >= 0.0 AND saturation <= 2.0",
            name="ck_edits_saturation_range",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    photo_id: Mapped[str] = mapped_column(
        ForeignKey("photos.id", ondelete="CASCADE"), nullable=False
    )
    author_member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("edits.id"))
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    brightness: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    saturation: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    photo: Mapped[Photo] = relationship(back_populates="edits")
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="edit", cascade="all, delete-orphan", passive_deletes=True
    )


class Approval(Base):
    __tablename__ = "approvals"

    edit_id: Mapped[str] = mapped_column(
        ForeignKey("edits.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[str] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    edit: Mapped[Edit] = relationship(back_populates="approvals")

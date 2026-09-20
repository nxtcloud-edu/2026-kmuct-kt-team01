from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AlbumCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)


class AlbumJoin(BaseModel):
    invite_code: str = Field(min_length=4, max_length=32)
    display_name: str = Field(min_length=1, max_length=100)


class AlbumCreated(BaseModel):
    album_id: str
    invite_code: str
    member_id: str


class MemberOut(ORMModel):
    id: str
    display_name: str
    joined_at: datetime
    reference_indexed: bool


class AlbumOut(ORMModel):
    id: str
    name: str
    invite_code: str
    created_at: datetime
    members: list[MemberOut]
    photo_count: int
    tags: list[str] = Field(default_factory=list)


class PhotoMemberOut(BaseModel):
    member_id: str
    display_name: str
    similarity: float | None
    source: str
    excluded: bool


class PhotoOut(ORMModel):
    id: str
    album_id: str
    uploader_member_id: str
    filename: str
    image_url: str
    thumb_url: str
    mime: str
    width: int
    height: int
    byte_size: int
    captured_at: datetime | None
    created_at: datetime
    analysis_status: str
    analysis_error: str | None
    provider: str | None
    mode: str | None
    face_count: int
    uncertain_face_count: int
    unregistered_face_count: int
    shot_type: str
    tags: list[str]
    quality: dict[str, Any]
    burst_group_id: str | None
    best_score: float | None
    is_best: bool
    members: list[PhotoMemberOut] = Field(default_factory=list)


class PhotoPage(BaseModel):
    items: list[PhotoOut]
    page: int
    page_size: int
    total: int
    total_pages: int


class UploadResult(BaseModel):
    filename: str
    ok: bool
    photo: PhotoOut | None = None
    error: dict[str, Any] | None = None


class UploadBatchResponse(BaseModel):
    results: list[UploadResult]


class MemberChange(BaseModel):
    member_id: str
    excluded: bool = False


class PhotoMembersUpdate(BaseModel):
    members: list[MemberChange]


class StatusOut(BaseModel):
    pending: int
    processing: int
    done: int
    failed: int


class CoverageMember(BaseModel):
    member_id: str
    display_name: str
    photo_count: int


class CoverageOut(BaseModel):
    members: list[CoverageMember]
    total: int


class EditCreate(BaseModel):
    brightness: float = Field(ge=0.5, le=1.5)
    saturation: float = Field(ge=0.0, le=2.0)
    parent_id: str | None = None


class DownloadSelection(BaseModel):
    photo_ids: list[str] = Field(min_length=1)
    version: Literal["original", "final"] = "original"

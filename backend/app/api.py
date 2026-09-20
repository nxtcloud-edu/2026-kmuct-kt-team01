from __future__ import annotations

import hashlib
import secrets
import tempfile
import zipfile
import math
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, selectinload

from backend.app.analysis_contract import AnalysisUnavailable, validate_reference
from backend.app.auth import SessionCodec
from backend.app.errors import ApiError, error_body
from backend.app.passcodes import hash_passcode, verify_passcode
from backend.app.phash import compute_dhash
from backend.app.models import (
    Album,
    AnalysisStatus,
    Approval,
    Edit,
    Member,
    MemberSource,
    Photo,
    PhotoMember,
)
from backend.app.schemas import (
    AlbumCreate,
    AlbumCreated,
    AlbumJoin,
    AlbumOut,
    CoverageMember,
    CoverageOut,
    DownloadSelection,
    MemberOut,
    PhotoMemberOut,
    PhotoMembersUpdate,
    PhotoOut,
    PhotoPage,
    StatusOut,
    UploadBatchResponse,
    UploadResult,
)
from backend.app.storage import (
    Storage,
    normalize_image,
    photo_keys,
    read_upload,
    transcode_heif_to_jpeg,
)

router = APIRouter(prefix="/api")


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def current_member(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    session_value: Annotated[str | None, Cookie(alias="zzik_session")] = None,
) -> Member:
    cookie_name = request.app.state.settings.session_cookie_name
    if cookie_name != "zzik_session":
        session_value = request.cookies.get(cookie_name)
    codec: SessionCodec = request.app.state.session_codec
    member_id = codec.decode(session_value)
    member = db.get(Member, member_id)
    if member is None:
        raise ApiError(401, "INVALID_SESSION", "세션의 멤버를 찾을 수 없습니다.")
    return member


def require_album_member(member: Member, album_id: str) -> None:
    if member.album_id != album_id:
        raise ApiError(403, "ALBUM_FORBIDDEN", "이 앨범에 접근할 권한이 없습니다.")


def require_photo(
    db: Session, member: Member, photo_id: str, *, for_update: bool = False
) -> Photo:
    query = (
        select(Photo)
        .where(Photo.id == photo_id)
        .options(selectinload(Photo.member_links))
    )
    if for_update:
        query = query.with_for_update()
    photo = db.scalar(query)
    if photo is None:
        raise ApiError(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.")
    require_album_member(member, photo.album_id)
    return photo


def content_disposition(filename: str) -> str:
    """HTTP 헤더는 latin-1만 허용한다. 한글 등 비-ASCII 파일명을 filename= 에 그대로
    넣으면 UnicodeEncodeError로 500이 난다(다운로드·사진 상세·보정 화면이 전부 깨진다).
    latin-1로 안전한 파일명은 그대로 두고(기존 동작 유지), 아니면 RFC 6266 filename*
    로 원본을, filename= 에는 ASCII로 줄인 대체값을 같이 준다."""
    try:
        filename.encode("latin-1")
        return f'attachment; filename="{filename}"'
    except UnicodeEncodeError:
        ascii_fallback = filename.encode("ascii", "ignore").decode("ascii").strip() or "download"
        return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}'


def photo_out(photo: Photo) -> PhotoOut:
    return PhotoOut(
        **{
            column: getattr(photo, column)
            for column in PhotoOut.model_fields
            if column not in {"image_url", "thumb_url", "members"}
        },
        image_url=f"/api/photos/{photo.id}/download",
        thumb_url=f"/api/photos/{photo.id}/thumbnail",
        members=[PhotoMemberOut(
            member_id=link.member_id,
            display_name=link.member.display_name,
            similarity=link.similarity,
            source=link.source,
            excluded=link.excluded,
        )
        for link in photo.member_links],
    )


def set_session_cookie(request: Request, response: Response, member_id: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.session_cookie_name,
        value=request.app.state.session_codec.encode(member_id),
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )


@router.post("/albums", response_model=AlbumCreated, status_code=201)
def create_album(
    payload: AlbumCreate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> AlbumCreated:
    album = Album(name=payload.name.strip(), invite_code=secrets.token_urlsafe(8))
    member = Member(
        album=album,
        display_name=payload.display_name.strip(),
        passcode_hash=hash_passcode(payload.passcode),
    )
    db.add_all([album, member])
    db.commit()
    set_session_cookie(request, response, member.id)
    return AlbumCreated(
        album_id=album.id, invite_code=album.invite_code, member_id=member.id
    )


@router.post("/albums/join", response_model=AlbumCreated)
def join_album(
    payload: AlbumJoin,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> AlbumCreated:
    album = db.scalar(select(Album).where(Album.invite_code == payload.invite_code))
    if album is None:
        raise ApiError(404, "INVITE_NOT_FOUND", "초대 코드를 찾을 수 없습니다.")

    display_name = payload.display_name.strip()
    # 앨범 안에서는 이름이 곧 신원이다. 같은 이름이 이미 있으면 비밀번호로 본인을 확인하고
    # 그 멤버로 다시 들어간다. 기준 사진과 올린 사진이 그대로 따라온다.
    existing = db.scalar(
        select(Member)
        .where(Member.album_id == album.id, Member.display_name == display_name)
        .order_by(Member.joined_at)
    )
    if existing is not None:
        if existing.passcode_hash is None:
            # 비밀번호 기능 전에 참여한 멤버다. 이 이름으로 처음 다시 들어오는 사람이
            # 비밀번호를 정한다. 초대 코드를 아는 사람만 여기 닿을 수 있다는 가정에 기댄다.
            existing.passcode_hash = hash_passcode(payload.passcode)
            db.commit()
        elif not verify_passcode(payload.passcode, existing.passcode_hash):
            raise ApiError(
                403,
                "PASSCODE_MISMATCH",
                "이미 있는 이름이에요. 비밀번호가 맞지 않으면 다른 이름으로 참여해 주세요.",
            )
        set_session_cookie(request, response, existing.id)
        return AlbumCreated(
            album_id=album.id,
            invite_code=album.invite_code,
            member_id=existing.id,
            rejoined=True,
            reference_indexed=existing.reference_indexed,
        )

    member = Member(
        album_id=album.id,
        display_name=display_name,
        passcode_hash=hash_passcode(payload.passcode),
    )
    db.add(member)
    db.commit()
    set_session_cookie(request, response, member.id)
    return AlbumCreated(
        album_id=album.id, invite_code=album.invite_code, member_id=member.id
    )


@router.get("/albums/{album_id}", response_model=AlbumOut)
def get_album(
    album_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
) -> AlbumOut:
    require_album_member(member, album_id)
    album = db.get(Album, album_id)
    if album is None:
        raise ApiError(404, "ALBUM_NOT_FOUND", "앨범을 찾을 수 없습니다.")
    members = db.scalars(
        select(Member).where(Member.album_id == album_id).order_by(Member.joined_at)
    ).all()
    photo_count = db.scalar(
        select(func.count(Photo.id)).where(Photo.album_id == album_id)
    ) or 0
    photo_tags = db.scalars(
        select(Photo.tags).where(Photo.album_id == album_id)
    ).all()
    tags = sorted({tag for items in photo_tags for tag in (items or [])})
    return AlbumOut(
        id=album.id,
        name=album.name,
        invite_code=album.invite_code,
        created_at=album.created_at,
        members=[MemberOut.model_validate(item) for item in members],
        photo_count=photo_count,
        tags=tags,
    )


@router.post("/members/me/reference")
def upload_reference(
    file: Annotated[UploadFile, File(...)],
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> dict[str, Any]:
    # iPhone HEIC 는 여기서 JPEG 로 바꿔 아래 분석·저장 계층이 손대지 않게 한다.
    raw = transcode_heif_to_jpeg(read_upload(file.file))
    try:
        result = validate_reference(raw)
    except AnalysisUnavailable as exc:
        raise ApiError(
            503,
            "ANALYSIS_UNAVAILABLE",
            "사진 분석 모듈이 아직 연결되지 않았습니다.",
            {"owner": "role-4", "mode": "unavailable"},
        ) from exc
    except Exception as exc:
        code = getattr(exc, "code", "REFERENCE_VALIDATION_FAILED")
        message = getattr(exc, "message_ko", str(exc))
        raise ApiError(422, code, message) from exc

    normalized, _, _, _, _, _ = normalize_image(raw, file.content_type)
    key = f"albums/{member.album_id}/members/{member.id}/reference.jpg"
    storage.put(key, normalized, "image/jpeg")
    member.reference_key = key
    member.reference_indexed = True
    db.commit()
    return {
        "member_id": member.id,
        "reference_indexed": True,
        "provider": result.get("provider"),
        "mode": result.get("mode"),
        "face_count": result.get("face_count"),
    }


@router.post("/albums/{album_id}/photos", response_model=UploadBatchResponse)
def upload_photos(
    album_id: str,
    files: Annotated[list[UploadFile], File(...)],
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> UploadBatchResponse:
    require_album_member(member, album_id)
    results: list[UploadResult] = []
    for upload in files:
        stored_keys: list[str] = []
        try:
            raw = transcode_heif_to_jpeg(read_upload(upload.file))
            _, thumbnail, width, height, captured_at, detected_mime = normalize_image(
                raw, upload.content_type
            )
            photo_id = str(uuid4())
            original_key, thumb_key = photo_keys(album_id, photo_id, detected_mime)
            storage.put(original_key, raw, detected_mime)
            stored_keys.append(original_key)
            storage.put(thumb_key, thumbnail, "image/jpeg")
            stored_keys.append(thumb_key)
            photo = Photo(
                id=photo_id,
                album_id=album_id,
                uploader_member_id=member.id,
                filename=(upload.filename or "photo.jpg")[:255],
                s3_key=original_key,
                thumb_key=thumb_key,
                content_hash=hashlib.sha256(raw).hexdigest(),
                phash=compute_dhash(raw),
                mime=detected_mime,
                width=width,
                height=height,
                byte_size=len(raw),
                captured_at=captured_at,
                analysis_status=AnalysisStatus.PENDING.value,
            )
            db.add(photo)
            db.commit()
            photo.member_links = []
            results.append(
                UploadResult(filename=upload.filename or "photo.jpg", ok=True, photo=photo_out(photo))
            )
        except ApiError as exc:
            db.rollback()
            for key in stored_keys:
                storage.delete(key)
            results.append(
                UploadResult(
                    filename=upload.filename or "unknown",
                    ok=False,
                    error=error_body(exc.code, exc.message, exc.details),
                )
            )
        except Exception:
            db.rollback()
            for key in stored_keys:
                storage.delete(key)
            results.append(
                UploadResult(
                    filename=upload.filename or "unknown",
                    ok=False,
                    error=error_body("UPLOAD_FAILED", "사진 저장에 실패했습니다."),
                )
            )
    return UploadBatchResponse(results=results)


@router.get("/albums/{album_id}/photos", response_model=PhotoPage)
def list_photos(
    album_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    member_id: list[str] | None = Query(default=None),
    shot_type: str | None = None,
    face_status: Literal["unregistered", "uncertain", "no_face"] | None = None,
    tag: str | None = None,
    only_best: bool = False,
    sort: str = "created_at_desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PhotoPage:
    require_album_member(member, album_id)
    query = select(Photo).where(Photo.album_id == album_id).options(selectinload(Photo.member_links))
    for selected_member_id in dict.fromkeys(member_id or []):
        query = query.where(
            Photo.member_links.any(
                (PhotoMember.member_id == selected_member_id)
                & (PhotoMember.excluded.is_(False))
            )
        )
    if shot_type:
        query = query.where(Photo.shot_type == shot_type)
    if face_status == "unregistered":
        query = query.where(Photo.unregistered_face_count > 0)
    elif face_status == "uncertain":
        query = query.where(Photo.uncertain_face_count > 0)
    elif face_status == "no_face":
        query = query.where(Photo.shot_type == "no_face")
    if only_best:
        query = query.where(Photo.is_best.is_(True))
    order = {
        "created_at_asc": Photo.created_at.asc(),
        "captured_at_desc": Photo.captured_at.desc().nullslast(),
        "best_score_desc": Photo.best_score.desc().nullslast(),
    }.get(sort, Photo.created_at.desc())
    photos = list(db.scalars(query.order_by(order)).all())
    if tag:
        photos = [photo for photo in photos if tag in photo.tags]
    total = len(photos)
    start = (page - 1) * page_size
    return PhotoPage(
        items=[photo_out(photo) for photo in photos[start : start + page_size]],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/photos/{photo_id}", response_model=PhotoOut)
def get_photo(
    photo_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
) -> PhotoOut:
    return photo_out(require_photo(db, member, photo_id))


@router.put("/photos/{photo_id}/members", response_model=PhotoOut)
def update_photo_members(
    photo_id: str,
    payload: PhotoMembersUpdate,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
) -> PhotoOut:
    photo = require_photo(db, member, photo_id, for_update=True)
    member_ids = {item.member_id for item in payload.members}
    valid_ids = set(
        db.scalars(
            select(Member.id).where(
                Member.album_id == photo.album_id, Member.id.in_(member_ids)
            )
        ).all()
    )
    if valid_ids != member_ids:
        raise ApiError(422, "INVALID_MEMBER", "다른 앨범의 멤버가 포함되어 있습니다.")

    existing = {link.member_id: link for link in photo.member_links}
    for change in payload.members:
        link = existing.get(change.member_id)
        if link is None:
            db.add(
                PhotoMember(
                    photo_id=photo.id,
                    member_id=change.member_id,
                    source=MemberSource.MANUAL.value,
                    excluded=change.excluded,
                )
            )
        else:
            link.source = MemberSource.MANUAL.value
            link.excluded = change.excluded
            link.similarity = None
    edit_ids = select(Edit.id).where(Edit.photo_id == photo.id)
    db.execute(delete(Approval).where(Approval.edit_id.in_(edit_ids)))
    db.commit()
    db.refresh(photo)
    photo = require_photo(db, member, photo_id)
    return photo_out(photo)


@router.post("/photos/{photo_id}/reanalyze", response_model=PhotoOut)
def reanalyze_photo(
    photo_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
) -> PhotoOut:
    photo = require_photo(db, member, photo_id, for_update=True)
    photo.analysis_status = AnalysisStatus.PENDING.value
    photo.analysis_error = None
    photo.processing_started_at = None
    photo.analysis_attempts = 0
    edit_ids = select(Edit.id).where(Edit.photo_id == photo.id)
    db.execute(delete(Approval).where(Approval.edit_id.in_(edit_ids)))
    db.commit()
    return photo_out(photo)


@router.post("/albums/{album_id}/reanalyze", response_model=StatusOut)
def reanalyze_album(
    album_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[Literal["failed", "all", "unmatched"], Query()] = "failed",
) -> StatusOut:
    """앨범의 사진을 일괄로 분석 대기열로 되돌린다. 사용자가 직접 눌러야 실행된다.

    scope 별로 대상이 다르다. 사진 1장당 분석 호출이 다시 나가므로 기본값은 가장 좁은
    "failed" 이고, 필요한 범위를 사용자가 고른다.

      failed     분석에 실패한 사진만
      unmatched  분석은 끝났지만 '미등록' 얼굴이 남은 사진만.
                 기준 사진을 뒤늦게 등록한 사람이 자기 얼굴을 찾게 하는 용도다.
      all        앨범의 모든 사진

    사람이 직접 지정한 인물 연결(source=manual)과 제외 표시는 worker 가 보존한다.
    다만 보정본 승인은 worker 의 apply_result 가 지우므로 재분석하면 초기화된다.
    """
    require_album_member(member, album_id)

    conditions = [Photo.album_id == album_id]
    if scope == "failed":
        conditions.append(Photo.analysis_status == AnalysisStatus.FAILED.value)
    elif scope == "unmatched":
        # 비교 대상이 될 기준 얼굴이 없으면 다시 돌려도 결과가 같다.
        if not member.reference_indexed or not member.reference_key:
            raise ApiError(
                409,
                "REFERENCE_REQUIRED",
                "기준 사진을 먼저 등록해야 얼굴을 다시 분류할 수 있습니다.",
            )
        conditions.append(Photo.analysis_status == AnalysisStatus.DONE.value)
        conditions.append(Photo.unregistered_face_count > 0)

    photo_ids = list(db.scalars(select(Photo.id).where(*conditions)))
    if photo_ids:
        edit_ids = select(Edit.id).where(Edit.photo_id.in_(photo_ids))
        db.execute(delete(Approval).where(Approval.edit_id.in_(edit_ids)))
        db.execute(
            update(Photo)
            .where(Photo.id.in_(photo_ids))
            .values(
                analysis_status=AnalysisStatus.PENDING.value,
                analysis_error=None,
                processing_started_at=None,
                analysis_attempts=0,
            )
        )
        db.commit()

    rows = db.execute(
        select(Photo.analysis_status, func.count(Photo.id))
        .where(Photo.album_id == album_id)
        .group_by(Photo.analysis_status)
    ).all()
    counts = Counter({status: count for status, count in rows})
    return StatusOut(**{status.value: counts[status.value] for status in AnalysisStatus})


@router.get("/albums/{album_id}/status", response_model=StatusOut)
def album_status(
    album_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
) -> StatusOut:
    require_album_member(member, album_id)
    rows = db.execute(
        select(Photo.analysis_status, func.count(Photo.id))
        .where(Photo.album_id == album_id)
        .group_by(Photo.analysis_status)
    ).all()
    counts = Counter({status: count for status, count in rows})
    return StatusOut(**{status.value: counts[status.value] for status in AnalysisStatus})


@router.get("/albums/{album_id}/coverage", response_model=CoverageOut)
def album_coverage(
    album_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
) -> CoverageOut:
    require_album_member(member, album_id)
    album_members = db.scalars(select(Member).where(Member.album_id == album_id)).all()
    counts = dict(
        db.execute(
            select(PhotoMember.member_id, func.count(PhotoMember.photo_id))
            .join(Photo, Photo.id == PhotoMember.photo_id)
            .where(Photo.album_id == album_id, PhotoMember.excluded.is_(False))
            .group_by(PhotoMember.member_id)
        ).all()
    )
    total = db.scalar(select(func.count(Photo.id)).where(Photo.album_id == album_id)) or 0
    return CoverageOut(
        members=[
            CoverageMember(
                member_id=item.id,
                display_name=item.display_name,
                photo_count=counts.get(item.id, 0),
            )
            for item in album_members
        ],
        total=total,
    )


@router.get("/photos/{photo_id}/download")
def download_photo(
    photo_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> Response:
    photo = require_photo(db, member, photo_id)
    url = storage.signed_url(photo.s3_key, expires=300)
    if url:
        return RedirectResponse(url=url, status_code=307)
    return Response(
        content=storage.get(photo.s3_key),
        media_type=photo.mime,
        headers={"Content-Disposition": content_disposition(photo.filename)},
    )


@router.get("/photos/{photo_id}/thumbnail")
def thumbnail_photo(
    photo_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> Response:
    photo = require_photo(db, member, photo_id)
    url = storage.signed_url(photo.thumb_key, expires=300)
    if url:
        return RedirectResponse(url=url, status_code=307)
    return Response(content=storage.get(photo.thumb_key), media_type="image/jpeg")


@router.delete("/photos/{photo_id}", status_code=204)
def delete_photo(
    photo_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> Response:
    photo = require_photo(db, member, photo_id)
    if photo.uploader_member_id != member.id:
        raise ApiError(403, "PHOTO_DELETE_FORBIDDEN", "업로더만 사진을 삭제할 수 있습니다.")
    keys = [photo.s3_key, photo.thumb_key]
    db.delete(photo)
    db.commit()
    for key in keys:
        storage.delete(key)
    return Response(status_code=204)


def final_edit(db: Session, photo: Photo) -> Edit | None:
    if photo.analysis_status != AnalysisStatus.DONE.value:
        return None
    active_ids = set(
        db.scalars(select(Member.id).where(Member.album_id == photo.album_id)).all()
    )
    confirmed_ids = set(
        db.scalars(
            select(PhotoMember.member_id).where(
                PhotoMember.photo_id == photo.id,
                PhotoMember.excluded.is_(False),
            )
        ).all()
    ) & active_ids
    targets = confirmed_ids
    if photo.shot_type == "no_face" or not targets:
        targets = (
            {photo.uploader_member_id}
            if photo.uploader_member_id in active_ids
            else set()
        )
    if not targets:
        return None
    edits = list(
        db.scalars(
            select(Edit)
            .where(Edit.photo_id == photo.id)
            .order_by(Edit.number.desc())
        ).all()
    )
    if not edits:
        return None
    approvals: dict[str, set[str]] = {}
    for edit_id, member_id in db.execute(
        select(Approval.edit_id, Approval.member_id).where(
            Approval.edit_id.in_([edit.id for edit in edits])
        )
    ):
        approvals.setdefault(edit_id, set()).add(member_id)
    return next(
        (edit for edit in edits if targets <= approvals.get(edit.id, set())), None
    )


def require_edit(db: Session, member: Member, edit_id: str) -> tuple[Edit, Photo]:
    edit = db.get(Edit, edit_id)
    if edit is None:
        raise ApiError(404, "EDIT_NOT_FOUND", "보정 버전을 찾을 수 없습니다.")
    photo = require_photo(db, member, edit.photo_id)
    return edit, photo


def edit_object_key(photo: Photo, edit: Edit) -> str:
    return f"albums/{photo.album_id}/photos/{photo.id}/edit-{edit.number}.jpg"


@router.get("/edits/{edit_id}/preview")
def preview_edit(
    edit_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> Response:
    edit, photo = require_edit(db, member, edit_id)
    key = edit_object_key(photo, edit)
    url = storage.signed_url(key, expires=300)
    if url:
        return RedirectResponse(url=url, status_code=307)
    return Response(content=storage.get(key), media_type="image/jpeg")


@router.get("/edits/{edit_id}/download")
def download_edit(
    edit_id: str,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> Response:
    edit, photo = require_edit(db, member, edit_id)
    filename = f"{Path(photo.filename).stem}-edit-{edit.number}.jpg"
    return Response(
        content=storage.get(edit_object_key(photo, edit)),
        media_type="image/jpeg",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post("/albums/{album_id}/download")
def download_album_selection(
    album_id: str,
    payload: DownloadSelection,
    member: Annotated[Member, Depends(current_member)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> StreamingResponse:
    require_album_member(member, album_id)
    unique_ids = list(dict.fromkeys(payload.photo_ids))
    photos = list(
        db.scalars(
            select(Photo).where(Photo.album_id == album_id, Photo.id.in_(unique_ids))
        ).all()
    )
    if len(photos) != len(unique_ids):
        raise ApiError(404, "PHOTO_NOT_FOUND", "선택한 사진 일부를 찾을 수 없습니다.")
    selected: list[tuple[Photo, str, str]] = []
    for photo in photos:
        key = photo.s3_key
        filename = photo.filename
        if payload.version == "final":
            edit = final_edit(db, photo)
            if edit is None:
                raise ApiError(
                    409,
                    "FINAL_EDIT_NOT_APPROVED",
                    "전원 승인된 보정본이 없는 사진이 있습니다.",
                    {"photo_id": photo.id},
                )
            key = edit_object_key(photo, edit)
            filename = f"{Path(photo.filename).stem}-edit-{edit.number}.jpg"
        selected.append((photo, key, filename))
    archive = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    used_names: set[str] = set()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for index, (photo, key, filename) in enumerate(selected, start=1):
            safe_name = Path(filename).name.replace("\\", "_") or f"photo-{index}.jpg"
            if safe_name in used_names:
                safe_name = f"{index}-{safe_name}"
            used_names.add(safe_name)
            output.writestr(safe_name, storage.get(key))
    archive.seek(0)

    def chunks():
        try:
            while data := archive.read(64 * 1024):
                yield data
        finally:
            archive.close()

    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="zzik-photos.zip"'},
    )


@router.get("/health/ready")
def readiness(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}

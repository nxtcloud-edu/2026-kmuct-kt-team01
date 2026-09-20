"""ROLE-05: original-based rendering and explicit edit approvals.

No global app, ORM models or in-memory production database is created here.
Role 3 supplies authenticated members, transactional repository and private storage.
"""

from dataclasses import dataclass
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from hashlib import file_digest
from io import BytesIO
import logging
import math
from tempfile import TemporaryFile
from threading import BoundedSemaphore
from typing import BinaryIO, Callable, Protocol
from uuid import UUID, uuid4
import warnings

from PIL import Image, ImageCms, ImageEnhance, ImageOps, UnidentifiedImageError
from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException


class EditError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class EditSettings:
    brightness: float = 1.0
    saturation: float = 1.0

    def __post_init__(self):
        for value, low, high in ((self.brightness, 0.5, 1.5), (self.saturation, 0.0, 2.0)):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not low <= value <= high):
                raise EditError("INVALID_EDIT_SETTINGS", "밝기 또는 채도 값이 허용 범위를 벗어났습니다.")


@dataclass(frozen=True)
class RenderResult:
    width: int
    height: int
    byte_size: int
    sha256: str
    original_sha256: str


def render_edit(source: BinaryIO, destination: BinaryIO, settings: EditSettings, *,
                max_bytes: int = 25 * 1024 * 1024,
                max_pixels: int = 20_000_000) -> RenderResult:
    """Render from an ORIGINAL seekable stream into a separate seekable stream.

    Own neither stream. Output is sRGB JPEG, white alpha matte, no EXIF/GPS.
    Callers must serialize renders per small worker to bound peak memory.
    """
    if source is destination:
        raise EditError("ORIGINAL_OVERWRITE", "원본과 출력 파일은 달라야 합니다.")
    source.seek(0, 2)
    if source.tell() > max_bytes:
        raise EditError("IMAGE_TOO_LARGE", "사진은 25MB 이하만 보정할 수 있습니다.", 413)
    source.seek(0)
    original_hash = file_digest(source, "sha256").hexdigest()
    source.seek(0)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as probe:
                if probe.format not in {"JPEG", "PNG"}:
                    raise EditError("UNSUPPORTED_IMAGE", "JPEG와 PNG 사진만 지원합니다.", 415)
                if probe.width * probe.height > max_pixels:
                    raise EditError("TOO_MANY_PIXELS", "사진의 픽셀 수가 보정 한도를 초과했습니다.", 413)
                if getattr(probe, "n_frames", 1) != 1:
                    raise EditError("UNSUPPORTED_IMAGE", "움직이는 PNG는 지원하지 않습니다.", 415)
                probe.verify()
            source.seek(0)
            with Image.open(source) as decoded:
                decoded.load()
                ImageOps.exif_transpose(decoded, in_place=True)
                profile = decoded.info.get("icc_profile")
                has_alpha = "A" in decoded.getbands() or "transparency" in decoded.info
                # Keep CMYK/L channels until their embedded profile is applied.
                if profile:
                    if decoded.mode in {"P", "RGBA"}:
                        profile_input = decoded.convert("RGB")
                    elif decoded.mode == "LA":
                        profile_input = decoded.getchannel("L")
                    else:
                        profile_input = decoded.copy()
                    try:
                        image = ImageCms.profileToProfile(
                            profile_input, ImageCms.ImageCmsProfile(BytesIO(profile)),
                            ImageCms.createProfile("sRGB"), outputMode="RGB")
                    finally:
                        profile_input.close()
                else:
                    image = decoded.convert("RGB")
                try:
                    if has_alpha:
                        matte = Image.new("RGB", image.size, "white")
                        with decoded.convert("RGBA") as rgba, rgba.getchannel("A") as alpha:
                            matte.paste(image, mask=alpha)
                        image.close()
                        image = matte
                    bright = ImageEnhance.Brightness(image).enhance(settings.brightness)
                    image.close()
                    image = bright
                    colored = ImageEnhance.Color(image).enhance(settings.saturation)
                    image.close()
                    image = colored
                    destination.seek(0)
                    destination.truncate()
                    image.save(destination, format="JPEG", quality=92, subsampling=0,
                               exif=b"", icc_profile=None)
                    width, height = image.size
                finally:
                    image.close()
    except EditError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise EditError("TOO_MANY_PIXELS", "사진의 픽셀 수가 보정 한도를 초과했습니다.", 413) from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, ImageCms.PyCMSError) as exc:
        raise EditError("INVALID_IMAGE", "사진을 읽을 수 없습니다. 손상 여부를 확인해 주세요.") from exc
    destination.seek(0, 2)
    byte_size = destination.tell()
    destination.seek(0)
    output_hash = file_digest(destination, "sha256").hexdigest()
    destination.seek(0)
    return RenderResult(width, height, byte_size, output_hash, original_hash)


@dataclass(frozen=True)
class PhotoSnapshot:
    id: str
    album_id: str
    uploader_member_id: str
    s3_key: str
    analysis_status: str
    face_count: int
    shot_type: str
    active_member_ids: frozenset[str]
    confirmed_member_ids: frozenset[str]
    # Adapter must exclude uncertain/excluded matches from confirmed_member_ids.
    # Informational only; unresolved faces are not approvers (team decision #3).
    has_unresolved_faces: bool = True
    provider: str | None = None
    mode: str | None = None


@dataclass(frozen=True)
class EditRecord:
    id: str
    photo_id: str
    author_member_id: str
    parent_id: str | None
    number: int
    settings: EditSettings
    created_at: str


class EditTransaction(Protocol):
    photo: PhotoSnapshot | None

    def edits(self) -> list[EditRecord]: ...
    def approvals(self) -> dict[str, set[str]]: ...
    def add_edit(self, edit: EditRecord) -> None: ...
    def add_approval(self, edit_id: str, member_id: str) -> None: ...
    def remove_approval(self, edit_id: str, member_id: str) -> None: ...
    def clear_approvals(self) -> None: ...


class EditRepository(Protocol):
    # mode='fixture' ONLY for a test adapter; production uses 'live'.
    mode: str

    def transaction(self, photo_id: str) -> AbstractContextManager[EditTransaction]:
        """Serialize ALL photo edits/approvals/member mutations, commit or rollback.

        Production: SELECT photos FOR UPDATE before reading related rows.
        Membership mutation must acquire the same affected-photo locks in ID order.
        """
        ...

    def photo_id_for_edit(self, edit_id: str) -> str | None: ...


class EditStorage(Protocol):
    def open_original(self, photo: PhotoSnapshot) -> AbstractContextManager[BinaryIO]:
        """Return original as a seekable stream (e.g. S3 -> bounded temp file)."""
        ...

    def write_edit(self, key: str, stream: BinaryIO) -> None:
        """Create only: complete object or exception; clean partial writes internally.

        S3 adapter: private put with IfNoneMatch='*', ContentType='image/jpeg'.
        Existing keys must never be overwritten, including after process crashes.
        """
        ...

    def delete_edit(self, key: str) -> None: ...


def edit_key(photo: PhotoSnapshot, number: int) -> str:
    """Deterministic private key, derived from trusted metadata, never filenames."""
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise EditError("INVALID_VERSION", "유효하지 않은 버전 번호입니다.")
    return f"edits/{UUID(photo.album_id)}/{UUID(photo.id)}/edit-{number}.jpg"


def approval_targets(photo: PhotoSnapshot) -> tuple[frozenset[str], str | None]:
    if photo.analysis_status != "done":
        return frozenset(), "ANALYSIS_NOT_READY"
    targets = photo.confirmed_member_ids & photo.active_member_ids
    # Role 3's policy: no_face OR no confirmed members requires the uploader.
    if photo.shot_type == "no_face" or not targets:
        if photo.uploader_member_id in photo.active_member_ids:
            return frozenset([photo.uploader_member_id]), None
        return frozenset(), "UPLOADER_LEFT"
    return targets, None


def invalidate_approvals(tx: EditTransaction) -> None:
    """Role 3 MUST call within the SAME transaction that changes subjects/members.

    Call on changed effective subject set, membership departure, or uncertainty.
    Invalidation is intentionally persistent: re-adding someone never revives votes.
    Reanalysis with unchanged confirmed subjects need not invalidate approvals.
    """
    tx.clear_approvals()


def _require_member(tx: EditTransaction, member_id: str) -> PhotoSnapshot:
    if tx.photo is None:
        raise EditError("PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.", 404)
    if member_id not in tx.photo.active_member_ids:
        raise EditError("ALBUM_ACCESS_DENIED", "이 앨범에 접근할 권한이 없습니다.", 403)
    return tx.photo


def _version_list(tx: EditTransaction, member_id: str, repository_mode: str) -> dict:
    photo = _require_member(tx, member_id)
    targets, blocked = approval_targets(photo)
    records, approvals = tx.edits(), tx.approvals()
    eligible = [edit for edit in records if targets and not blocked and targets <= approvals.get(edit.id, set())]
    final_id = max(eligible, key=lambda edit: edit.number).id if eligible else None
    versions = []
    for edit in sorted(records, key=lambda edit: edit.number, reverse=True):
        approved = approvals.get(edit.id, set()) & targets
        versions.append(dict(
            id=edit.id, photo_id=edit.photo_id, author_member_id=edit.author_member_id,
            parent_id=edit.parent_id, number=edit.number, created_at=edit.created_at,
            brightness=edit.settings.brightness, saturation=edit.settings.saturation,
            approval_count=len(approved), required_count=len(targets),
            required_member_ids=sorted(targets), approved_member_ids=sorted(approved),
            is_final=edit.id == final_id, can_approve=member_id in targets and not blocked,
            approved_by_me=member_id in approved, approval_blocked_reason=blocked,
            provider=photo.provider, mode=photo.mode, storage_mode=repository_mode,
            preview_url=f"/api/edits/{edit.id}/preview",
            download_url=f"/api/edits/{edit.id}/download"))
    return dict(photo_id=photo.id, versions=versions, final_edit_id=final_id,
                provider=photo.provider, mode=photo.mode, storage_mode=repository_mode)


_render_slot = BoundedSemaphore(1)
_logger = logging.getLogger(__name__)


class EditService:
    def __init__(self, repository: EditRepository, storage: EditStorage):
        self.repository, self.storage = repository, storage

    def list(self, photo_id: str, member_id: str) -> dict:
        with self.repository.transaction(photo_id) as tx:
            return _version_list(tx, member_id, self.repository.mode)

    def create(self, photo_id: str, member_id: str, settings: EditSettings,
               parent_id: str | None = None) -> dict:
        written_key = None
        try:
            # Acquire before DB lock: concurrent photos must not accumulate decoded images.
            with _render_slot, self.repository.transaction(photo_id) as tx:
                photo = _require_member(tx, member_id)
                records = tx.edits()
                if parent_id is not None and parent_id not in {edit.id for edit in records}:
                    raise EditError("INVALID_PARENT", "이 사진에 속한 이전 버전을 선택해 주세요.")
                number = max((edit.number for edit in records), default=0) + 1
                key = edit_key(photo, number)
                if key == photo.s3_key:
                    raise EditError("ORIGINAL_OVERWRITE", "원본 파일을 덮어쓸 수 없습니다.")
                with self.storage.open_original(photo) as source, TemporaryFile() as output:
                    render_edit(source, output, settings)
                    self.storage.write_edit(key, output)
                    written_key = key
                record = EditRecord(str(uuid4()), photo_id, member_id, parent_id, number,
                                    settings, datetime.now(timezone.utc).isoformat())
                tx.add_edit(record)
                result = next(row for row in _version_list(tx, member_id, self.repository.mode)["versions"] if row["id"] == record.id)
            return result
        except Exception as exc:
            if written_key is not None:
                try:
                    self.storage.delete_edit(written_key)
                except Exception:
                    _logger.exception("Edit rollback requires orphan cleanup: %s", written_key)
            if isinstance(exc, EditError):
                raise
            _logger.exception("Edit creation failed for photo %s", photo_id)
            raise EditError("EDIT_SAVE_FAILED", "보정본을 저장하지 못했습니다. 다시 시도해 주세요.", 503) from exc

    def _change_approval(self, edit_id: str, member_id: str, *, approve: bool) -> dict:
        photo_id = self.repository.photo_id_for_edit(edit_id)
        if photo_id is None:
            raise EditError("EDIT_NOT_FOUND", "보정 버전을 찾을 수 없습니다.", 404)
        with self.repository.transaction(photo_id) as tx:
            photo = _require_member(tx, member_id)
            if edit_id not in {edit.id for edit in tx.edits()}:
                raise EditError("EDIT_NOT_FOUND", "보정 버전을 찾을 수 없습니다.", 404)
            if approve:
                targets, blocked = approval_targets(photo)
                if blocked:
                    raise EditError("APPROVAL_BLOCKED", "등장 인물을 확인한 뒤 승인해 주세요.", 409)
                if member_id not in targets:
                    raise EditError("NOT_APPROVER", "이 사진의 승인 대상이 아닙니다.", 403)
                tx.add_approval(edit_id, member_id)
            else:
                # Revoking is allowed for any active album member's OWN vote only.
                tx.remove_approval(edit_id, member_id)
            return next(row for row in _version_list(tx, member_id, self.repository.mode)["versions"] if row["id"] == edit_id)

    def approve(self, edit_id: str, member_id: str) -> dict:
        return self._change_approval(edit_id, member_id, approve=True)

    def revoke(self, edit_id: str, member_id: str) -> dict:
        return self._change_approval(edit_id, member_id, approve=False)


class CreateEditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brightness: float = Field(ge=0.5, le=1.5, strict=True, allow_inf_nan=False)
    saturation: float = Field(ge=0.0, le=2.0, strict=True, allow_inf_nan=False)
    parent_id: UUID | None = None


class _EditRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await handler(request)
            except EditError as exc:
                return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message})
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"code": "INVALID_REQUEST", "message": "요청 값과 사진·버전 ID를 확인해 주세요."})
            except HTTPException as exc:
                code, message = {
                    401: ("SESSION_REQUIRED", "앨범에 먼저 참여해 주세요."),
                    403: ("ALBUM_ACCESS_DENIED", "이 앨범에 접근할 권한이 없습니다."),
                    404: ("NOT_FOUND", "요청한 항목을 찾을 수 없습니다."),
                }.get(exc.status_code, ("REQUEST_FAILED", "요청을 처리하지 못했습니다."))
                content = {"code": code, "message": message}
                if isinstance(exc.detail, dict) and {"code", "message"} <= exc.detail.keys():
                    content = {key: exc.detail[key] for key in ("code", "message", "details") if key in exc.detail}
                return JSONResponse(status_code=exc.status_code, headers=exc.headers, content=content)
            except Exception as exc:
                # Preserve Role 3's explicitly registered ApiError handler.
                # A generic Exception handler alone must not swallow our fallback.
                if any(cls in request.app.exception_handlers for cls in type(exc).__mro__
                       if cls not in (Exception, BaseException, object)):
                    raise
                _logger.exception("Edit API dependency failed")
                return JSONResponse(status_code=503, content={"code": "EDIT_SERVICE_UNAVAILABLE", "message": "잠시 후 다시 시도해 주세요."})

        return handle


def build_edit_router(service: EditService, current_member: Callable) -> APIRouter:
    """Inject a dependency that verifies the signed session and returns member UUID str.

    Include this router once; it already carries /api. Never accept actor IDs from
    request bodies. Synchronous routes keep Pillow and storage off the event loop.
    """
    router = APIRouter(prefix="/api", tags=["edits"], route_class=_EditRoute)

    @router.post("/photos/{photo_id}/edits", status_code=201)
    def create(photo_id: UUID, body: CreateEditBody, member_id: str = Depends(current_member)):
        return service.create(str(photo_id), member_id, EditSettings(body.brightness, body.saturation),
                              str(body.parent_id) if body.parent_id else None)

    @router.get("/photos/{photo_id}/edits")
    def versions(photo_id: UUID, member_id: str = Depends(current_member)):
        return service.list(str(photo_id), member_id)

    @router.post("/edits/{edit_id}/approve")
    def approve(edit_id: UUID, member_id: str = Depends(current_member)):
        return service.approve(str(edit_id), member_id)

    @router.delete("/edits/{edit_id}/approve")
    def revoke(edit_id: UUID, member_id: str = Depends(current_member)):
        return service.revoke(str(edit_id), member_id)

    return router

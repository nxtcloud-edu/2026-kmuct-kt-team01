from __future__ import annotations

import io
import os
import re
from datetime import datetime
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath

import boto3
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.app.config import Settings
from backend.app.errors import ApiError

Image.MAX_IMAGE_PIXELS = 25_000_000
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png"}
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def validate_key(key: str) -> str:
    if not key or "\x00" in key or "\\" in key or key.startswith("/"):
        raise ValueError("unsafe storage key")
    path = PurePosixPath(key)
    if any(part in {"", ".", ".."} or not _SAFE_SEGMENT.fullmatch(part) for part in path.parts):
        raise ValueError("unsafe storage key")
    return key


class Storage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def signed_url(self, key: str, expires: int = 300) -> str | None: ...


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*PurePosixPath(validate_key(key)).parts)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise ApiError(404, "OBJECT_NOT_FOUND", "사진 파일을 찾을 수 없습니다.") from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def signed_url(self, key: str, expires: int = 300) -> None:
        del key, expires
        return None


class S3Storage(Storage):
    def __init__(self, bucket: str, region: str = "us-east-1") -> None:
        self.bucket = bucket
        self.client = boto3.client("s3", region_name=region)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=validate_key(key),
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=validate_key(key))
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=validate_key(key))

    def signed_url(self, key: str, expires: int = 300) -> str:
        expires = max(1, min(int(expires), 300))
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": validate_key(key)},
            ExpiresIn=expires,
        )


def make_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        return S3Storage(settings.s3_bucket, settings.aws_region)
    return LocalStorage(settings.local_storage_path)


def read_upload(file_object: object) -> bytes:
    reader = getattr(file_object, "read")
    data = reader(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "파일당 최대 크기는 25MB입니다.")
    if not data:
        raise ApiError(400, "EMPTY_FILE", "빈 파일은 업로드할 수 없습니다.")
    return data


def normalize_image(
    data: bytes, mime: str | None
) -> tuple[bytes, bytes, int, int, datetime | None, str]:
    if mime not in ALLOWED_MIME:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "JPEG와 PNG만 업로드할 수 있습니다.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            captured_at = None
            # iPhone Portrait/버스트 사진은 종종 MPO(Multi Picture Object) 컨테이너로 저장된다.
            # 대표 이미지 자체는 정상 JPEG이므로(PIL이 그대로 열고 처리할 수 있다) JPEG로 취급한다.
            detected_format = "JPEG" if source.format == "MPO" else source.format
            detected_mime = Image.MIME.get(detected_format or "")
            if detected_mime not in ALLOWED_MIME:
                raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "JPEG와 PNG만 업로드할 수 있습니다.")
            captured_value = source.getexif().get(36867) or source.getexif().get(306)
            if isinstance(captured_value, str):
                try:
                    captured_at = datetime.strptime(captured_value, "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass
            image = ImageOps.exif_transpose(source)
            original_width, original_height = image.size
            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                alpha = image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            original_buffer = io.BytesIO()
            image.save(original_buffer, format="JPEG", quality=85, optimize=True)
            thumb = image.copy()
            thumb.thumbnail((400, 400), Image.Resampling.LANCZOS)
            thumb_buffer = io.BytesIO()
            thumb.save(thumb_buffer, format="JPEG", quality=82, optimize=True)
            return (
                original_buffer.getvalue(),
                thumb_buffer.getvalue(),
                original_width,
                original_height,
                captured_at,
                detected_mime,
            )
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ApiError(400, "INVALID_IMAGE", "손상되었거나 너무 큰 이미지입니다.") from exc


def photo_keys(album_id: str, photo_id: str, mime: str = "image/jpeg") -> tuple[str, str]:
    prefix = f"albums/{album_id}/photos/{photo_id}"
    extension = "png" if mime == "image/png" else "jpg"
    return f"{prefix}/original.{extension}", f"{prefix}/thumb.jpg"

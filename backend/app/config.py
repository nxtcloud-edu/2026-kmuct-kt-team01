from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./zzik.db"
    session_secret: str = "local-development-secret-change-me"
    session_cookie_name: str = "zzik_session"
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: Path = Path("storage")
    aws_region: Literal["us-east-1"] = "us-east-1"
    s3_bucket: str | None = None
    signed_url_seconds: int = Field(default=300, ge=1, le=300)


@lru_cache
def get_settings() -> Settings:
    return Settings()

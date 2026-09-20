from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI

from backend.app.api import current_member, router
from backend.app.auth import SessionCodec
from backend.app.config import Settings, get_settings
from backend.app.database import make_engine, make_session_factory
from backend.app.edit_adapters import BackendEditStorage, SqlAlchemyEditRepository
from backend.app.edits import EditService, build_edit_router
from backend.app.errors import install_error_handlers
from backend.app.models import Member
from backend.app.storage import make_storage


def current_member_id(
    member: Annotated[Member, Depends(current_member)],
) -> str:
    return member.id


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="ZZIK API", version="0.1.0")
    app.state.settings = resolved
    app.state.engine = make_engine(resolved.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.session_codec = SessionCodec(resolved.session_secret)
    app.state.storage = make_storage(resolved)
    app.state.edit_repository = SqlAlchemyEditRepository(app.state.session_factory)
    app.state.edit_service = EditService(
        app.state.edit_repository, BackendEditStorage(app.state.storage)
    )
    install_error_handlers(app)
    app.include_router(router)
    app.include_router(build_edit_router(app.state.edit_service, current_member_id))
    return app


app = create_app()

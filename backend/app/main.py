from __future__ import annotations

from fastapi import FastAPI

from backend.app.api import router
from backend.app.auth import SessionCodec
from backend.app.config import Settings, get_settings
from backend.app.database import make_engine, make_session_factory
from backend.app.errors import install_error_handlers
from backend.app.storage import make_storage


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="ZZIK API", version="0.1.0")
    app.state.settings = resolved
    app.state.engine = make_engine(resolved.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.session_codec = SessionCodec(resolved.session_secret)
    app.state.storage = make_storage(resolved)
    install_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()

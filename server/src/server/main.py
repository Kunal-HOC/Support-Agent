"""FastAPI application factory.

Run with ``uv run support-agent`` (prints config errors without a traceback) or
``uvicorn server.main:create_app --factory``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import Settings, load_settings
from core.db import create_engine, create_session_factory
from core.logging import configure_logging
from server.api.health import router as health_router
from server.errors import register_error_handlers
from server.request_id import RequestIdMiddleware

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Loads settings from the environment if none are given."""
    if settings is None:
        settings = load_settings()
    configure_logging(settings.LOG_LEVEL)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        logger.info("Starting Support Agent server (APP_ENV=%s)", settings.APP_ENV)
        try:
            yield
        finally:
            await engine.dispose()

    docs_enabled = settings.APP_ENV != "production"
    app = FastAPI(
        title="Support Agent",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    return app

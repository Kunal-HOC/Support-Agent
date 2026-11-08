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
from core.ingestion.embedding import Embedder, OpenAIEmbedder
from core.ingestion.pipeline import IngestionContext
from core.ingestion.service import fail_interrupted_versions
from core.ingestion.storage import Storage
from core.ingestion.tokenizer import TiktokenTokenizer, Tokenizer
from core.logging import configure_logging
from server.api.documents import router as documents_router
from server.api.health import router as health_router
from server.errors import register_error_handlers
from server.request_id import RequestIdMiddleware

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    embedder: Embedder | None = None,
    tokenizer: Tokenizer | None = None,
) -> FastAPI:
    """Build the app.

    Loads settings from the environment if none are given. ``embedder`` and
    ``tokenizer`` replace the ones built from settings (tests pass fakes).
    """
    if settings is None:
        settings = load_settings()
    configure_logging(settings.LOG_LEVEL)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        active_embedder = embedder or OpenAIEmbedder.from_settings(settings)
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.ingestion = IngestionContext(
            settings=settings,
            session_factory=session_factory,
            storage=Storage(settings.UPLOAD_DIR),
            embedder=active_embedder,
            tokenizer=tokenizer or TiktokenTokenizer(settings.TOKENIZER_ENCODING),
        )
        logger.info("Starting Support Agent server (APP_ENV=%s)", settings.APP_ENV)
        await _fail_interrupted(app)
        try:
            yield
        finally:
            await active_embedder.aclose()
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
    app.include_router(documents_router)
    return app


async def _fail_interrupted(app: FastAPI) -> None:
    """Versions left pending by a previous process can never finish: fail them."""
    try:
        async with app.state.session_factory() as session:
            count = await fail_interrupted_versions(session)
    except Exception as exc:  # the DB may be down at startup; /health reports that
        logger.warning("Could not check for interrupted ingestions: %s", type(exc).__name__)
        return
    if count:
        logger.warning("Marked %d interrupted version(s) as failed", count)

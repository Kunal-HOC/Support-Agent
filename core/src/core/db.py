"""Async database engine, sessions and connectivity check."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import Settings

logger = logging.getLogger(__name__)

# Upper bound, in seconds, for connecting and for the health-check query.
DB_CHECK_TIMEOUT_SECONDS = 2


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the async engine. No connection is made until first use."""
    return create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"connect_timeout": DB_CHECK_TIMEOUT_SECONDS},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a session that is closed afterwards (for use as a dependency)."""
    async with factory() as session:
        yield session


async def is_database_reachable(engine: AsyncEngine) -> bool:
    """Return True if ``SELECT 1`` succeeds within the timeout."""
    try:
        async with asyncio.timeout(DB_CHECK_TIMEOUT_SECONDS):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:  # any failure means "unreachable"
        logger.warning("Database check failed: %s", type(exc).__name__)
        return False
    return True

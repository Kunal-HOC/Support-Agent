"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.db import session_scope


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an ``AsyncSession`` for one request."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async for session in session_scope(factory):
        yield session

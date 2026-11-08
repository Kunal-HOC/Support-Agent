"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an ``AsyncSession`` for one request; it is closed even if the request fails."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session

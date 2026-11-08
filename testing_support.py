"""Helpers shared by the test suites (imported by conftest.py and tests)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.config import Settings

SETTING_KEYS = ("DATABASE_URL", "EMBEDDING_DIMENSION", "APP_ENV", "LOG_LEVEL")
TEST_DATABASE_URL_VAR = "TEST_DATABASE_URL"

# Port 1 on localhost has nothing listening, so connections fail fast.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://user:pass@127.0.0.1:1/unreachable"

VALID_VALUES: dict[str, Any] = {
    "DATABASE_URL": UNREACHABLE_DATABASE_URL,
    "EMBEDDING_DIMENSION": 8,
    "APP_ENV": "test",
    "LOG_LEVEL": "WARNING",
}

MakeSettings = Callable[..., Settings]


@asynccontextmanager
async def running_app(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Run the app's lifespan and yield an HTTP client bound to it."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client

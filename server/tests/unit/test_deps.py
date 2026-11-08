from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.deps import get_session
from server.main import create_app
from testing_support import MakeSettings, running_app


async def test_get_session_yields_an_async_session(make_settings: MakeSettings) -> None:
    app = create_app(make_settings())

    @app.get("/session-type")
    async def session_type(session: Annotated[AsyncSession, Depends(get_session)]) -> str:
        return type(session).__name__

    async with running_app(app) as client:
        response = await client.get("/session-type")
    assert response.json() == "AsyncSession"

"""GET /health: app status and database reachability."""

from __future__ import annotations

from importlib.metadata import version
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from core.db import is_database_reachable

router = APIRouter()

DISTRIBUTION_NAME = "support-agent-server"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["reachable", "unreachable"]
    version: str


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    engine: AsyncEngine = request.app.state.engine
    reachable = await is_database_reachable(engine)
    return HealthResponse(
        status="ok",
        database="reachable" if reachable else "unreachable",
        version=version(DISTRIBUTION_NAME),
    )

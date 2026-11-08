from __future__ import annotations

import pytest

from server.main import create_app
from testing_support import MakeSettings, running_app

pytestmark = pytest.mark.db


async def test_health_reports_reachable_database(
    make_settings: MakeSettings, test_database_url: str
) -> None:
    app = create_app(make_settings(DATABASE_URL=test_database_url))
    async with running_app(app) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable", "version": "0.1.0"}

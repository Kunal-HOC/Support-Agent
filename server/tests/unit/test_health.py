from __future__ import annotations

from server.main import create_app
from testing_support import MakeSettings, running_app


async def test_health_reports_unreachable_database(make_settings: MakeSettings) -> None:
    app = create_app(make_settings())
    async with running_app(app) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "unreachable", "version": "0.1.0"}
    assert response.headers["X-Request-ID"]

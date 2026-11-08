from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI

from server.errors import INTERNAL_ERROR_MESSAGE
from server.main import create_app
from testing_support import MakeSettings, running_app

ERROR_KEYS = {"code", "message", "details", "request_id"}


@pytest.fixture
def app(make_settings: MakeSettings) -> FastAPI:
    app = create_app(make_settings())

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    return app


async def test_not_found_uses_error_model(app: FastAPI) -> None:
    async with running_app(app) as client:
        response = await client.get("/does-not-exist")
    body = response.json()
    assert response.status_code == 404
    assert set(body) == ERROR_KEYS
    assert body["code"] == "http_error"
    assert body["request_id"] == response.headers["X-Request-ID"]


async def test_validation_error_uses_error_model(app: FastAPI) -> None:
    async with running_app(app) as client:
        response = await client.get("/items/not-a-number")
    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "validation_error"
    assert body["details"][0]["loc"] == ["path", "item_id"]
    assert body["request_id"] == response.headers["X-Request-ID"]


async def test_unhandled_error_hides_details(app: FastAPI) -> None:
    async with running_app(app) as client:
        response = await client.get("/boom")
    body = response.json()
    assert response.status_code == 500
    assert body == {
        "code": "internal_error",
        "message": INTERNAL_ERROR_MESSAGE,
        "details": None,
        "request_id": response.headers["X-Request-ID"],
    }
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text


async def test_incoming_request_id_is_reused(app: FastAPI) -> None:
    async with running_app(app) as client:
        response = await client.get("/does-not-exist", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"
    assert response.json()["request_id"] == "abc-123"


async def test_unsafe_request_id_is_replaced(app: FastAPI) -> None:
    async with running_app(app) as client:
        response = await client.get("/does-not-exist", headers={"X-Request-ID": "bad id\twith tab"})
    uuid.UUID(response.headers["X-Request-ID"])  # a fresh UUID4 was generated


async def test_docs_disabled_in_production(make_settings: MakeSettings) -> None:
    app = create_app(make_settings(APP_ENV="production"))
    async with running_app(app) as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404


async def test_docs_enabled_outside_production(make_settings: MakeSettings) -> None:
    app = create_app(make_settings(APP_ENV="development"))
    async with running_app(app) as client:
        assert (await client.get("/openapi.json")).status_code == 200

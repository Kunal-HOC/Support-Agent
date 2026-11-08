"""Upload checks that happen before any database access."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from server.main import create_app
from testing_support import FakeEmbedder, FakeTokenizer, MakeSettings, running_app, sop_fixture


@pytest.fixture
def app(make_settings: MakeSettings) -> FastAPI:
    return create_app(
        make_settings(MAX_UPLOAD_BYTES=50_000), embedder=FakeEmbedder(8), tokenizer=FakeTokenizer()
    )


def _form(**fields: str) -> dict[str, str]:
    return {"title": "Desk booking", "category": "Facilities", **fields}


async def test_missing_title_is_422(app: FastAPI) -> None:
    async with running_app(app) as client:
        files = {"file": ("sop.md", sop_fixture(".md").read_bytes())}
        response = await client.post("/documents", data={"category": "IT"}, files=files)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_unknown_category_is_422_and_lists_allowed(app: FastAPI) -> None:
    async with running_app(app) as client:
        files = {"file": ("sop.md", sop_fixture(".md").read_bytes())}
        response = await client.post("/documents", data=_form(category="Legal"), files=files)
    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "validation_error"
    assert body["details"]["allowed_categories"] == ["Facilities", "IT", "HR"]


@pytest.mark.parametrize("title", ["   ", "x" * 201])
async def test_bad_title_is_422(app: FastAPI, title: str) -> None:
    async with running_app(app) as client:
        files = {"file": ("sop.md", sop_fixture(".md").read_bytes())}
        response = await client.post("/documents", data=_form(title=title), files=files)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("notes.txt", b"plain text"),
        ("sop.pdf", b"not a pdf at all"),
        ("sop.docx", b"%PDF-1.4 pretending"),
        ("image.png", b"\x89PNG\r\n\x1a\n"),
    ],
)
async def test_unsupported_type_is_415(
    app: FastAPI, upload_dir: Path, filename: str, content: bytes
) -> None:
    async with running_app(app) as client:
        response = await client.post(
            "/documents", data=_form(), files={"file": (filename, content)}
        )
    body = response.json()
    assert response.status_code == 415
    assert body["code"] == "unsupported_file_type"
    assert body["details"] == {"allowed_extensions": [".pdf", ".docx", ".md"]}
    assert not any(p.is_file() for p in upload_dir.rglob("*"))  # nothing kept


async def test_oversize_file_is_413(app: FastAPI, upload_dir: Path) -> None:
    async with running_app(app) as client:
        content = b"# Big\n\n" + b"word " * 20_000
        response = await client.post(
            "/documents", data=_form(), files={"file": ("big.md", content)}
        )
    body = response.json()
    assert response.status_code == 413
    assert body["code"] == "file_too_large"
    assert body["details"] == {"max_upload_bytes": 50_000}
    assert not any(p.is_file() for p in upload_dir.rglob("*"))

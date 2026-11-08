"""End-to-end ingestion through the API on a real PostgreSQL + pgvector database.

Uses the real tiktoken tokenizer (cl100k_base from fixtures) and a deterministic
fake embedder. BackgroundTasks finish before the test client returns.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import AsyncClient, Response

from core.config import Settings
from core.ingestion.errors import EmbeddingError
from core.ingestion.tokenizer import TiktokenTokenizer
from server.main import create_app
from testing_support import (
    EXPECTED_PDF_PAGES,
    EXPECTED_SECTION_PATHS,
    FakeEmbedder,
    MakeSettings,
    running_app,
    sop_fixture,
)

pytestmark = pytest.mark.db

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "core" / "alembic.ini"
DIMENSION = 8
MAX_TOKENS = 40
OVERLAP = 8
FORMATS = [".pdf", ".docx", ".md"]


@pytest.fixture
def db_settings(make_settings: MakeSettings, test_database_url: str) -> Callable[..., Settings]:
    def _make(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "DATABASE_URL": test_database_url,
            "EMBEDDING_DIMENSION": DIMENSION,
            "CHUNK_MAX_TOKENS": MAX_TOKENS,
            "CHUNK_OVERLAP_TOKENS": OVERLAP,
            "EMBEDDING_BATCH_SIZE": 4,
        }
        return make_settings(**{**values, **overrides})

    return _make


@pytest.fixture
def migrated(db_settings: Callable[..., Settings]) -> Iterator[sa.Engine]:
    settings = db_settings()
    config = Config(str(ALEMBIC_INI))
    config.attributes["settings"] = settings
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = sa.create_engine(settings.DATABASE_URL)
    yield engine
    engine.dispose()
    command.downgrade(config, "base")


AppFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture
def client_for(
    migrated: sa.Engine, db_settings: Callable[..., Settings], tiktoken_cache: Path
) -> AppFactory:
    """``async with client_for(embedder=..., **settings_overrides) as client``."""

    def _client(embedder: FakeEmbedder | None = None, **overrides: Any) -> Any:
        settings = db_settings(**overrides)
        app: FastAPI = create_app(
            settings,
            embedder=embedder or FakeEmbedder(DIMENSION),
            tokenizer=TiktokenTokenizer("cl100k_base"),
        )
        return running_app(app)

    return _client


async def _post(
    client: AsyncClient,
    content: bytes,
    filename: str,
    title: str = "Workspace booking",
    category: str = "Facilities",
) -> Response:
    return await client.post(
        "/documents",
        data={"title": title, "category": category},
        files={"file": (filename, content)},
    )


async def _put(client: AsyncClient, document_id: str, content: bytes, filename: str) -> Response:
    return await client.put(f"/documents/{document_id}", files={"file": (filename, content)})


def _chunks(engine: sa.Engine, document_id: str) -> list[sa.Row[Any]]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                sa.text(
                    "SELECT version, chunk_index, section_path, page, is_active, token_count, "
                    "content, content_tsv IS NOT NULL AS has_tsv, vector_dims(embedding) AS dims "
                    "FROM chunks WHERE document_id = :d ORDER BY version, chunk_index"
                ),
                {"d": document_id},
            )
        )


def _changed_markdown() -> bytes:
    return sop_fixture(".md").read_bytes() + b"\n## 6. Review\n\nThis SOP is reviewed yearly.\n"


@pytest.mark.parametrize("extension", FORMATS)
@pytest.mark.parametrize("strategy", ["heading", "fixed"])
async def test_fixture_indexes_in_every_format_and_strategy(
    client_for: AppFactory, migrated: sa.Engine, upload_dir: Path, extension: str, strategy: str
) -> None:
    content = sop_fixture(extension).read_bytes()
    async with client_for(CHUNKING_STRATEGY=strategy) as client:
        accepted = await _post(client, content, f"booking{extension}")
        assert accepted.status_code == 202
        body = accepted.json()
        assert body["version"] == 1 and body["status"] == "pending"
        detail = (await client.get(f"/documents/{body['document_id']}")).json()

    assert detail["versions"][0]["status"] == "indexed", detail
    assert detail["active_version"] == 1
    assert detail["chunk_count"] > 0
    paths = [tuple(p) for p in detail["section_paths"]]
    if strategy == "heading":
        assert paths == EXPECTED_SECTION_PATHS
    else:
        assert set(paths) <= set(EXPECTED_SECTION_PATHS)

    chunks = _chunks(migrated, body["document_id"])
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.is_active and c.has_tsv and c.dims == DIMENSION for c in chunks)
    assert all(0 < c.token_count <= MAX_TOKENS for c in chunks)
    if extension == ".pdf" and strategy == "heading":
        first_page: dict[tuple[str, ...], int | None] = {}
        for chunk in chunks:
            first_page.setdefault(tuple(chunk.section_path), chunk.page)
        assert list(first_page.values()) == EXPECTED_PDF_PAGES
    elif extension != ".pdf":
        assert all(c.page is None for c in chunks)

    stored = upload_dir / body["document_id"] / "v1" / f"original{extension}"
    assert stored.read_bytes() == content


async def test_list_filters_and_fields(client_for: AppFactory) -> None:
    async with client_for() as client:
        md = (await _post(client, sop_fixture(".md").read_bytes(), "a.md", category="IT")).json()
        await _post(client, sop_fixture(".docx").read_bytes(), "b.docx", category="HR")
        everything = (await client.get("/documents")).json()
        it_only = (await client.get("/documents", params={"category": "IT"})).json()
        failed = (await client.get("/documents", params={"status": "failed"})).json()
        bad = await client.get("/documents", params={"status": "weird"})
    assert len(everything) == 2
    assert set(everything[0]) == {
        "id",
        "title",
        "category",
        "version",
        "status",
        "chunk_count",
        "updated_at",
    }
    assert [d["id"] for d in it_only] == [md["document_id"]]
    assert it_only[0]["status"] == "indexed" and it_only[0]["chunk_count"] > 0
    assert failed == []
    assert bad.status_code == 422


async def test_reupload_bumps_version_and_switches_active_chunks(
    client_for: AppFactory, migrated: sa.Engine
) -> None:
    async with client_for() as client:
        first = (await _post(client, sop_fixture(".md").read_bytes(), "sop.md")).json()
        doc_id = first["document_id"]
        second = await _put(client, doc_id, _changed_markdown(), "sop.md")
        detail = (await client.get(f"/documents/{doc_id}")).json()
    assert second.status_code == 202
    assert second.json() == {"document_id": doc_id, "version": 2, "status": "pending"}
    assert [v["status"] for v in detail["versions"]] == ["indexed", "indexed"]
    assert detail["active_version"] == 2
    assert ["Workspace Booking Procedure", "6. Review"] in detail["section_paths"]

    chunks = _chunks(migrated, doc_id)
    old = [c for c in chunks if c.version == 1]
    new = [c for c in chunks if c.version == 2]
    assert old and not any(c.is_active for c in old)  # kept, but inactive
    assert new and all(c.is_active for c in new)


async def test_failed_new_version_leaves_previous_active(
    client_for: AppFactory, migrated: sa.Engine
) -> None:
    async with client_for() as client:
        first = (await _post(client, sop_fixture(".md").read_bytes(), "sop.md")).json()
        doc_id = first["document_id"]
        await _put(client, doc_id, b"# Only a heading\n", "sop.md")
        detail = (await client.get(f"/documents/{doc_id}")).json()
        listed = (await client.get("/documents")).json()
    assert [v["status"] for v in detail["versions"]] == ["indexed", "failed"]
    assert detail["versions"][1]["failure_reason"] == "no extractable text"
    assert detail["active_version"] == 1
    assert all(c.is_active for c in _chunks(migrated, doc_id))
    assert listed[0]["version"] == 2 and listed[0]["status"] == "failed"


async def test_identical_upload_is_409(client_for: AppFactory, upload_dir: Path) -> None:
    content = sop_fixture(".pdf").read_bytes()
    async with client_for() as client:
        first = (await _post(client, content, "a.pdf")).json()
        again = await _post(client, content, "renamed.pdf", title="Other")
        same_doc = await _put(client, first["document_id"], content, "a.pdf")
        listed = (await client.get("/documents")).json()
    for response in (again, same_doc):
        body = response.json()
        assert response.status_code == 409
        assert body["code"] == "duplicate_content"
        assert body["details"] == {"document_id": first["document_id"], "version": 1}
        assert first["document_id"] in body["message"]
    assert len(listed) == 1
    assert not list((upload_dir / ".incoming").iterdir())


async def test_failed_content_can_be_uploaded_again(client_for: AppFactory) -> None:
    content = sop_fixture(".md").read_bytes()
    async with client_for(embedder=FakeEmbedder(DIMENSION, error=EmbeddingError("down"))) as client:
        first = (await _post(client, content, "a.md")).json()
    async with client_for() as client:
        retry = await _post(client, content, "a.md")
        detail = (await client.get(f"/documents/{first['document_id']}")).json()
    assert detail["versions"][0]["failure_reason"] == "embedding failed: down"
    assert retry.status_code == 202


async def test_put_while_pending_is_409(client_for: AppFactory, migrated: sa.Engine) -> None:
    async with client_for() as client:
        first = (await _post(client, sop_fixture(".md").read_bytes(), "a.md")).json()
        with migrated.begin() as conn:
            conn.execute(
                sa.text("UPDATE document_versions SET status = 'pending' WHERE document_id = :d"),
                {"d": first["document_id"]},
            )
        response = await _put(client, first["document_id"], _changed_markdown(), "a.md")
    assert response.status_code == 409
    assert response.json()["code"] == "version_pending"


async def test_unknown_document_is_404(client_for: AppFactory) -> None:
    missing = str(uuid.uuid4())
    async with client_for() as client:
        responses = [
            await client.get(f"/documents/{missing}"),
            await _put(client, missing, sop_fixture(".md").read_bytes(), "a.md"),
            await client.delete(f"/documents/{missing}"),
        ]
    for response in responses:
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


async def test_delete_removes_rows_and_files(
    client_for: AppFactory, migrated: sa.Engine, upload_dir: Path
) -> None:
    async with client_for() as client:
        first = (await _post(client, sop_fixture(".md").read_bytes(), "a.md")).json()
        doc_id = first["document_id"]
        await _put(client, doc_id, _changed_markdown(), "a.md")
        deleted = await client.delete(f"/documents/{doc_id}")
        after = await client.get(f"/documents/{doc_id}")
    assert deleted.status_code == 204
    assert after.status_code == 404
    with migrated.connect() as conn:
        for table in ("documents", "document_versions", "chunks"):
            assert conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
    assert not (upload_dir / doc_id).exists()


async def _failure_reason(client: AsyncClient, content: bytes, filename: str) -> str:
    accepted = (await _post(client, content, filename)).json()
    detail = (await client.get(f"/documents/{accepted['document_id']}")).json()
    assert detail["versions"][0]["status"] == "failed"
    assert detail["active_version"] is None
    reason: str = detail["versions"][0]["failure_reason"]
    return reason


async def test_page_limit_fails_version(client_for: AppFactory) -> None:
    async with client_for(MAX_PAGES=1) as client:
        reason = await _failure_reason(client, sop_fixture(".pdf").read_bytes(), "a.pdf")
    assert reason == "page limit exceeded"


async def test_no_text_fails_version(client_for: AppFactory) -> None:
    async with client_for() as client:
        reason = await _failure_reason(client, b"   \n", "blank.md")
    assert reason == "no extractable text"


async def test_parse_error_fails_version(client_for: AppFactory) -> None:
    async with client_for() as client:
        reason = await _failure_reason(client, b"%PDF-1.4\ngarbage", "broken.pdf")
    assert reason.startswith("parse error: ")


async def test_dimension_mismatch_fails_version(client_for: AppFactory) -> None:
    async with client_for(embedder=FakeEmbedder(DIMENSION - 3)) as client:
        reason = await _failure_reason(client, sop_fixture(".md").read_bytes(), "a.md")
    assert reason == f"embedding dimension mismatch: expected {DIMENSION}, got {DIMENSION - 3}"


async def test_embeddings_are_batched(client_for: AppFactory) -> None:
    embedder = FakeEmbedder(DIMENSION)
    async with client_for(embedder=embedder, EMBEDDING_BATCH_SIZE=2) as client:
        await _post(client, sop_fixture(".md").read_bytes(), "a.md")
    assert len(embedder.batches) > 1
    assert all(1 <= len(batch) <= 2 for batch in embedder.batches)


async def test_startup_fails_interrupted_versions(
    client_for: AppFactory, migrated: sa.Engine
) -> None:
    async with client_for() as client:
        first = (await _post(client, sop_fixture(".md").read_bytes(), "a.md")).json()
    with migrated.begin() as conn:
        conn.execute(sa.text("UPDATE document_versions SET status = 'pending'"))
    async with client_for() as client:
        detail = (await client.get(f"/documents/{first['document_id']}")).json()
    assert detail["versions"][0]["status"] == "failed"
    assert detail["versions"][0]["failure_reason"] == "interrupted by server restart"

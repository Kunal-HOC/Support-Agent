"""Migrations against a real PostgreSQL + pgvector database (TEST_DATABASE_URL)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from core.config import Settings
from core.models import Base
from testing_support import MakeSettings

pytestmark = pytest.mark.db

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
TEST_DIMENSION = 8
M1_TABLES = {"documents", "document_versions", "chunks", "threads", "reviews", "feedback"}


@pytest.fixture
def settings(make_settings: MakeSettings, test_database_url: str) -> Settings:
    return make_settings(DATABASE_URL=test_database_url, EMBEDDING_DIMENSION=TEST_DIMENSION)


@pytest.fixture
def alembic_config(settings: Settings) -> Iterator[Config]:
    config = Config(str(ALEMBIC_INI))
    config.attributes["settings"] = settings
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")  # start from an empty database
    yield config
    command.downgrade(config, "base")  # leave it empty


@pytest.fixture
def engine(settings: Settings) -> Iterator[sa.Engine]:
    engine = sa.create_engine(settings.DATABASE_URL)
    yield engine
    engine.dispose()


def _tables(engine: sa.Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names()) - {"alembic_version"}


def _has_vector_extension(engine: sa.Engine) -> bool:
    with engine.connect() as conn:
        query = sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        return conn.execute(query).first() is not None


def _index_defs(engine: sa.Engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'chunks'")
        )
        return {name: definition for name, definition in rows}


def test_upgrade_downgrade_upgrade(alembic_config: Config, engine: sa.Engine) -> None:
    command.upgrade(alembic_config, "head")
    assert _tables(engine) == M1_TABLES
    assert _has_vector_extension(engine)

    command.downgrade(alembic_config, "base")
    assert _tables(engine) == set()
    assert not _has_vector_extension(engine)

    command.upgrade(alembic_config, "head")
    assert _tables(engine) == M1_TABLES


def test_chunks_schema(alembic_config: Config, engine: sa.Engine) -> None:
    command.upgrade(alembic_config, "head")

    with engine.connect() as conn:
        embedding_type = conn.execute(
            sa.text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            )
        ).scalar_one()
    assert embedding_type == f"vector({TEST_DIMENSION})"

    indexes = _index_defs(engine)
    assert "USING hnsw (embedding vector_cosine_ops)" in indexes["ix_chunks_embedding_hnsw"]
    assert "USING gin (content_tsv)" in indexes["ix_chunks_content_tsv_gin"]
    assert "ix_chunks_document_version_id" in indexes

    columns = {c["name"] for c in sa.inspect(engine).get_columns("chunks")}
    assert {"document_id", "version", "section_path", "page", "chunk_index"} <= columns


def test_chunk_insert_fills_tsvector(alembic_config: Config, engine: sa.Engine) -> None:
    command.upgrade(alembic_config, "head")
    vector_literal = "[" + ",".join(["0.1"] * TEST_DIMENSION) + "]"

    with engine.begin() as conn:
        document_id = conn.execute(
            sa.text("INSERT INTO documents (title, category) VALUES ('Sample', 'IT') RETURNING id")
        ).scalar_one()
        version_id = conn.execute(
            sa.text(
                "INSERT INTO document_versions (document_id, version, content_sha256, "
                "file_size_bytes, storage_path, source_filename, content_type, status) "
                "VALUES (:doc, 1, repeat('a', 64), 10, 'placeholder/path', 'sample.md', "
                "'text/markdown', 'indexed') RETURNING id"
            ),
            {"doc": document_id},
        ).scalar_one()
        tsv = conn.execute(
            sa.text(
                "INSERT INTO chunks (document_id, document_version_id, version, chunk_index, "
                "section_path, page, content, embedding, token_count) "
                "VALUES (:doc, :ver, 1, 0, ARRAY['Intro'], NULL, 'Refunds are processed', "
                "CAST(:emb AS vector), 3) RETURNING content_tsv::text"
            ),
            {"doc": document_id, "ver": version_id, "emb": vector_literal},
        ).scalar_one()
    assert "refund" in tsv


def test_wrong_embedding_dimension_is_rejected(alembic_config: Config, engine: sa.Engine) -> None:
    command.upgrade(alembic_config, "head")
    with pytest.raises(sa.exc.DataError), engine.connect() as conn:
        conn.execute(sa.text("SELECT CAST('[1,2,3]' AS vector(8))"))


def _compare_type(
    context: MigrationContext,
    inspected_column: dict[str, Any],
    metadata_column: sa.Column[Any],
    inspected_type: sa.types.TypeEngine[Any],
    metadata_type: sa.types.TypeEngine[Any],
) -> bool | None:
    # The model's Vector() has no dimension on purpose; the DB has vector(N).
    if metadata_column.name == "embedding":
        return False
    return None  # default comparison for everything else


def test_models_match_migrated_database(alembic_config: Config, engine: sa.Engine) -> None:
    command.upgrade(alembic_config, "head")
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": _compare_type})
        diff = compare_metadata(context, Base.metadata)
    assert diff == []


def test_0002_downgrade_keeps_document_file_metadata(
    alembic_config: Config, engine: sa.Engine
) -> None:
    command.upgrade(alembic_config, "head")
    with engine.begin() as conn:
        document_id = conn.execute(
            sa.text("INSERT INTO documents (title, category) VALUES ('Doc', 'IT') RETURNING id")
        ).scalar_one()
        for version, name in ((1, "old.md"), (2, "new.pdf")):
            conn.execute(
                sa.text(
                    "INSERT INTO document_versions (document_id, version, content_sha256, "
                    "file_size_bytes, storage_path, source_filename, content_type, status) "
                    "VALUES (:doc, :v, repeat('b', 64), 1, 'p', :name, 'x/y', 'failed')"
                ),
                {"doc": document_id, "v": version, "name": name},
            )

    command.downgrade(alembic_config, "0001_foundation")
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT source_filename, status FROM documents WHERE id = :id"),
            {"id": document_id},
        ).one()
    assert tuple(row) == ("new.pdf", "active")


def test_0002_upgrade_copies_file_metadata_to_versions(
    alembic_config: Config, engine: sa.Engine
) -> None:
    # 0002 adds documents.category NOT NULL with no value to fill it from, so it
    # can only upgrade an empty documents table (M1 never writes documents).
    command.upgrade(alembic_config, "0001_foundation")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (title, source_filename, content_type, status) "
                "VALUES ('Doc', 'a.md', 'text/markdown', 'active')"
            )
        )
    with pytest.raises(sa.exc.IntegrityError, match="category"):
        command.upgrade(alembic_config, "head")
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM documents"))
    command.upgrade(alembic_config, "head")
    assert _tables(engine) == M1_TABLES

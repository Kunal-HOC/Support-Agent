"""Foundation: enable pgvector and create the M1 tables.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-11-08

The embedding dimension is read from the EMBEDDING_DIMENSION setting when this
migration runs and is then fixed in the database. Changing it later needs a
new migration.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import context, op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from core.config import Settings
from core.models import TSVECTOR_EXPRESSION

revision: str = "0001_foundation"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _embedding_dimension() -> int:
    settings = context.config.attributes["settings"]
    assert isinstance(settings, Settings)
    return settings.EMBEDDING_DIMENSION


def _uuid_pk() -> sa.Column[uuid.UUID]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.func.gen_random_uuid(),
        nullable=False,
    )


def _ts(name: str, *, nullable: bool = False) -> sa.Column[datetime]:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        _uuid_pk(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("status IN ('active', 'archived')", name=op.f("ck_documents_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )

    op.create_table(
        "document_versions",
        _uuid_pk(),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.CHAR(64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint("version >= 1", name=op.f("ck_document_versions_version_positive")),
        sa.CheckConstraint(
            "status IN ('pending', 'indexed', 'failed')", name=op.f("ck_document_versions_status")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "document_id", "version", name=op.f("uq_document_versions_document_id_version")
        ),
    )

    op.create_table(
        "chunks",
        _uuid_pk(),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_path", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(_embedding_dimension()), nullable=False),
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(TSVECTOR_EXPRESSION, persisted=True),
            nullable=True,
        ),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_chunks_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name=op.f("uq_chunks_document_version_id_chunk_index"),
        ),
    )
    op.create_index(
        op.f("ix_chunks_embedding_hnsw"),
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        op.f("ix_chunks_content_tsv_gin"), "chunks", ["content_tsv"], postgresql_using="gin"
    )
    op.create_index(op.f("ix_chunks_document_version_id"), "chunks", ["document_version_id"])

    op.create_table(
        "threads",
        _uuid_pk(),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_threads")),
    )

    op.create_table(
        "reviews",
        _uuid_pk(),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_answer", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.Text(), nullable=True),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("decided_at", nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'edited', 'rejected')",
            name=op.f("ck_reviews_status"),
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["threads.id"],
            name=op.f("fk_reviews_thread_id_threads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
    )

    op.create_table(
        "feedback",
        _uuid_pk(),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint("rating IN (-1, 1)", name=op.f("ck_feedback_rating")),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["threads.id"],
            name=op.f("fk_feedback_thread_id_threads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_feedback_review_id_reviews"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("reviews")
    op.drop_table("threads")
    op.drop_index("ix_chunks_document_version_id", table_name="chunks")
    op.drop_index("ix_chunks_content_tsv_gin", table_name="chunks")
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.execute("DROP EXTENSION IF EXISTS vector")

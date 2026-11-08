"""Ingestion: categories, per-version file metadata, active chunks.

Revision ID: 0002_ingestion
Revises: 0001_foundation
Create Date: 2026-11-08

- documents: add category; drop status, source_filename, content_type
  (file metadata moves to document_versions, since each version can be a
  different file). M1 never wrote documents, so category is added NOT NULL.
- document_versions: add source_filename, content_type, page_count,
  embedding_model; rename error_message to failure_reason; index content_sha256.
- chunks: add token_count and is_active; index (document_id, is_active).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ingestion"
down_revision: str | Sequence[str] | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # document_versions: add file metadata, copying any existing values from documents.
    op.add_column("document_versions", sa.Column("source_filename", sa.Text(), nullable=True))
    op.add_column("document_versions", sa.Column("content_type", sa.Text(), nullable=True))
    op.execute(
        "UPDATE document_versions v SET source_filename = d.source_filename, "
        "content_type = d.content_type FROM documents d WHERE d.id = v.document_id"
    )
    op.alter_column("document_versions", "source_filename", nullable=False)
    op.alter_column("document_versions", "content_type", nullable=False)
    op.add_column("document_versions", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("document_versions", sa.Column("embedding_model", sa.Text(), nullable=True))
    op.alter_column("document_versions", "error_message", new_column_name="failure_reason")
    op.create_index(
        op.f("ix_document_versions_content_sha256"), "document_versions", ["content_sha256"]
    )

    # documents
    op.add_column("documents", sa.Column("category", sa.Text(), nullable=False))
    op.drop_constraint(op.f("ck_documents_status"), "documents", type_="check")
    op.drop_column("documents", "status")
    op.drop_column("documents", "source_filename")
    op.drop_column("documents", "content_type")

    # chunks (M1 never wrote chunks, so token_count is added NOT NULL)
    op.add_column("chunks", sa.Column("token_count", sa.Integer(), nullable=False))
    op.add_column(
        "chunks",
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(op.f("ix_chunks_document_id_is_active"), "chunks", ["document_id", "is_active"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chunks_document_id_is_active"), table_name="chunks")
    op.drop_column("chunks", "is_active")
    op.drop_column("chunks", "token_count")

    # documents: restore columns, filling them from each document's latest version.
    op.add_column("documents", sa.Column("source_filename", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("content_type", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("status", sa.Text(), nullable=True))
    op.execute(
        "UPDATE documents d SET status = 'active', source_filename = v.source_filename, "
        "content_type = v.content_type FROM (SELECT DISTINCT ON (document_id) document_id, "
        "source_filename, content_type FROM document_versions "
        "ORDER BY document_id, version DESC) v WHERE v.document_id = d.id"
    )
    op.execute("UPDATE documents SET status = 'active' WHERE status IS NULL")
    op.alter_column("documents", "source_filename", nullable=False)
    op.alter_column("documents", "content_type", nullable=False)
    op.alter_column("documents", "status", nullable=False)
    op.create_check_constraint(
        op.f("ck_documents_status"), "documents", "status IN ('active', 'archived')"
    )
    op.drop_column("documents", "category")

    op.drop_index(op.f("ix_document_versions_content_sha256"), table_name="document_versions")
    op.alter_column("document_versions", "failure_reason", new_column_name="error_message")
    op.drop_column("document_versions", "embedding_model")
    op.drop_column("document_versions", "page_count")
    op.drop_column("document_versions", "content_type")
    op.drop_column("document_versions", "source_filename")

"""SQLAlchemy ORM models for the M1 tables.

The migration ``0001_foundation`` is written by hand to match these models; a
DB test checks that they agree. The embedding column is declared without a
dimension here because the dimension comes from the EMBEDDING_DIMENSION setting
and is fixed in the database when the migration runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TSVECTOR_EXPRESSION = "to_tsvector('english'::regconfig, content)"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


VERSION_STATUSES = ("pending", "indexed", "failed")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("status IN ('pending', 'indexed', 'failed')", name="status"),
        Index("ix_document_versions_content_sha256", "content_sha256"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_index"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_content_tsv_gin", "content_tsv", postgresql_using="gin"),
        Index("ix_chunks_document_version_id", "document_version_id"),
        Index("ix_chunks_document_id_is_active", "document_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed(TSVECTOR_EXPRESSION, persisted=True), nullable=True
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa_false())
    created_at: Mapped[datetime] = _created_at()


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'edited', 'rejected')", name="status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    draft_answer: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("rating IN (-1, 1)", name="rating"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


__all__ = [
    "Base",
    "Chunk",
    "Document",
    "DocumentVersion",
    "Feedback",
    "Review",
    "Thread",
]

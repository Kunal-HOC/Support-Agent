"""Database operations for documents and versions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import ScalarSelect, Subquery

from core.ingestion.errors import DocumentNotFound, DuplicateContent, VersionPending
from core.ingestion.storage import ReceivedFile, Storage
from core.ingestion.types import FileKind
from core.models import Chunk, Document, DocumentVersion

INTERRUPTED_REASON = "interrupted by server restart"


@dataclass(frozen=True)
class NewVersion:
    document_id: uuid.UUID
    version_id: uuid.UUID
    version: int


async def find_duplicate(session: AsyncSession, sha256: str) -> tuple[uuid.UUID, int] | None:
    """An existing non-failed version with this content, if any."""
    row = (
        await session.execute(
            select(DocumentVersion.document_id, DocumentVersion.version)
            .where(DocumentVersion.content_sha256 == sha256, DocumentVersion.status != "failed")
            .order_by(DocumentVersion.created_at)
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def create_document(
    session: AsyncSession,
    storage: Storage,
    received: ReceivedFile,
    *,
    kind: FileKind,
    filename: str,
    title: str,
    category: str,
) -> NewVersion:
    duplicate = await find_duplicate(session, received.sha256)
    if duplicate:
        raise DuplicateContent(*duplicate)
    document = Document(id=uuid.uuid4(), title=title, category=category)
    session.add(document)
    return await _add_version(session, storage, received, document.id, 1, kind, filename)


async def create_next_version(
    session: AsyncSession,
    storage: Storage,
    received: ReceivedFile,
    *,
    document_id: uuid.UUID,
    kind: FileKind,
    filename: str,
) -> NewVersion:
    # Lock the document row so concurrent uploads for it are serialised.
    document = (
        await session.execute(select(Document).where(Document.id == document_id).with_for_update())
    ).scalar_one_or_none()
    if document is None:
        raise DocumentNotFound(document_id)
    latest = (
        await session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one()
    if latest.status == "pending":
        raise VersionPending(document_id, latest.version)
    duplicate = await find_duplicate(session, received.sha256)
    if duplicate:
        raise DuplicateContent(*duplicate)
    document.updated_at = func.now()
    return await _add_version(
        session, storage, received, document_id, latest.version + 1, kind, filename
    )


async def _add_version(
    session: AsyncSession,
    storage: Storage,
    received: ReceivedFile,
    document_id: uuid.UUID,
    version: int,
    kind: FileKind,
    filename: str,
) -> NewVersion:
    relative = storage.relative_path(document_id, version, kind)
    row = DocumentVersion(
        id=uuid.uuid4(),
        document_id=document_id,
        version=version,
        content_sha256=received.sha256,
        file_size_bytes=received.size,
        storage_path=relative,
        source_filename=filename,
        content_type=kind.content_type,
        status="pending",
    )
    session.add(row)
    await session.flush()
    storage.place(received.temp_path, relative)
    try:
        await session.commit()
    except BaseException:
        storage.remove(relative)
        raise
    return NewVersion(document_id=document_id, version_id=row.id, version=version)


@dataclass(frozen=True)
class DocumentSummary:
    id: uuid.UUID
    title: str
    category: str
    version: int
    status: str
    chunk_count: int
    updated_at: datetime


def _active_chunk_count() -> ScalarSelect[int]:
    return (
        select(func.count(Chunk.id))
        .where(Chunk.document_id == Document.id, Chunk.is_active.is_(True))
        .correlate(Document)
        .scalar_subquery()
    )


def _latest_versions() -> Subquery:
    return (
        select(DocumentVersion.document_id, DocumentVersion.version, DocumentVersion.status)
        .ext(distinct_on(DocumentVersion.document_id))
        .order_by(DocumentVersion.document_id, DocumentVersion.version.desc())
        .subquery()
    )


async def list_documents(
    session: AsyncSession, *, status: str | None, category: str | None
) -> list[DocumentSummary]:
    latest = _latest_versions()
    query = (
        select(
            Document.id,
            Document.title,
            Document.category,
            latest.c.version,
            latest.c.status,
            _active_chunk_count(),
            Document.updated_at,
        )
        .join(latest, latest.c.document_id == Document.id)
        .order_by(Document.updated_at.desc(), Document.id)
    )
    if status is not None:
        query = query.where(latest.c.status == status)
    if category is not None:
        query = query.where(Document.category == category)
    rows = (await session.execute(query)).all()
    return [DocumentSummary(*row) for row in rows]


@dataclass(frozen=True)
class VersionInfo:
    number: int
    status: str
    failure_reason: str | None
    sha256: str
    created_at: datetime


@dataclass(frozen=True)
class DocumentDetail:
    id: uuid.UUID
    title: str
    category: str
    created_at: datetime
    updated_at: datetime
    active_version: int | None
    chunk_count: int
    section_paths: list[list[str]]
    versions: list[VersionInfo]


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> DocumentDetail:
    document = await session.get(Document, document_id)
    if document is None:
        raise DocumentNotFound(document_id)
    versions = (
        await session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version)
        )
    ).scalars()
    version_infos = [
        VersionInfo(v.version, v.status, v.failure_reason, v.content_sha256, v.created_at)
        for v in versions
    ]
    active = (
        await session.execute(
            select(Chunk.version, Chunk.section_path, func.min(Chunk.chunk_index))
            .where(Chunk.document_id == document_id, Chunk.is_active.is_(True))
            .group_by(Chunk.version, Chunk.section_path)
            .order_by(func.min(Chunk.chunk_index))
        )
    ).all()
    chunk_count = (
        await session.execute(
            select(func.count(Chunk.id)).where(
                Chunk.document_id == document_id, Chunk.is_active.is_(True)
            )
        )
    ).scalar_one()
    return DocumentDetail(
        id=document.id,
        title=document.title,
        category=document.category,
        created_at=document.created_at,
        updated_at=document.updated_at,
        active_version=active[0][0] if active else None,
        chunk_count=chunk_count,
        section_paths=[list(row[1]) for row in active],
        versions=version_infos,
    )


async def delete_document(session: AsyncSession, storage: Storage, document_id: uuid.UUID) -> None:
    document = await session.get(Document, document_id)
    if document is None:
        raise DocumentNotFound(document_id)
    await session.delete(document)  # versions and chunks cascade in the database
    await session.commit()
    storage.delete_document(document_id)


async def fail_interrupted_versions(session: AsyncSession) -> int:
    """Mark versions left pending by a previous process as failed."""
    result = await session.execute(
        update(DocumentVersion)
        .where(DocumentVersion.status == "pending")
        .values(status="failed", failure_reason=INTERRUPTED_REASON)
        .returning(DocumentVersion.id)
    )
    count = len(result.all())
    await session.commit()
    return count

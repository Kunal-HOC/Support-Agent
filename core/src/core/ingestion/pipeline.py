"""Background ingestion of one version: parse → chunk → embed → store → activate.

Runs outside the request with its own DB sessions. Any failure marks the
version ``failed`` (with a reason) in a fresh transaction, so the previous
version's chunks stay active.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Settings
from core.ingestion.chunking import chunk_blocks
from core.ingestion.embedding import Embedder
from core.ingestion.errors import EmbeddingError, IngestionFailed
from core.ingestion.parsing import NO_TEXT_REASON, parse
from core.ingestion.storage import Storage
from core.ingestion.tokenizer import Tokenizer
from core.ingestion.types import ChunkData, FileKind
from core.models import Chunk, Document, DocumentVersion

logger = logging.getLogger(__name__)

INTERNAL_FAILURE_REASON = "internal error during ingestion"


@dataclass(frozen=True)
class IngestionContext:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    storage: Storage
    embedder: Embedder
    tokenizer: Tokenizer


@dataclass(frozen=True)
class _Job:
    document_id: uuid.UUID
    version: int
    kind: FileKind
    storage_path: str


async def ingest_version(context: IngestionContext, version_id: uuid.UUID) -> None:
    try:
        job = await _load_job(context, version_id)
        if job is None:
            return  # deleted, or no longer pending
        page_count, chunks = await _parse_and_chunk(context, job)
        embeddings = await _embed(context, chunks)
        await _store_and_activate(context, version_id, job, page_count, chunks, embeddings)
    except IngestionFailed as failure:
        await _mark_failed(context, version_id, failure.reason)
    except EmbeddingError as error:
        await _mark_failed(context, version_id, f"embedding failed: {error}")
    except Exception:
        logger.exception("Ingestion of version %s failed unexpectedly", version_id)
        await _mark_failed(context, version_id, INTERNAL_FAILURE_REASON)


async def _load_job(context: IngestionContext, version_id: uuid.UUID) -> _Job | None:
    async with context.session_factory() as session:
        version = await session.get(DocumentVersion, version_id)
        if version is None or version.status != "pending":
            return None
        return _Job(
            document_id=version.document_id,
            version=version.version,
            kind=FileKind.from_content_type(version.content_type),
            storage_path=version.storage_path,
        )


async def _parse_and_chunk(
    context: IngestionContext, job: _Job
) -> tuple[int | None, list[ChunkData]]:
    settings = context.settings
    data = await asyncio.to_thread(context.storage.absolute(job.storage_path).read_bytes)
    parsed = await asyncio.to_thread(parse, job.kind, data, max_pages=settings.MAX_PAGES)
    chunks = await asyncio.to_thread(
        chunk_blocks,
        parsed.blocks,
        strategy=settings.CHUNKING_STRATEGY,
        tokenizer=context.tokenizer,
        max_tokens=settings.CHUNK_MAX_TOKENS,
        overlap=settings.CHUNK_OVERLAP_TOKENS,
    )
    if not chunks:
        raise IngestionFailed(NO_TEXT_REASON)
    return parsed.page_count, chunks


async def _embed(context: IngestionContext, chunks: list[ChunkData]) -> list[list[float]]:
    expected = context.settings.EMBEDDING_DIMENSION
    batch_size = context.settings.EMBEDDING_BATCH_SIZE
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), batch_size):
        batch = [chunk.content for chunk in chunks[start : start + batch_size]]
        result = await context.embedder.embed(batch)
        if len(result) != len(batch):
            raise EmbeddingError(f"expected {len(batch)} vectors, got {len(result)}")
        for vector in result:
            if len(vector) != expected:
                raise IngestionFailed(
                    f"embedding dimension mismatch: expected {expected}, got {len(vector)}"
                )
        vectors.extend(result)
    return vectors


async def _store_and_activate(
    context: IngestionContext,
    version_id: uuid.UUID,
    job: _Job,
    page_count: int | None,
    chunks: list[ChunkData],
    embeddings: list[list[float]],
) -> None:
    """Insert chunks and switch the active version in one transaction."""
    async with context.session_factory() as session, session.begin():
        version = (
            await session.execute(
                select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
            )
        ).scalar_one_or_none()
        if version is None or version.status != "pending":
            return
        await session.execute(
            update(Chunk).where(Chunk.document_id == job.document_id).values(is_active=False)
        )
        session.add_all(
            Chunk(
                document_id=job.document_id,
                document_version_id=version_id,
                version=job.version,
                chunk_index=chunk.chunk_index,
                section_path=list(chunk.section_path),
                page=chunk.page,
                content=chunk.content,
                embedding=embedding,
                token_count=chunk.token_count,
                is_active=True,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        )
        version.status = "indexed"
        version.page_count = page_count
        version.embedding_model = context.embedder.model
        await session.execute(
            update(Document).where(Document.id == job.document_id).values(updated_at=func.now())
        )


async def _mark_failed(context: IngestionContext, version_id: uuid.UUID, reason: str) -> None:
    try:
        async with context.session_factory() as session, session.begin():
            await session.execute(
                update(DocumentVersion)
                .where(DocumentVersion.id == version_id, DocumentVersion.status == "pending")
                .values(status="failed", failure_reason=reason)
            )
    except Exception:
        logger.exception("Could not mark version %s as failed (%s)", version_id, reason)

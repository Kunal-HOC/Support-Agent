"""SOP document endpoints: upload, re-upload, list, detail, delete."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.ingestion import service
from core.ingestion.errors import InvalidUpload
from core.ingestion.filetypes import detect_kind
from core.ingestion.pipeline import IngestionContext, ingest_version
from core.ingestion.storage import ReceivedFile
from core.ingestion.types import FileKind
from server.deps import get_session

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_TITLE_LENGTH = 200
VersionStatus = Literal["pending", "indexed", "failed"]


class UploadAccepted(BaseModel):
    document_id: uuid.UUID
    version: int
    status: Literal["pending"]


class DocumentListItem(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    version: int
    status: VersionStatus
    chunk_count: int
    updated_at: datetime


class VersionOut(BaseModel):
    number: int
    status: VersionStatus
    failure_reason: str | None
    sha256: str
    created_at: datetime


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    created_at: datetime
    updated_at: datetime
    active_version: int | None
    chunk_count: int
    section_paths: list[list[str]]
    versions: list[VersionOut]


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _context(request: Request) -> IngestionContext:
    context: IngestionContext = request.app.state.ingestion
    return context


ContextDep = Annotated[IngestionContext, Depends(_context)]


async def _receive(context: IngestionContext, file: UploadFile) -> tuple[ReceivedFile, FileKind]:
    received = await context.storage.receive(file.read, context.settings.MAX_UPLOAD_BYTES)
    try:
        kind = detect_kind(file.filename or "", received.temp_path)
    except BaseException:
        context.storage.discard(received.temp_path)
        raise
    return received, kind


def _clean_title(title: str) -> str:
    cleaned = title.strip()
    if not 1 <= len(cleaned) <= MAX_TITLE_LENGTH:
        raise InvalidUpload(
            f"Title must be 1 to {MAX_TITLE_LENGTH} characters.",
            {"field": "title", "max_length": MAX_TITLE_LENGTH},
        )
    return cleaned


def _check_category(context: IngestionContext, category: str) -> str:
    allowed = context.settings.SOP_CATEGORIES
    cleaned = category.strip()
    if cleaned not in allowed:
        raise InvalidUpload(
            "Unknown category.", {"field": "category", "allowed_categories": list(allowed)}
        )
    return cleaned


@router.post("", status_code=202, response_model=UploadAccepted)
async def upload_document(
    background: BackgroundTasks,
    session: SessionDep,
    context: ContextDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()],
    category: Annotated[str, Form()],
) -> UploadAccepted:
    clean_title = _clean_title(title)
    clean_category = _check_category(context, category)
    received, kind = await _receive(context, file)
    try:
        new = await service.create_document(
            session,
            context.storage,
            received,
            kind=kind,
            filename=file.filename or "",
            title=clean_title,
            category=clean_category,
        )
    finally:
        context.storage.discard(received.temp_path)  # no-op once placed
    background.add_task(ingest_version, context, new.version_id)
    return UploadAccepted(document_id=new.document_id, version=new.version, status="pending")


@router.put("/{document_id}", status_code=202, response_model=UploadAccepted)
async def upload_new_version(
    document_id: uuid.UUID,
    background: BackgroundTasks,
    session: SessionDep,
    context: ContextDep,
    file: Annotated[UploadFile, File()],
) -> UploadAccepted:
    received, kind = await _receive(context, file)
    try:
        new = await service.create_next_version(
            session,
            context.storage,
            received,
            document_id=document_id,
            kind=kind,
            filename=file.filename or "",
        )
    finally:
        context.storage.discard(received.temp_path)
    background.add_task(ingest_version, context, new.version_id)
    return UploadAccepted(document_id=new.document_id, version=new.version, status="pending")


@router.get("", response_model=list[DocumentListItem])
async def list_documents(
    session: SessionDep,
    status: Annotated[VersionStatus | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
) -> list[DocumentListItem]:
    rows = await service.list_documents(session, status=status, category=category)
    return [DocumentListItem.model_validate(row, from_attributes=True) for row in rows]


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, session: SessionDep) -> DocumentOut:
    detail = await service.get_document(session, document_id)
    return DocumentOut.model_validate(detail, from_attributes=True)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID, session: SessionDep, context: ContextDep
) -> Response:
    await service.delete_document(session, context.storage, document_id)
    return Response(status_code=204)

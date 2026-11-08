"""Ingestion errors.

``UploadError`` subclasses are raised while handling a request and are turned
into HTTP error responses by the server. ``IngestionFailed`` is raised in the
background pipeline and becomes a version's ``failure_reason``.
"""

from __future__ import annotations

import uuid
from typing import Any


class UploadError(Exception):
    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class UnsupportedFileType(UploadError):
    def __init__(self, allowed: tuple[str, ...]) -> None:
        super().__init__(
            f"Unsupported file type. Allowed types: {', '.join(allowed)}",
            {"allowed_extensions": list(allowed)},
        )


class FileTooLarge(UploadError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            f"File is larger than the {limit}-byte limit.", {"max_upload_bytes": limit}
        )


class InvalidUpload(UploadError):
    """Bad form fields (title, category)."""


class DuplicateContent(UploadError):
    def __init__(self, document_id: uuid.UUID, version: int) -> None:
        super().__init__(
            f"This file is already stored as version {version} of document {document_id}.",
            {"document_id": str(document_id), "version": version},
        )


class VersionPending(UploadError):
    def __init__(self, document_id: uuid.UUID, version: int) -> None:
        super().__init__(
            f"Version {version} of document {document_id} is still being ingested.",
            {"document_id": str(document_id), "version": version},
        )


class DocumentNotFound(UploadError):
    def __init__(self, document_id: uuid.UUID) -> None:
        super().__init__(f"Document {document_id} not found.", {"document_id": str(document_id)})


class IngestionFailed(Exception):
    """A version cannot be indexed; ``reason`` is stored as its failure_reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class EmbeddingError(Exception):
    """The embedding provider failed. The message never contains the API key."""

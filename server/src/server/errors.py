"""Typed error responses. Clients never see a stack trace."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.ingestion.errors import (
    DocumentNotFound,
    DuplicateContent,
    FileTooLarge,
    InvalidUpload,
    UnsupportedFileType,
    UploadError,
    VersionPending,
)
from server.request_id import REQUEST_ID_HEADER, get_request_id

logger = logging.getLogger(__name__)

ErrorCode = Literal[
    "validation_error",
    "http_error",
    "internal_error",
    "unsupported_file_type",
    "file_too_large",
    "duplicate_content",
    "version_pending",
    "not_found",
]

# Upload error type -> (HTTP status, error code)
UPLOAD_ERRORS: dict[type[UploadError], tuple[int, ErrorCode]] = {
    UnsupportedFileType: (415, "unsupported_file_type"),
    FileTooLarge: (413, "file_too_large"),
    InvalidUpload: (422, "validation_error"),
    DuplicateContent: (409, "duplicate_content"),
    VersionPending: (409, "version_pending"),
    DocumentNotFound: (404, "not_found"),
}

INTERNAL_ERROR_MESSAGE = "An unexpected error occurred."


class ErrorResponse(BaseModel):
    """Body returned for every error."""

    code: ErrorCode
    message: str
    details: Any | None
    request_id: str


def error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = get_request_id()
    body = ErrorResponse(code=code, message=message, details=details, request_id=request_id)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body),
        headers={**(headers or {}), REQUEST_ID_HEADER: request_id},
    )


def internal_error_response() -> JSONResponse:
    return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return error_response(422, "validation_error", "Request validation failed.", details)


async def _handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return error_response(
        exc.status_code, "http_error", str(exc.detail), headers=dict(exc.headers or {})
    )


async def _handle_upload_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, UploadError)
    status_code, code = UPLOAD_ERRORS[type(exc)]
    return error_response(status_code, code, exc.message, exc.details)


def register_error_handlers(app: FastAPI) -> None:
    """Register handlers for validation and HTTP errors.

    Unhandled exceptions are turned into ``internal_error`` responses by
    ``RequestIdMiddleware`` so that the request id header is always present.
    """
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    for error_type in UPLOAD_ERRORS:
        app.add_exception_handler(error_type, _handle_upload_error)

"""Original files under UPLOAD_DIR.

Layout: ``<UPLOAD_DIR>/<document_id>/v<version>/original.<ext>``. Uploads are
first streamed to ``<UPLOAD_DIR>/.incoming/`` (same filesystem), then moved
into place with an atomic rename. Paths stored in the DB are relative to
UPLOAD_DIR.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from core.ingestion.errors import FileTooLarge
from core.ingestion.types import FileKind

logger = logging.getLogger(__name__)

READ_CHUNK_BYTES = 1024 * 1024
INCOMING_DIR = ".incoming"

ReadFn = Callable[[int], Awaitable[bytes]]


@dataclass(frozen=True)
class ReceivedFile:
    temp_path: Path
    sha256: str
    size: int


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def receive(self, read: ReadFn, max_bytes: int) -> ReceivedFile:
        """Stream an upload to a temp file, hashing it and enforcing ``max_bytes``."""
        incoming = self.root / INCOMING_DIR
        incoming.mkdir(exist_ok=True)
        temp_path = incoming / f"{uuid.uuid4()}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with temp_path.open("wb") as handle:
                while chunk := await read(READ_CHUNK_BYTES):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLarge(max_bytes)
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            self.discard(temp_path)
            raise
        return ReceivedFile(temp_path=temp_path, sha256=digest.hexdigest(), size=size)

    @staticmethod
    def relative_path(document_id: uuid.UUID, version: int, kind: FileKind) -> str:
        return str(PurePosixPath(str(document_id), f"v{version}", f"original{kind.extension}"))

    def absolute(self, relative: str) -> Path:
        return self.root / PurePosixPath(relative)

    def place(self, temp_path: Path, relative: str) -> Path:
        """Move a received temp file to its final location."""
        target = self.absolute(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_path, target)
        return target

    def remove(self, relative: str) -> None:
        target = self.absolute(relative)
        target.unlink(missing_ok=True)
        for parent in (target.parent, target.parent.parent):
            try:
                parent.rmdir()  # only removes empty folders
            except OSError:
                break

    def delete_document(self, document_id: uuid.UUID) -> None:
        folder = self.root / str(document_id)
        try:
            shutil.rmtree(folder)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Could not remove stored files for document %s", document_id)

    @staticmethod
    def discard(temp_path: Path) -> None:
        temp_path.unlink(missing_ok=True)

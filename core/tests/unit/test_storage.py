from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from core.ingestion.errors import FileTooLarge
from core.ingestion.storage import INCOMING_DIR, Storage
from core.ingestion.types import FileKind


def _reader(data: bytes):  # type: ignore[no-untyped-def]
    position = 0

    async def read(size: int) -> bytes:
        nonlocal position
        chunk = data[position : position + size]
        position += len(chunk)
        return chunk

    return read


async def test_receive_hashes_and_places_file(upload_dir: Path) -> None:
    storage = Storage(upload_dir)
    data = b"x" * (3 * 1024 * 1024 + 5)
    received = await storage.receive(_reader(data), max_bytes=len(data))
    assert received.sha256 == hashlib.sha256(data).hexdigest()
    assert received.size == len(data)

    document_id = uuid.uuid4()
    relative = storage.relative_path(document_id, 2, FileKind.PDF)
    assert relative == f"{document_id}/v2/original.pdf"
    storage.place(received.temp_path, relative)
    assert (upload_dir / relative).read_bytes() == data
    assert list((upload_dir / INCOMING_DIR).iterdir()) == []


async def test_receive_rejects_oversize_and_cleans_up(upload_dir: Path) -> None:
    storage = Storage(upload_dir)
    with pytest.raises(FileTooLarge):
        await storage.receive(_reader(b"y" * 11), max_bytes=10)
    assert list((upload_dir / INCOMING_DIR).iterdir()) == []


async def test_remove_and_delete_document(upload_dir: Path) -> None:
    storage = Storage(upload_dir)
    document_id = uuid.uuid4()
    for version in (1, 2):
        received = await storage.receive(_reader(b"v%d" % version), max_bytes=100)
        storage.place(
            received.temp_path, storage.relative_path(document_id, version, FileKind.MARKDOWN)
        )
    storage.remove(storage.relative_path(document_id, 2, FileKind.MARKDOWN))
    assert not (upload_dir / str(document_id) / "v2").exists()
    assert (upload_dir / str(document_id) / "v1").exists()
    storage.delete_document(document_id)
    assert not (upload_dir / str(document_id)).exists()
    storage.delete_document(document_id)  # deleting again is harmless

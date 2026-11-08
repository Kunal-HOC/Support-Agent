"""Detect an upload's type from both its extension and its content."""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePath

from core.ingestion.errors import UnsupportedFileType
from core.ingestion.types import ALLOWED_EXTENSIONS, FileKind

PDF_MAGIC = b"%PDF-"
DOCX_REQUIRED_MEMBERS = ("[Content_Types].xml", "word/document.xml")


def detect_kind(filename: str, path: Path) -> FileKind:
    """Return the file's kind, or raise ``UnsupportedFileType``.

    The extension (case-insensitive) picks the expected kind; the content must
    then match it: PDF magic bytes, a DOCX zip with a Word body, or Markdown
    that is valid UTF-8 without NUL bytes.
    """
    extension = PurePath(filename).suffix.lower()
    kind = next((k for k in FileKind if k.extension == extension), None)
    if kind is None or not _content_matches(kind, path):
        raise UnsupportedFileType(ALLOWED_EXTENSIONS)
    return kind


def _content_matches(kind: FileKind, path: Path) -> bool:
    if kind is FileKind.PDF:
        with path.open("rb") as handle:
            return handle.read(len(PDF_MAGIC)) == PDF_MAGIC
    if kind is FileKind.DOCX:
        if not zipfile.is_zipfile(path):
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return False
        return all(member in names for member in DOCX_REQUIRED_MEMBERS)
    data = path.read_bytes()
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True

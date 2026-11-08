"""Plain data types shared by the ingestion steps."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FileKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    MARKDOWN = "md"

    @property
    def extension(self) -> str:
        return f".{self.value}"

    @property
    def content_type(self) -> str:
        return CONTENT_TYPES[self]

    @classmethod
    def from_content_type(cls, content_type: str) -> FileKind:
        for kind, value in CONTENT_TYPES.items():
            if value == content_type:
                return kind
        raise ValueError(f"unknown content type: {content_type}")


CONTENT_TYPES: dict[FileKind, str] = {
    FileKind.PDF: "application/pdf",
    FileKind.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FileKind.MARKDOWN: "text/markdown",
}

ALLOWED_EXTENSIONS: tuple[str, ...] = tuple(kind.extension for kind in FileKind)


@dataclass(frozen=True)
class Block:
    """A paragraph-like run of text and where it sits in the document."""

    text: str
    section_path: tuple[str, ...]
    page: int | None  # 1-based; PDF only


@dataclass(frozen=True)
class ParsedDocument:
    blocks: list[Block]
    page_count: int | None  # PDF only


@dataclass(frozen=True)
class ChunkData:
    chunk_index: int
    content: str
    section_path: tuple[str, ...]
    page: int | None
    token_count: int

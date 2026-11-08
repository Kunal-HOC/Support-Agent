"""Turn a stored file into ``Block``s with section paths and pages."""

from __future__ import annotations

from core.ingestion.errors import IngestionFailed
from core.ingestion.parsing.docx import parse_docx
from core.ingestion.parsing.markdown import parse_markdown
from core.ingestion.parsing.pdf import parse_pdf
from core.ingestion.types import FileKind, ParsedDocument

NO_TEXT_REASON = "no extractable text"


def parse(kind: FileKind, data: bytes, *, max_pages: int) -> ParsedDocument:
    """Parse ``data``. Raises ``IngestionFailed`` with the failure reason."""
    try:
        if kind is FileKind.PDF:
            document = parse_pdf(data, max_pages=max_pages)
        elif kind is FileKind.DOCX:
            document = parse_docx(data)
        else:
            document = parse_markdown(data)
    except IngestionFailed:
        raise
    except Exception as exc:  # any parser error becomes the version's failure reason
        message = str(exc).strip() or type(exc).__name__
        raise IngestionFailed(f"parse error: {message}") from exc
    if not any(block.text.strip() for block in document.blocks):
        raise IngestionFailed(NO_TEXT_REASON)
    return document

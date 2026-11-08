"""PDF parsing with pdfplumber.

Headings come from the PDF outline (bookmarks) when it has one. Otherwise a
font-size heuristic is used: the body size is the most common character size;
short lines at least ``HEADING_SIZE_RATIO`` times larger are headings, and
distinct heading sizes (largest first) become levels 1, 2, 3, ...
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import PDFNoOutlines
from pdfminer.pdftypes import PDFObjRef, resolve1
from pdfminer.psparser import PSLiteral
from pdfminer.utils import decode_text

from core.ingestion.errors import IngestionFailed
from core.ingestion.parsing.sections import SectionTracker
from core.ingestion.types import Block, ParsedDocument

PAGE_LIMIT_REASON = "page limit exceeded"
HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 120
# A vertical gap bigger than this fraction of the line height starts a new paragraph.
PARAGRAPH_GAP_RATIO = 0.6
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class _Line:
    text: str
    size: float
    top: float
    bottom: float


@dataclass(frozen=True)
class _OutlineEntry:
    level: int
    title: str
    page_index: int


def parse_pdf(data: bytes, *, max_pages: int) -> ParsedDocument:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page_count = len(pdf.pages)
        if page_count > max_pages:
            raise IngestionFailed(PAGE_LIMIT_REASON)
        pages = [_lines(page) for page in pdf.pages]
        outline = _outline(pdf)
    blocks = _blocks_from_outline(pages, outline) if outline else _blocks_from_font_sizes(pages)
    return ParsedDocument(blocks=blocks, page_count=page_count)


def _normalise(text: str) -> str:
    return _SPACES.sub(" ", text).strip().casefold()


def _lines(page: Any) -> list[_Line]:
    lines: list[_Line] = []
    for raw in page.extract_text_lines(return_chars=True):
        text = str(raw["text"]).strip()
        if not text:
            continue
        size = max(round(float(char["size"]) * 2) / 2 for char in raw["chars"])
        lines.append(_Line(text, size, float(raw["top"]), float(raw["bottom"])))
    return lines


def _outline(pdf: Any) -> list[_OutlineEntry]:
    page_index_by_objid = {page.page_obj.pageid: i for i, page in enumerate(pdf.pages)}
    entries: list[_OutlineEntry] = []
    try:
        raw_entries = list(pdf.doc.get_outlines())
    except PDFNoOutlines:
        return []
    for level, title, dest, action, _ in raw_entries:
        page_index = _resolve_page(pdf, dest, action, page_index_by_objid)
        if page_index is None or not title:
            continue
        text = decode_text(title) if isinstance(title, bytes) else str(title)
        entries.append(_OutlineEntry(int(level), text.strip(), page_index))
    return entries


def _resolve_page(
    pdf: Any, dest: Any, action: Any, page_index_by_objid: dict[int, int]
) -> int | None:
    target = dest
    if target is None and isinstance(action, dict):
        target = action.get("D")
    target = resolve1(target)
    if isinstance(target, (bytes, str, PSLiteral)):
        name = target.name if isinstance(target, PSLiteral) else target
        target = resolve1(pdf.doc.get_dest(name))
    if isinstance(target, dict):
        target = resolve1(target.get("D"))
    if isinstance(target, list) and target:
        page_ref = target[0]
        if isinstance(page_ref, PDFObjRef):
            return page_index_by_objid.get(page_ref.objid)
    return None


class _BlockBuilder:
    """Collects body lines into paragraph blocks under the current section."""

    def __init__(self) -> None:
        self.tracker = SectionTracker()
        self.blocks: list[Block] = []
        self._lines: list[str] = []
        self._page: int | None = None
        self._last: _Line | None = None

    def heading(self, level: int, title: str) -> None:
        self.flush()
        self.tracker.heading(level, title)

    def body(self, line: _Line, page: int) -> None:
        if self._last is not None and self._page == page:
            height = max(line.bottom - line.top, 1.0)
            if line.top - self._last.bottom > height * PARAGRAPH_GAP_RATIO:
                self.flush()
        elif self._page != page:
            self.flush()
        if not self._lines:
            self._page = page
        self._lines.append(line.text)
        self._last = line

    def flush(self) -> None:
        if self._lines:
            text = "\n".join(self._lines)
            self.blocks.append(Block(text, self.tracker.path, self._page))
        self._lines = []
        self._last = None


def _blocks_from_outline(pages: list[list[_Line]], outline: list[_OutlineEntry]) -> list[Block]:
    builder = _BlockBuilder()
    for page_index, lines in enumerate(pages):
        page = page_index + 1
        pending = [entry for entry in outline if entry.page_index == page_index]
        # Entries whose title is not printed on the page apply from the page top.
        printed = {_normalise(line.text) for line in lines}
        for entry in [e for e in pending if _normalise(e.title) not in printed]:
            builder.heading(entry.level, entry.title)
        pending = [e for e in pending if _normalise(e.title) in printed]
        for line in lines:
            if pending and _normalise(line.text) == _normalise(pending[0].title):
                entry = pending.pop(0)
                builder.heading(entry.level, entry.title)
            else:
                builder.body(line, page)
    builder.flush()
    return builder.blocks


def _blocks_from_font_sizes(pages: list[list[_Line]]) -> list[Block]:
    sizes: Counter[float] = Counter()
    for lines in pages:
        for line in lines:
            sizes[line.size] += len(line.text)
    if not sizes:
        return []
    body_size = sizes.most_common(1)[0][0]
    heading_sizes = sorted(
        {line.size for lines in pages for line in lines if _is_heading_candidate(line, body_size)},
        reverse=True,
    )
    level_by_size = {size: level for level, size in enumerate(heading_sizes, start=1)}

    builder = _BlockBuilder()
    previous_heading: _Line | None = None
    pending_title: list[str] = []
    pending_level = 0

    def close_heading() -> None:
        nonlocal pending_title, previous_heading
        if pending_title:
            builder.heading(pending_level, " ".join(pending_title))
        pending_title = []
        previous_heading = None

    for page_index, lines in enumerate(pages):
        for line in lines:
            if _is_heading_candidate(line, body_size):
                level = level_by_size[line.size]
                continues = (
                    previous_heading is not None
                    and previous_heading.size == line.size
                    and line.top - previous_heading.bottom < (line.bottom - line.top)
                )
                if not continues:
                    close_heading()
                    pending_level = level
                pending_title.append(line.text)
                previous_heading = line
            else:
                close_heading()
                builder.body(line, page_index + 1)
        close_heading()
    builder.flush()
    return builder.blocks


def _is_heading_candidate(line: _Line, body_size: float) -> bool:
    return line.size >= body_size * HEADING_SIZE_RATIO and len(line.text) <= MAX_HEADING_CHARS

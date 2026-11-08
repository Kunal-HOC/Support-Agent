"""DOCX parsing with python-docx: ``Heading N`` styles define sections."""

from __future__ import annotations

import io
import re

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from core.ingestion.parsing.sections import SectionTracker
from core.ingestion.types import Block, ParsedDocument

HEADING_STYLE = re.compile(r"^Heading (\d)$")


def parse_docx(data: bytes) -> ParsedDocument:
    document = Document(io.BytesIO(data))
    tracker = SectionTracker()
    blocks: list[Block] = []
    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = paragraph.style.name if paragraph.style is not None else ""
            match = HEADING_STYLE.match(style_name or "")
            if match:
                tracker.heading(int(match.group(1)), text)
            else:
                prefix = "- " if (style_name or "").startswith("List") else ""
                blocks.append(Block(prefix + text, tracker.path, None))
        elif tag == "tbl":
            table = Table(element, document)
            rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
            text = "\n".join(r for r in rows if r.strip(" |"))
            if text:
                blocks.append(Block(text, tracker.path, None))
    return ParsedDocument(blocks=_merge_list_items(blocks), page_count=None)


def _merge_list_items(blocks: list[Block]) -> list[Block]:
    """Join consecutive list items in the same section into one block."""
    merged: list[Block] = []
    for block in blocks:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and block.text.startswith("- ")
            and previous.text.split("\n")[-1].startswith("- ")
            and previous.section_path == block.section_path
        ):
            merged[-1] = Block(f"{previous.text}\n{block.text}", block.section_path, None)
        else:
            merged.append(block)
    return merged

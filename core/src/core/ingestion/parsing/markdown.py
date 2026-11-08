"""Markdown parsing with markdown-it (CommonMark + tables)."""

from __future__ import annotations

from markdown_it import MarkdownIt

from core.ingestion.parsing.sections import SectionTracker
from core.ingestion.types import Block, ParsedDocument


def parse_markdown(data: bytes) -> ParsedDocument:
    text = data.decode("utf-8-sig")
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    tracker = SectionTracker()
    blocks: list[Block] = []
    list_depth = 0
    list_items: list[str] = []
    table_rows: list[list[str]] = []
    row: list[str] = []

    def add(block_text: str) -> None:
        if block_text.strip():
            blocks.append(Block(block_text.strip(), tracker.path, None))

    for index, token in enumerate(tokens):
        kind = token.type
        if kind == "heading_open":
            tracker.heading(int(token.tag[1:]), tokens[index + 1].content)
        elif kind in ("bullet_list_open", "ordered_list_open"):
            list_depth += 1
        elif kind in ("bullet_list_close", "ordered_list_close"):
            list_depth -= 1
            if list_depth == 0:
                add("\n".join(list_items))
                list_items = []
        elif kind == "inline" and index > 0 and tokens[index - 1].type == "paragraph_open":
            if list_depth:
                list_items.append(f"- {token.content}")
            else:
                add(token.content)
        elif kind in ("fence", "code_block"):
            add(token.content)
        elif kind == "tr_open":
            row = []
        elif kind == "inline" and index > 0 and tokens[index - 1].type in ("th_open", "td_open"):
            row.append(token.content.strip())
        elif kind == "tr_close":
            table_rows.append(row)
        elif kind == "table_close":
            add("\n".join(" | ".join(cells) for cells in table_rows))
            table_rows = []
    return ParsedDocument(blocks=blocks, page_count=None)

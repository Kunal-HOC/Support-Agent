"""Split parsed blocks into token-bounded chunks.

- ``heading``: chunks never cross a section boundary. Within a section,
  paragraphs are packed up to ``max_tokens``; a paragraph longer than that is
  split on token boundaries. Consecutive chunks of the same section overlap by
  ``overlap`` tokens.
- ``fixed``: a sliding window of ``max_tokens`` with ``overlap`` over the whole
  document's text, ignoring sections (a baseline).

In both, a chunk's ``section_path`` and ``page`` are those of the text it
starts with (ignoring overlap). Chunk text does not repeat the headings.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import groupby

from core.config import ChunkingStrategy
from core.ingestion.tokenizer import Tokenizer
from core.ingestion.types import Block, ChunkData

PARAGRAPH_SEPARATOR = "\n\n"


@dataclass
class _Draft:
    tokens: list[int]
    section_path: tuple[str, ...]
    page: int | None


def chunk_blocks(
    blocks: list[Block],
    *,
    strategy: ChunkingStrategy,
    tokenizer: Tokenizer,
    max_tokens: int,
    overlap: int,
) -> list[ChunkData]:
    if overlap >= max_tokens:
        raise ValueError("overlap must be less than max_tokens")
    if strategy == "heading":
        drafts = list(_heading_drafts(blocks, tokenizer, max_tokens, overlap))
    else:
        drafts = list(_fixed_drafts(blocks, tokenizer, max_tokens, overlap))
    chunks: list[ChunkData] = []
    for draft in drafts:
        content = tokenizer.decode(draft.tokens).strip()
        if not content:
            continue
        chunks.append(
            ChunkData(
                chunk_index=len(chunks),
                content=content,
                section_path=draft.section_path,
                page=draft.page,
                token_count=len(draft.tokens),
            )
        )
    return chunks


def _windows(tokens: list[int], max_tokens: int, overlap: int) -> Iterator[tuple[int, list[int]]]:
    """Yield ``(start, window)`` pairs covering ``tokens`` with the given overlap."""
    step = max_tokens - overlap
    start = 0
    while True:
        yield start, tokens[start : start + max_tokens]
        if start + max_tokens >= len(tokens):
            return
        start += step


@dataclass
class _SectionPacker:
    section_path: tuple[str, ...]
    max_tokens: int
    overlap: int
    separator: list[int]
    drafts: list[_Draft] = field(default_factory=list)
    _tokens: list[int] = field(default_factory=list)
    _page: int | None = None
    _has_new_text: bool = False

    def add(self, tokens: list[int], page: int | None) -> None:
        if len(tokens) > self.max_tokens:
            self._flush()
            windows = list(_windows(tokens, self.max_tokens, self.overlap))
            for _, window in windows:
                self.drafts.append(_Draft(window, self.section_path, page))
            self._tokens = list(windows[-1][1][-self.overlap :]) if self.overlap else []
            self._has_new_text = False
            return
        joined = self._tokens + self.separator + tokens if self._tokens else tokens
        if len(joined) <= self.max_tokens:
            if not self._has_new_text:
                self._page = page
            self._tokens = joined
            self._has_new_text = True
            return
        self._flush()
        tail_room = self.max_tokens - len(tokens) - len(self.separator)
        keep = min(self.overlap, tail_room)
        tail = self._tokens[-keep:] if keep > 0 else []
        self._tokens = tail + self.separator + tokens if tail else tokens
        self._page = page
        self._has_new_text = True

    def _flush(self) -> None:
        if self._has_new_text:
            self.drafts.append(_Draft(self._tokens, self.section_path, self._page))
        self._has_new_text = False

    def finish(self) -> list[_Draft]:
        self._flush()
        return self.drafts


def _heading_drafts(
    blocks: list[Block], tokenizer: Tokenizer, max_tokens: int, overlap: int
) -> Iterator[_Draft]:
    separator = tokenizer.encode(PARAGRAPH_SEPARATOR)
    for section_path, group in groupby(blocks, key=lambda block: block.section_path):
        packer = _SectionPacker(section_path, max_tokens, overlap, separator)
        for block in group:
            tokens = tokenizer.encode(block.text)
            if tokens:
                packer.add(tokens, block.page)
        yield from packer.finish()


def _fixed_drafts(
    blocks: list[Block], tokenizer: Tokenizer, max_tokens: int, overlap: int
) -> Iterator[_Draft]:
    separator = tokenizer.encode(PARAGRAPH_SEPARATOR)
    tokens: list[int] = []
    starts: list[int] = []
    ends: list[int] = []
    owners: list[Block] = []
    for block in blocks:
        encoded = tokenizer.encode(block.text)
        if not encoded:
            continue
        if tokens:
            tokens += separator
        starts.append(len(tokens))
        owners.append(block)
        tokens += encoded
        ends.append(len(tokens))
    if not tokens:
        return
    for start, window in _windows(tokens, max_tokens, overlap):
        index = max(bisect.bisect_right(starts, start) - 1, 0)
        if start >= ends[index] and index + 1 < len(owners):
            index += 1  # window starts on a separator: it belongs to the next block
        owner = owners[index]
        yield _Draft(window, owner.section_path, owner.page)

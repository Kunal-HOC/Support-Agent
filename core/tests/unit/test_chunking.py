from __future__ import annotations

from pathlib import Path

import pytest

from core.config import ChunkingStrategy
from core.ingestion.chunking import chunk_blocks
from core.ingestion.parsing import parse
from core.ingestion.tokenizer import TiktokenTokenizer
from core.ingestion.types import Block, FileKind
from testing_support import EXPECTED_SECTION_PATHS, FakeTokenizer, sop_fixture

A = ("Doc", "A")
B = ("Doc", "B")


def _words(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{i}" for i in range(count))


def _chunk(blocks: list[Block], strategy: ChunkingStrategy, max_tokens: int, overlap: int):  # type: ignore[no-untyped-def]
    return chunk_blocks(
        blocks, strategy=strategy, tokenizer=FakeTokenizer(), max_tokens=max_tokens, overlap=overlap
    )


def test_heading_chunks_never_cross_sections() -> None:
    blocks = [Block(_words("a", 6), A, 1), Block(_words("b", 6), B, 2)]
    chunks = _chunk(blocks, "heading", max_tokens=50, overlap=5)
    assert [(c.section_path, c.page) for c in chunks] == [(A, 1), (B, 2)]
    assert "b0" not in chunks[0].content and "a5" not in chunks[1].content


def test_heading_packs_paragraphs_up_to_the_limit() -> None:
    # Three 4-word paragraphs; "\n\n" counts as one token in the fake tokenizer.
    blocks = [Block(_words(p, 4), A, 1) for p in ("x", "y", "z")]
    chunks = _chunk(blocks, "heading", max_tokens=9, overlap=0)
    assert [c.content for c in chunks] == [
        f"{_words('x', 4)}\n\n{_words('y', 4)}",
        _words("z", 4),
    ]
    assert all(c.token_count <= 9 for c in chunks)


def test_heading_overlap_stays_within_section() -> None:
    blocks = [Block(_words(p, 4), A, page) for p, page in (("x", 1), ("y", 1), ("z", 2))]
    chunks = _chunk(blocks, "heading", max_tokens=7, overlap=2)
    # Each new chunk starts with the last 2 tokens of the previous one.
    assert chunks[1].content.startswith("x2 x3")
    assert chunks[2].content.startswith("y2 y3")
    assert [c.page for c in chunks] == [1, 1, 2]
    assert all(c.token_count <= 7 for c in chunks)


def test_heading_overlap_shrinks_to_fit_the_limit() -> None:
    blocks = [Block(_words(p, 4), A, 1) for p in ("x", "y")]
    chunks = _chunk(blocks, "heading", max_tokens=6, overlap=2)
    assert chunks[1].content == "x3\n\ny0 y1 y2 y3"  # only 1 overlap token fits
    assert chunks[1].token_count == 6


def test_heading_splits_an_oversize_paragraph() -> None:
    chunks = _chunk([Block(_words("w", 25), A, 3)], "heading", max_tokens=10, overlap=2)
    assert [c.token_count for c in chunks] == [10, 10, 9]
    assert chunks[1].content.startswith("w8 w9")
    assert {c.page for c in chunks} == {3}


def test_fixed_windows_cross_sections_and_take_start_metadata() -> None:
    blocks = [Block(_words("a", 6), A, 1), Block(_words("b", 6), B, 2)]
    chunks = _chunk(blocks, "fixed", max_tokens=8, overlap=2)
    assert [c.token_count for c in chunks] == [8, 7]
    assert [(c.section_path, c.page) for c in chunks] == [(A, 1), (B, 2)]
    assert "a5" in chunks[0].content and "b0" in chunks[0].content


def test_chunk_indexes_are_sequential() -> None:
    blocks = [Block(_words("q", 30), A, None)]
    strategies: tuple[ChunkingStrategy, ...] = ("heading", "fixed")
    for strategy in strategies:
        chunks = _chunk(blocks, strategy, max_tokens=7, overlap=1)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_overlap_must_be_smaller_than_max() -> None:
    with pytest.raises(ValueError):
        _chunk([Block("a b", A, None)], "fixed", max_tokens=3, overlap=3)


@pytest.mark.parametrize("extension", [".pdf", ".docx", ".md"])
@pytest.mark.parametrize("strategy", ["heading", "fixed"])
def test_fixtures_with_real_tokenizer(
    tiktoken_cache: Path, extension: str, strategy: ChunkingStrategy
) -> None:
    kind = {".pdf": FileKind.PDF, ".docx": FileKind.DOCX, ".md": FileKind.MARKDOWN}[extension]
    parsed = parse(kind, sop_fixture(extension).read_bytes(), max_pages=150)
    tokenizer = TiktokenTokenizer("cl100k_base")
    chunks = chunk_blocks(
        parsed.blocks, strategy=strategy, tokenizer=tokenizer, max_tokens=40, overlap=8
    )
    assert chunks
    assert all(0 < c.token_count <= 40 for c in chunks)
    paths = {c.section_path for c in chunks}
    assert paths <= set(EXPECTED_SECTION_PATHS)
    if strategy == "heading":
        assert paths == set(EXPECTED_SECTION_PATHS)

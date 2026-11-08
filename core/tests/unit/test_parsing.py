from __future__ import annotations

import io
import zipfile
from types import ModuleType

import pytest
from reportlab.pdfgen.canvas import Canvas

from core.ingestion.errors import IngestionFailed
from core.ingestion.parsing import parse
from core.ingestion.types import FileKind, ParsedDocument
from testing_support import (
    EXPECTED_PDF_PAGES,
    EXPECTED_SECTION_PATHS,
    load_sop_generator,
    sop_fixture,
)

generator: ModuleType = load_sop_generator()


def _sections(document: ParsedDocument) -> list[tuple[str, ...]]:
    seen: list[tuple[str, ...]] = []
    for block in document.blocks:
        if block.section_path not in seen:
            seen.append(block.section_path)
    return seen


def _first_page(document: ParsedDocument) -> list[int | None]:
    pages: dict[tuple[str, ...], int | None] = {}
    for block in document.blocks:
        pages.setdefault(block.section_path, block.page)
    return list(pages.values())


@pytest.mark.parametrize(
    ("extension", "kind"),
    [(".pdf", FileKind.PDF), (".docx", FileKind.DOCX), (".md", FileKind.MARKDOWN)],
)
def test_fixture_sections_match_in_every_format(extension: str, kind: FileKind) -> None:
    document = parse(kind, sop_fixture(extension).read_bytes(), max_pages=150)
    assert _sections(document) == EXPECTED_SECTION_PATHS
    if kind is FileKind.PDF:
        assert document.page_count == 2
        assert _first_page(document) == EXPECTED_PDF_PAGES
    else:
        assert document.page_count is None
        assert all(block.page is None for block in document.blocks)


def test_bullets_and_tables_are_kept() -> None:
    for extension, kind in ((".docx", FileKind.DOCX), (".md", FileKind.MARKDOWN)):
        texts = [
            b.text for b in parse(kind, sop_fixture(extension).read_bytes(), max_pages=9).blocks
        ]
        assert any("- Pick a free desk on the map." in t for t in texts)
        assert any("Portal outage | Facilities desk" in t for t in texts)


def test_pdf_outline_is_used_when_present() -> None:
    # Same font size for every heading level: only the outline can give levels.
    flat_sizes = {1: 11.0, 2: 11.0, 3: 11.0}
    data = generator.build_pdf(outline=True, heading_sizes=flat_sizes)
    document = parse(FileKind.PDF, data, max_pages=150)
    assert _sections(document) == EXPECTED_SECTION_PATHS
    assert _first_page(document) == EXPECTED_PDF_PAGES


def test_pdf_without_outline_or_larger_fonts_has_no_sections() -> None:
    flat_sizes = {1: 10.0, 2: 10.0, 3: 10.0}
    document = parse(FileKind.PDF, generator.build_pdf(heading_sizes=flat_sizes), max_pages=9)
    assert _sections(document) == [()]


def test_markdown_text_before_first_heading_has_empty_path() -> None:
    document = parse(FileKind.MARKDOWN, b"Intro line.\n\n# Title\n\nBody.\n", max_pages=1)
    assert [(b.section_path, b.text) for b in document.blocks] == [
        ((), "Intro line."),
        (("Title",), "Body."),
    ]


def test_markdown_heading_levels_reset() -> None:
    text = b"# A\n\n## B\n\nb\n\n### C\n\nc\n\n## D\n\nd\n\n# E\n\ne\n"
    paths = [b.section_path for b in parse(FileKind.MARKDOWN, text, max_pages=1).blocks]
    assert paths == [("A", "B"), ("A", "B", "C"), ("A", "D"), ("E",)]


def test_page_limit_exceeded() -> None:
    with pytest.raises(IngestionFailed) as info:
        parse(FileKind.PDF, sop_fixture(".pdf").read_bytes(), max_pages=1)
    assert info.value.reason == "page limit exceeded"


def test_pdf_without_text() -> None:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, invariant=1)
    canvas.rect(100, 100, 200, 200)
    canvas.save()
    with pytest.raises(IngestionFailed) as info:
        parse(FileKind.PDF, buffer.getvalue(), max_pages=5)
    assert info.value.reason == "no extractable text"


@pytest.mark.parametrize("data", [b"", b"   \n\n", b"# Only a heading\n"])
def test_markdown_without_text(data: bytes) -> None:
    with pytest.raises(IngestionFailed) as info:
        parse(FileKind.MARKDOWN, data, max_pages=5)
    assert info.value.reason == "no extractable text"


def test_corrupt_pdf_is_a_parse_error() -> None:
    with pytest.raises(IngestionFailed) as info:
        parse(FileKind.PDF, b"%PDF-1.4\nthis is not really a pdf", max_pages=5)
    assert info.value.reason.startswith("parse error: ")


def test_corrupt_docx_is_a_parse_error() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<not-closed")
        archive.writestr("word/document.xml", "<also-broken")
    with pytest.raises(IngestionFailed) as info:
        parse(FileKind.DOCX, buffer.getvalue(), max_pages=5)
    assert info.value.reason.startswith("parse error: ")

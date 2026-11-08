from __future__ import annotations

from pathlib import Path

import pytest

from core.ingestion.errors import UnsupportedFileType
from core.ingestion.filetypes import detect_kind
from core.ingestion.types import FileKind
from testing_support import sop_fixture


@pytest.mark.parametrize(
    ("filename", "fixture", "kind"),
    [
        ("sop.pdf", ".pdf", FileKind.PDF),
        ("SOP.PDF", ".pdf", FileKind.PDF),
        ("sop.docx", ".docx", FileKind.DOCX),
        ("sop.md", ".md", FileKind.MARKDOWN),
    ],
)
def test_accepts_matching_extension_and_content(
    filename: str, fixture: str, kind: FileKind
) -> None:
    assert detect_kind(filename, sop_fixture(fixture)) is kind


@pytest.mark.parametrize(
    ("filename", "fixture"),
    [
        ("sop.pdf", ".docx"),  # extension says PDF, content is DOCX
        ("sop.docx", ".pdf"),
        ("sop.md", ".pdf"),  # binary content with NUL bytes
        ("sop.txt", ".md"),
        ("sop.markdown", ".md"),
        ("sop", ".md"),
    ],
)
def test_rejects_mismatch_or_unknown_type(filename: str, fixture: str) -> None:
    with pytest.raises(UnsupportedFileType) as info:
        detect_kind(filename, sop_fixture(fixture))
    assert info.value.details == {"allowed_extensions": [".pdf", ".docx", ".md"]}


def test_rejects_zip_without_word_body(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "fake.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(UnsupportedFileType):
        detect_kind("fake.docx", path)


def test_rejects_markdown_that_is_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "latin1.md"
    path.write_bytes("caf\xe9".encode("latin-1"))
    with pytest.raises(UnsupportedFileType):
        detect_kind("latin1.md", path)

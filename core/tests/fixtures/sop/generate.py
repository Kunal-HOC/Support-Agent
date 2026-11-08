"""Generate the fictional SOP fixtures (PDF, DOCX, Markdown).

All content is invented for testing. Run from the repo root:

    uv run python core/tests/fixtures/sop/generate.py

The same ``SOP`` definition drives all three formats, so tests can expect the
same headings everywhere. The PDF has no outline (bookmarks), so it exercises
the font-size heading heuristic; ``build_pdf(..., outline=True)`` adds one.
Output is deterministic: fixed PDF metadata and fixed DOCX zip timestamps.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from docx import Document as DocxDocument
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

HERE = Path(__file__).resolve().parent
BASENAME = "workspace_booking"
FIXED_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Section:
    level: int
    heading: str
    paragraphs: tuple[str, ...] = ()
    bullets: tuple[str, ...] = ()
    table: tuple[tuple[str, ...], ...] = ()  # first row is the header (DOCX/MD only)
    new_page: bool = False  # PDF only: start this section on a new page


@dataclass(frozen=True)
class Sop:
    sections: tuple[Section, ...] = field(default_factory=tuple)


SOP = Sop(
    sections=(
        Section(
            1,
            "Workspace Booking Procedure",
            (
                "This procedure explains how staff reserve shared desks in the fictional "
                "Riverside office.",
            ),
        ),
        Section(
            2,
            "1. Purpose",
            (
                "Shared desks are limited. Booking ahead keeps seating fair and lets the "
                "facilities team plan cleaning.",
            ),
        ),
        Section(
            2,
            "2. Scope",
            (
                "This applies to every hot desk on floors two and three. Meeting rooms use "
                "a separate procedure.",
            ),
        ),
        Section(2, "3. Booking a Desk"),
        Section(
            3,
            "3.1 Before You Book",
            (
                "Check the floor plan for quiet zones. Desks near the windows fill up "
                "first on Mondays.",
            ),
        ),
        Section(
            3,
            "3.2 Making a Booking",
            ("Use the booking portal and follow these steps.",),
            bullets=(
                "Choose the date and floor.",
                "Pick a free desk on the map.",
                "Confirm and keep the booking reference.",
            ),
        ),
        Section(
            2,
            "4. Cancellations",
            (
                "Cancel at least two hours before the booking starts so the desk returns "
                "to the pool. Three missed bookings in a month pause booking rights for one "
                "week.",
            ),
            new_page=True,
        ),
        Section(
            2,
            "5. Escalation",
            ("If the portal is down, contact the facilities desk.",),
            table=(
                ("Issue", "Contact"),
                ("Portal outage", "Facilities desk"),
                ("Broken equipment", "Service desk"),
            ),
        ),
    )
)

# Font sizes per heading level, and for body text (PDF only).
PDF_HEADING_SIZES = {1: 20.0, 2: 15.0, 3: 12.5}
PDF_BODY_SIZE = 10.0


def build_pdf(
    sop: Sop = SOP,
    *,
    outline: bool = False,
    heading_sizes: dict[int, float] | None = None,
) -> bytes:
    """Render ``sop`` as a text PDF. ``outline`` adds bookmarks for each heading."""
    sizes = heading_sizes or PDF_HEADING_SIZES
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    canvas.setTitle("Workspace Booking Procedure")
    canvas.setAuthor("Support Agent test fixtures")
    width, height = A4
    margin = 60.0
    usable = width - 2 * margin
    y = height - margin

    def write_line(text: str, font: str, size: float) -> None:
        nonlocal y
        if y < margin + size:
            canvas.showPage()
            y = height - margin
        canvas.setFont(font, size)
        canvas.drawString(margin, y, text)
        y -= size * 1.4

    for index, section in enumerate(sop.sections):
        if section.new_page and y < height - margin:
            canvas.showPage()
            y = height - margin
        size = sizes[section.level]
        if outline:
            key = f"s{index}"
            canvas.bookmarkPage(key, fit="XYZ", top=y + size)
            canvas.addOutlineEntry(section.heading, key, level=section.level - 1)
        y -= 4
        write_line(section.heading, "Helvetica-Bold", size)
        for paragraph in section.paragraphs:
            for line in simpleSplit(paragraph, "Helvetica", PDF_BODY_SIZE, usable):
                write_line(line, "Helvetica", PDF_BODY_SIZE)
            y -= PDF_BODY_SIZE  # paragraph gap
        for bullet in section.bullets:
            write_line(f"- {bullet}", "Helvetica", PDF_BODY_SIZE)
        if section.bullets:
            y -= PDF_BODY_SIZE
    canvas.save()
    return buffer.getvalue()


def build_docx(sop: Sop = SOP) -> bytes:
    """Render ``sop`` as DOCX with Heading N styles, bullets and tables."""
    document = DocxDocument()
    props = document.core_properties
    props.title = "Workspace Booking Procedure"
    props.author = "Support Agent test fixtures"
    props.created = FIXED_TIME
    props.modified = FIXED_TIME
    props.last_modified_by = "Support Agent test fixtures"
    props.revision = 1
    for section in sop.sections:
        document.add_heading(section.heading, level=section.level)
        for paragraph in section.paragraphs:
            document.add_paragraph(paragraph)
        for bullet in section.bullets:
            document.add_paragraph(bullet, style="List Bullet")
        if section.table:
            table = document.add_table(rows=len(section.table), cols=len(section.table[0]))
            for row_cells, row_values in zip(table.rows, section.table, strict=True):
                for cell, value in zip(row_cells.cells, row_values, strict=True):
                    cell.text = value
    raw = io.BytesIO()
    document.save(raw)
    return _fix_zip_timestamps(raw.getvalue())


def build_markdown(sop: Sop = SOP) -> str:
    lines: list[str] = []
    for section in sop.sections:
        lines += [f"{'#' * section.level} {section.heading}", ""]
        for paragraph in section.paragraphs:
            lines += [paragraph, ""]
        if section.bullets:
            lines += [f"- {bullet}" for bullet in section.bullets] + [""]
        if section.table:
            header, *rows = section.table
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join("---" for _ in header) + " |")
            lines += ["| " + " | ".join(row) + " |" for row in rows]
            lines.append("")
    return "\n".join(lines)


def _fix_zip_timestamps(data: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            info = zipfile.ZipInfo(item.filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, source.read(item.filename))
    return out.getvalue()


def main() -> None:
    (HERE / f"{BASENAME}.pdf").write_bytes(build_pdf())
    (HERE / f"{BASENAME}.docx").write_bytes(build_docx())
    (HERE / f"{BASENAME}.md").write_text(build_markdown(), encoding="utf-8")
    print(f"Wrote {BASENAME}.pdf, .docx and .md to {HERE}")


if __name__ == "__main__":
    main()

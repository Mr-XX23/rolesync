"""Render one neutral document model to docx, pptx, xlsx, pdf or Markdown.

The model is deliberately small (a title and sections of paragraphs, bullets and a table),
so an agent can describe any business document once and the rep can pick the format.
Inline ``**bold**`` is honoured where the format has bold text; other Markdown marks are
dropped outside Markdown output.
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Cell = str | int | float | None
DocumentFormat = Literal["docx", "pptx", "xlsx", "pdf", "md"]

MIME_TYPES: dict[str, str] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "md": "text/markdown",
}
FORMAT_LABELS: dict[str, str] = {
    "docx": "Word document",
    "pptx": "PowerPoint presentation",
    "xlsx": "Excel workbook",
    "pdf": "PDF",
    "md": "Markdown document",
}

# Unicode-capable fonts for PDFs, tried in order (the Docker image ships DejaVu).
_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", None),
)


@dataclass(frozen=True, slots=True)
class Table:
    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class Section:
    heading: str | None = None
    paragraphs: tuple[str, ...] = ()
    bullets: tuple[str, ...] = ()
    table: Table | None = None


@dataclass(frozen=True, slots=True)
class Document:
    title: str
    subtitle: str | None = None
    sections: tuple[Section, ...] = field(default_factory=tuple)


def render(document: Document, fmt: DocumentFormat, *, font_path: Path | None = None) -> bytes:
    if fmt == "docx":
        return _docx(document)
    if fmt == "pptx":
        return _pptx(document)
    if fmt == "xlsx":
        return _xlsx(document)
    if fmt == "pdf":
        return _pdf(document, font_path)
    if fmt == "md":
        return markdown(document).encode("utf-8")
    raise ValueError(f"unsupported format {fmt!r}")


# ----------------------------------------------------------------------------- text helpers

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MARKS = re.compile(r"(?<!\w)[*_`]{1,2}(?=\S)|(?<=\S)[*_`]{1,2}(?!\w)")


def plain(text: str) -> str:
    """Text without inline Markdown marks."""
    return _MARKS.sub("", _BOLD.sub(r"\1", text))


def bold_runs(text: str) -> list[tuple[str, bool]]:
    """``[(text, is_bold)]`` for ``**bold**`` spans; other marks are removed."""
    runs: list[tuple[str, bool]] = []
    position = 0
    for match in _BOLD.finditer(text):
        if match.start() > position:
            runs.append((_MARKS.sub("", text[position : match.start()]), False))
        runs.append((_MARKS.sub("", match.group(1)), True))
        position = match.end()
    if position < len(text):
        runs.append((_MARKS.sub("", text[position:]), False))
    return [run for run in runs if run[0]]


def cell_text(value: Cell) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return str(value)


def _chunks(items: Sequence[str], size: int) -> list[Sequence[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)] or [[]]


# ----------------------------------------------------------------------------- markdown


def markdown(document: Document) -> str:
    lines = [f"# {document.title}"]
    if document.subtitle:
        lines += ["", f"_{document.subtitle}_"]
    for section in document.sections:
        if section.heading:
            lines += ["", f"## {section.heading}"]
        for paragraph in section.paragraphs:
            lines += ["", paragraph]
        if section.bullets:
            lines.append("")
            lines += [f"- {bullet}" for bullet in section.bullets]
        if section.table:
            lines += ["", _md_row(section.table.columns), _md_row(["---"] * len(section.table.columns))]
            lines += [_md_row([cell_text(cell) for cell in row]) for row in section.table.rows]
    return "\n".join(lines).strip() + "\n"


def _md_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |"


# ----------------------------------------------------------------------------- docx


def _docx(document: Document) -> bytes:
    from docx import Document as WordDocument

    word = WordDocument()
    word.core_properties.title = document.title[:255]
    word.add_heading(plain(document.title), level=0)
    if document.subtitle:
        word.add_paragraph(plain(document.subtitle), style="Subtitle")
    for section in document.sections:
        if section.heading:
            word.add_heading(plain(section.heading), level=1)
        for text in section.paragraphs:
            paragraph = word.add_paragraph()
            for run_text, is_bold in bold_runs(text):
                paragraph.add_run(run_text).bold = is_bold
        for text in section.bullets:
            paragraph = word.add_paragraph(style="List Bullet")
            for run_text, is_bold in bold_runs(text):
                paragraph.add_run(run_text).bold = is_bold
        if section.table:
            columns = section.table.columns
            table = word.add_table(rows=1, cols=len(columns))
            table.style = "Table Grid"
            for index, name in enumerate(columns):
                cell = table.rows[0].cells[index]
                cell.text = ""
                cell.paragraphs[0].add_run(plain(name)).bold = True
            for row in section.table.rows:
                cells = table.add_row().cells
                for index in range(len(columns)):
                    cells[index].text = cell_text(row[index]) if index < len(row) else ""
            word.add_paragraph()
    buffer = io.BytesIO()
    word.save(buffer)
    return buffer.getvalue()


# ----------------------------------------------------------------------------- pptx

_LINES_PER_SLIDE = 7
_ROWS_PER_SLIDE = 12


def _pptx(document: Document) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    deck = Presentation()
    deck.core_properties.title = document.title[:255]
    cover = deck.slides.add_slide(deck.slide_layouts[0])
    cover.shapes.title.text = plain(document.title)
    if document.subtitle and len(cover.placeholders) > 1:
        cover.placeholders[1].text = plain(document.subtitle)

    for section in document.sections:
        heading = plain(section.heading or document.title)
        lines = [plain(text) for text in (*section.paragraphs, *section.bullets)]
        if lines or not section.table:
            for page, chunk in enumerate(_chunks(lines, _LINES_PER_SLIDE)):
                slide = deck.slides.add_slide(deck.slide_layouts[1])
                slide.shapes.title.text = heading if page == 0 else f"{heading} (continued)"
                body = slide.placeholders[1].text_frame
                body.clear()
                for index, line in enumerate(chunk):
                    paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
                    paragraph.text = line[:400]
                    paragraph.font.size = Pt(18 if len(chunk) <= 5 else 16)
        if section.table:
            columns = section.table.columns
            rows = list(section.table.rows) or [()]
            for page in range(0, len(rows), _ROWS_PER_SLIDE):
                chunk = rows[page : page + _ROWS_PER_SLIDE]
                slide = deck.slides.add_slide(deck.slide_layouts[5])
                slide.shapes.title.text = heading if page == 0 else f"{heading} (continued)"
                width = deck.slide_width - Inches(1)
                shape = slide.shapes.add_table(
                    len(chunk) + 1, len(columns), Inches(0.5), Inches(1.6), width, Inches(0.4) * (len(chunk) + 1)
                )
                table = shape.table
                for index, name in enumerate(columns):
                    table.cell(0, index).text = plain(name)
                for row_index, row in enumerate(chunk, start=1):
                    for index in range(len(columns)):
                        table.cell(row_index, index).text = cell_text(row[index]) if index < len(row) else ""
                for row_cells in table.rows:
                    for cell in row_cells.cells:
                        for paragraph in cell.text_frame.paragraphs:
                            paragraph.font.size = Pt(12)
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


# ----------------------------------------------------------------------------- xlsx

_SHEET_UNSAFE = re.compile(r"[\[\]:*?/\\]")


def _xlsx(document: Document) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    used_names: set[str] = set()

    def sheet_name(wanted: str) -> str:
        base = _SHEET_UNSAFE.sub(" ", plain(wanted)).strip()[:31] or "Sheet"
        name, counter = base, 2
        while name.lower() in used_names:
            suffix = f" ({counter})"
            name, counter = base[: 31 - len(suffix)] + suffix, counter + 1
        used_names.add(name.lower())
        return name

    has_text = document.subtitle or any(s.paragraphs or s.bullets or (s.heading and not s.table) for s in document.sections)
    first = workbook.active
    sheets_used = 0
    if has_text:
        sheet = first
        sheet.title = sheet_name("Overview")
        sheets_used = 1
        sheet.append([plain(document.title)])
        sheet["A1"].font = Font(bold=True, size=14)
        if document.subtitle:
            sheet.append([plain(document.subtitle)])
        for section in document.sections:
            if not (section.paragraphs or section.bullets or section.heading):
                continue
            sheet.append([])
            if section.heading:
                sheet.append([plain(section.heading)])
                sheet.cell(sheet.max_row, 1).font = Font(bold=True)
            for text in section.paragraphs:
                sheet.append([plain(text)])
                sheet.cell(sheet.max_row, 1).alignment = Alignment(wrap_text=True, vertical="top")
            for text in section.bullets:
                sheet.append([f"• {plain(text)}"])
        sheet.column_dimensions["A"].width = 100

    header_fill = PatternFill("solid", fgColor="DDE7F3")
    for position, section in enumerate(document.sections, start=1):
        if not section.table:
            continue
        sheet = first if sheets_used == 0 else workbook.create_sheet()
        sheets_used += 1
        sheet.title = sheet_name(section.heading or f"Table {position}")
        sheet.append([plain(name) for name in section.table.columns])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = header_fill
        for row in section.table.rows:
            sheet.append([_xlsx_value(cell) for cell in row[: len(section.table.columns)]])
        sheet.freeze_panes = "A2"
        for index, name in enumerate(section.table.columns, start=1):
            longest = max([len(plain(name)), *(len(cell_text(row[index - 1])) for row in section.table.rows if index - 1 < len(row))])
            sheet.column_dimensions[sheet.cell(1, index).column_letter].width = min(60, max(10, longest + 2))
    if sheets_used == 0:
        first.title = sheet_name("Overview")
        first.append([plain(document.title)])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _xlsx_value(value: Cell) -> Cell:
    if isinstance(value, str):
        text = value.strip()
        # Keep numbers the model wrote as text numeric, so sums and sorting work in Excel.
        if re.fullmatch(r"-?\d{1,15}(\.\d+)?", text):
            return float(text) if "." in text else int(text)
        return value[:32_000]
    return value


# ----------------------------------------------------------------------------- pdf


def _pdf(document: Document, font_path: Path | None) -> bytes:
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    pdf = FPDF(format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(True, margin=18)
    pdf.set_title(document.title[:255])
    family, unicode_font = _pdf_fonts(pdf, font_path)

    def text(value: str) -> str:
        value = plain(value)
        return value if unicode_font else value.replace("•", "-").encode("latin-1", "replace").decode("latin-1")

    pdf.add_page()
    pdf.set_font(family, "B", 20)
    pdf.multi_cell(0, 10, text(document.title), new_x="LMARGIN", new_y="NEXT")
    if document.subtitle:
        pdf.set_font(family, "", 12)
        pdf.set_text_color(90, 90, 90)
        pdf.multi_cell(0, 7, text(document.subtitle), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    for section in document.sections:
        pdf.ln(4)
        if section.heading:
            pdf.set_font(family, "B", 14)
            pdf.multi_cell(0, 8, text(section.heading), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        pdf.set_font(family, "", 11)
        for paragraph in section.paragraphs:
            pdf.multi_cell(0, 6, text(paragraph), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        for bullet in section.bullets:
            pdf.multi_cell(0, 6, text(f"•  {bullet}"), new_x="LMARGIN", new_y="NEXT")
        if section.table:
            pdf.ln(2)
            pdf.set_font(family, "", 10)
            heading_style = FontFace(emphasis="BOLD", fill_color=(221, 231, 243))
            with pdf.table(headings_style=heading_style, line_height=6, text_align="LEFT") as table:
                header = table.row()
                for name in section.table.columns:
                    header.cell(text(name))
                for row in section.table.rows:
                    cells = table.row()
                    for index in range(len(section.table.columns)):
                        cells.cell(text(cell_text(row[index])) if index < len(row) else "")
    return bytes(pdf.output())


def _pdf_fonts(pdf, font_path: Path | None) -> tuple[str, bool]:
    candidates = [(str(font_path), None)] if font_path else []
    candidates += list(_FONT_CANDIDATES)
    for regular, bold in candidates:
        if regular and Path(regular).is_file():
            pdf.add_font("Body", "", regular)
            pdf.add_font("Body", "B", bold if bold and Path(bold).is_file() else regular)
            return "Body", True
    return "Helvetica", False

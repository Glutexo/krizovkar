"""Vektorové vykreslení křížovkové mřížky do PDF."""

from __future__ import annotations

from functools import cache
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.sax.saxutils import escape

import pymupdf_fonts
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A0, A1, A2, A3, A4, A5, A6, LEGAL, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from krizovkar.model import CrosswordGrid, EmptyCell, LegendCell, SecretCell

PAGE_MARGIN = 15 * mm
MAX_CELL_SIZE = 12 * mm
INNER_LINE_WIDTH = 0.5
OUTER_LINE_WIDTH = 1.25
LETTER_FONT = "Helvetica-Bold"
LETTER_SIZE_RATIO = 0.58
LETTER_BASELINE_OFFSET = 0.35
SECRET_FILL_GRAY = 0.85
LEGEND_FILL_GRAY = 0.93
LEGEND_FONT = "KrizovkarNotoSans"
LEGEND_MAX_FONT_SIZE = 6.0
LEGEND_MIN_FONT_SIZE = 2.0
LEGEND_FONT_STEP = 0.25
LEGEND_PADDING = 1.5
LEGEND_SEPARATOR_LINE_WIDTH = 0.4
EMPTY_SYMBOL_INSET_RATIO = 0.3
EMPTY_SYMBOL_LINE_WIDTH = 0.65
DEFAULT_PAGE_FORMAT = "A4"
SUPPORTED_PAGE_FORMATS = (
    "A0",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A6",
    "LETTER",
    "LEGAL",
)
_PAGE_SIZES = {
    "A0": A0,
    "A1": A1,
    "A2": A2,
    "A3": A3,
    "A4": A4,
    "A5": A5,
    "A6": A6,
    "LETTER": LETTER,
    "LEGAL": LEGAL,
}


class RenderError(RuntimeError):
    """PDF nelze bezpečně vytvořit."""


@cache
def _register_legend_font() -> None:
    font_data = pymupdf_fonts.fontbuffers["notos"]()
    pdfmetrics.registerFont(TTFont(LEGEND_FONT, BytesIO(font_data)))


def _draw_fitted_legend_text(
    pdf: Canvas,
    text: str,
    left: float,
    bottom: float,
    width: float,
    height: float,
) -> None:
    _register_legend_font()
    maximum = min(LEGEND_MAX_FONT_SIZE, height * 0.45)
    minimum = min(LEGEND_MIN_FONT_SIZE, maximum)
    font_size = maximum

    while font_size >= minimum:
        style = ParagraphStyle(
            name="legend",
            fontName=LEGEND_FONT,
            fontSize=font_size,
            leading=font_size * 1.05,
            alignment=TA_CENTER,
            splitLongWords=1,
            spaceBefore=0,
            spaceAfter=0,
        )
        paragraph = Paragraph(escape(text), style)
        _, text_height = paragraph.wrap(width, height)
        if text_height <= height:
            paragraph.drawOn(
                pdf,
                left,
                bottom + (height - text_height) / 2,
            )
            return
        font_size -= LEGEND_FONT_STEP

    raise RenderError(f"text legendy je příliš dlouhý pro buňku: {text!r}")


def _draw_legend_cell(
    pdf: Canvas,
    cell: LegendCell,
    left: float,
    bottom: float,
    size: float,
) -> None:
    pdf.setFillGray(LEGEND_FILL_GRAY)
    pdf.rect(left, bottom, size, size, stroke=0, fill=1)

    if len(cell.texts) == 2:
        pdf.setStrokeColorRGB(0, 0, 0)
        pdf.setLineWidth(LEGEND_SEPARATOR_LINE_WIDTH)
        pdf.line(left, bottom + size / 2, left + size, bottom + size / 2)
        sections = (
            (cell.texts[0], bottom + size / 2, size / 2),
            (cell.texts[1], bottom, size / 2),
        )
    else:
        sections = ((cell.texts[0], bottom, size),)

    padding = min(LEGEND_PADDING, size * 0.08)
    for text, section_bottom, section_height in sections:
        _draw_fitted_legend_text(
            pdf,
            text,
            left + padding,
            section_bottom + padding,
            size - 2 * padding,
            section_height - 2 * padding,
        )


def _draw_empty_cell(
    pdf: Canvas,
    left: float,
    bottom: float,
    size: float,
) -> None:
    inset = size * EMPTY_SYMBOL_INSET_RATIO
    pdf.saveState()
    pdf.setStrokeColorRGB(0.25, 0.25, 0.25)
    pdf.setLineWidth(EMPTY_SYMBOL_LINE_WIDTH)
    pdf.setLineCap(1)
    pdf.line(
        left + inset,
        bottom + inset,
        left + size - inset,
        bottom + size - inset,
    )
    pdf.line(
        left + inset,
        bottom + size - inset,
        left + size - inset,
        bottom + inset,
    )
    pdf.restoreState()


def resolve_page_size(page_format: str) -> tuple[float, float]:
    """Vrátí rozměr stránky pro podporovaný název formátu."""

    normalized = page_format.upper()
    try:
        return _PAGE_SIZES[normalized]
    except KeyError as error:
        supported = ", ".join(SUPPORTED_PAGE_FORMATS)
        raise RenderError(
            f"nepodporovaný formát stránky {page_format!r}; "
            f"podporované formáty: {supported}"
        ) from error


def _write_pdf(
    crossword: CrosswordGrid,
    target: Path,
    page_size: tuple[float, float],
) -> None:
    page_width, page_height = page_size
    width = crossword.grid.width
    height = crossword.grid.height
    cell_size = min(
        MAX_CELL_SIZE,
        (page_width - 2 * PAGE_MARGIN) / width,
        (page_height - 2 * PAGE_MARGIN) / height,
    )
    grid_width = width * cell_size
    grid_height = height * cell_size
    left = (page_width - grid_width) / 2
    bottom = (page_height - grid_height) / 2

    pdf = Canvas(str(target), pagesize=page_size, pageCompression=1)
    pdf.setTitle(f"Křížovkář – mřížka {width} × {height}")
    pdf.setCreator("Křížovkář")
    subject = (
        "Křížovková mřížka s písmeny"
        if crossword.grid.cells is not None
        else "Prázdná křížovková mřížka"
    )
    pdf.setSubject(subject)
    pdf.setStrokeColorRGB(0, 0, 0)

    if crossword.grid.cells is not None:
        pdf.setFillGray(SECRET_FILL_GRAY)
        for row_index, row in enumerate(crossword.grid.cells):
            cell_bottom = bottom + grid_height - (row_index + 1) * cell_size
            for column_index, cell in enumerate(row):
                if isinstance(cell, SecretCell):
                    cell_left = left + column_index * cell_size
                    pdf.rect(
                        cell_left,
                        cell_bottom,
                        cell_size,
                        cell_size,
                        stroke=0,
                        fill=1,
                    )
                elif isinstance(cell, LegendCell):
                    cell_left = left + column_index * cell_size
                    _draw_legend_cell(
                        pdf,
                        cell,
                        cell_left,
                        cell_bottom,
                        cell_size,
                    )
                elif isinstance(cell, EmptyCell):
                    cell_left = left + column_index * cell_size
                    _draw_empty_cell(
                        pdf,
                        cell_left,
                        cell_bottom,
                        cell_size,
                    )

        font_size = cell_size * LETTER_SIZE_RATIO
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont(LETTER_FONT, font_size)
        for row_index, row in enumerate(crossword.grid.cells):
            center_y = bottom + grid_height - (row_index + 0.5) * cell_size
            baseline = center_y - font_size * LETTER_BASELINE_OFFSET
            for column_index, cell in enumerate(row):
                if isinstance(cell, (LegendCell, EmptyCell)):
                    continue
                center_x = left + (column_index + 0.5) * cell_size
                pdf.drawCentredString(center_x, baseline, cell.value)

    pdf.setLineWidth(INNER_LINE_WIDTH)
    for column in range(1, width):
        x = left + column * cell_size
        pdf.line(x, bottom, x, bottom + grid_height)
    for row in range(1, height):
        y = bottom + row * cell_size
        pdf.line(left, y, left + grid_width, y)

    pdf.setLineWidth(OUTER_LINE_WIDTH)
    pdf.rect(left, bottom, grid_width, grid_height, stroke=1, fill=0)
    pdf.showPage()
    pdf.save()


def render_pdf(
    crossword: CrosswordGrid,
    output: str | Path,
    *,
    overwrite: bool = False,
    page_format: str = DEFAULT_PAGE_FORMAT,
) -> Path:
    """Vykreslí křížovku atomicky do jednostránkového PDF."""

    output_path = Path(output)
    page_size = resolve_page_size(page_format)
    if output_path.exists() and not overwrite:
        raise RenderError(f"výstupní soubor již existuje: {output_path}")

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            prefix=f".{output_path.name}.",
            suffix=".pdf",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)

        _write_pdf(crossword, temporary_path, page_size)
        temporary_path.replace(output_path)
    except OSError as error:
        detail = error.strerror or str(error)
        raise RenderError(f"PDF nelze zapsat ({output_path}): {detail}") from error
    finally:
        if "temporary_path" in locals():
            temporary_path.unlink(missing_ok=True)

    return output_path

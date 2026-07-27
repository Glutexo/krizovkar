"""Vektorové vykreslení křížovkové mřížky do PDF."""

from __future__ import annotations

import re
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

from krizovkar.model import CrosswordGrid, EmptyCell, HelpCell, LegendCell, SecretCell
from krizovkar.typography import mark_czech_hyphenation, protect_czech_prepositions

PAGE_MARGIN = 15 * mm
MAX_CELL_SIZE = 12 * mm
INNER_LINE_WIDTH = 0.5
OUTER_LINE_WIDTH = 1.25
LETTER_FONT = "KrizovkarNotoSansBold"
LETTER_SIZE_RATIO = 0.58
LETTER_BASELINE_OFFSET = 0.35
SECRET_FILL_GRAY = 0.85
LEGEND_FILL_GRAY = 0.93
HELP_FILL_GRAY = 0.93
TEXT_CELL_FONT = "KrizovkarNotoSans"
TEXT_CELL_BOLD_FONT = "KrizovkarNotoSansBold"
TEXT_CELL_MAX_FONT_SIZE = 6.0
TEXT_CELL_MIN_FONT_SIZE = 2.0
TEXT_CELL_FONT_STEP = 0.25
TEXT_CELL_PADDING = 1.5
_UNBREAKABLE_TEXT = re.compile(r"[^ \t\r\n]+")
LEGEND_SEPARATOR_LINE_WIDTH = 0.4
LEGEND_ARROW_LINE_WIDTH = 0.75
LEGEND_ARROW_LENGTH_RATIO = 0.18
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
def _register_text_cell_fonts() -> None:
    regular_data = pymupdf_fonts.fontbuffers["notos"]()
    bold_data = pymupdf_fonts.fontbuffers["notosbo"]()
    pdfmetrics.registerFont(TTFont(TEXT_CELL_FONT, BytesIO(regular_data)))
    pdfmetrics.registerFont(TTFont(TEXT_CELL_BOLD_FONT, BytesIO(bold_data)))
    pdfmetrics.registerFontFamily(
        TEXT_CELL_FONT,
        normal=TEXT_CELL_FONT,
        bold=TEXT_CELL_BOLD_FONT,
    )


def _mark_overlong_czech_text(
    text: str,
    width: float,
    font_size: float,
) -> str:
    """Vyznačí dělení jen v částech, které se nevejdou na řádek."""

    def mark_if_overlong(match: re.Match[str]) -> str:
        unbreakable_text = match.group()
        if (
            pdfmetrics.stringWidth(
                unbreakable_text,
                TEXT_CELL_FONT,
                font_size,
            )
            <= width
        ):
            return unbreakable_text
        return mark_czech_hyphenation(unbreakable_text)

    return _UNBREAKABLE_TEXT.sub(mark_if_overlong, text)


def _text_fits_without_hyphenation(
    text: str,
    width: float,
    font_size: float,
) -> bool:
    """Zjistí, zda se každá nezalomitelná část vejde na řádek."""

    return all(
        pdfmetrics.stringWidth(
            match.group(),
            TEXT_CELL_FONT,
            font_size,
        )
        <= width
        for match in _UNBREAKABLE_TEXT.finditer(text)
    )


def _draw_fitted_text(
    pdf: Canvas,
    text: str,
    left: float,
    bottom: float,
    width: float,
    height: float,
    *,
    prefix: str | None = None,
) -> None:
    _register_text_cell_fonts()
    maximum = min(TEXT_CELL_MAX_FONT_SIZE, height * 0.45)
    minimum = min(TEXT_CELL_MIN_FONT_SIZE, maximum)
    protected_text = protect_czech_prepositions(text)

    def draw_if_fits(content_text: str, font_size: float) -> bool:
        content = escape(content_text)
        if prefix is not None:
            content = f"<b>{escape(prefix)}</b> {content}"
        style = ParagraphStyle(
            name="text-cell",
            fontName=TEXT_CELL_FONT,
            fontSize=font_size,
            leading=font_size * 1.05,
            alignment=TA_CENTER,
            hyphenationLang="",
            splitLongWords=0,
            spaceBefore=0,
            spaceAfter=0,
        )
        paragraph = Paragraph(content, style)
        _, text_height = paragraph.wrap(width, height)
        if text_height <= height:
            paragraph.drawOn(
                pdf,
                left,
                bottom + (height - text_height) / 2,
            )
            return True
        return False

    # Jeden typografický krok zmenšení je méně rušivý než dělení slov.
    whole_word_minimum = max(minimum, maximum - TEXT_CELL_FONT_STEP)
    font_size = maximum
    while font_size >= whole_word_minimum:
        if _text_fits_without_hyphenation(
            protected_text,
            width,
            font_size,
        ) and draw_if_fits(protected_text, font_size):
            return
        font_size -= TEXT_CELL_FONT_STEP

    font_size = maximum
    while font_size >= minimum:
        marked_text = _mark_overlong_czech_text(
            protected_text,
            width,
            font_size,
        )
        if draw_if_fits(marked_text, font_size):
            return
        font_size -= TEXT_CELL_FONT_STEP

    raise RenderError(f"text je příliš dlouhý pro buňku: {text!r}")


def _draw_legend_cell(
    pdf: Canvas,
    cell: LegendCell,
    left: float,
    bottom: float,
    size: float,
) -> None:
    pdf.setFillGray(LEGEND_FILL_GRAY)
    pdf.rect(left, bottom, size, size, stroke=0, fill=1)

    section_height = size / len(cell.texts)
    if len(cell.texts) > 1:
        pdf.setStrokeColorRGB(0, 0, 0)
        pdf.setLineWidth(LEGEND_SEPARATOR_LINE_WIDTH)
        for section_index in range(1, len(cell.texts)):
            separator_y = bottom + size - section_index * section_height
            pdf.line(left, separator_y, left + size, separator_y)

    sections = tuple(
        (
            text,
            bottom + size - (section_index + 1) * section_height,
            section_height,
        )
        for section_index, text in enumerate(cell.texts)
    )

    for section_index, (text, section_bottom, section_height) in enumerate(
        sections
    ):
        padding = min(TEXT_CELL_PADDING, size * 0.08, section_height * 0.15)
        _draw_fitted_text(
            pdf,
            text,
            left + padding,
            section_bottom + padding,
            size - 2 * padding,
            section_height - 2 * padding,
        )
        if section_index < len(cell.arrows):
            _draw_legend_arrow(
                pdf,
                cell.arrows[section_index],
                left,
                bottom,
                size,
                section_bottom,
                section_height,
            )


def _draw_legend_arrow(
    pdf: Canvas,
    direction: str,
    left: float,
    bottom: float,
    size: float,
    section_bottom: float,
    section_height: float,
) -> None:
    length = size * LEGEND_ARROW_LENGTH_RATIO
    head = length * 0.38
    inset = max(INNER_LINE_WIDTH, size * 0.04)

    pdf.saveState()
    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.setLineWidth(LEGEND_ARROW_LINE_WIDTH)
    pdf.setLineCap(1)
    pdf.setLineJoin(1)

    if direction == "right":
        tip_x = left + size - inset
        tip_y = section_bottom + section_height * 0.22
        pdf.line(tip_x - length, tip_y, tip_x, tip_y)
        pdf.line(tip_x, tip_y, tip_x - head, tip_y + head)
        pdf.line(tip_x, tip_y, tip_x - head, tip_y - head)
    else:
        tip_x = left + size * 0.78
        tip_y = bottom + inset
        pdf.line(tip_x, tip_y + length, tip_x, tip_y)
        pdf.line(tip_x, tip_y, tip_x - head, tip_y + head)
        pdf.line(tip_x, tip_y, tip_x + head, tip_y + head)

    pdf.restoreState()


def _draw_help_cell(
    pdf: Canvas,
    cell: HelpCell,
    left: float,
    bottom: float,
    size: float,
) -> None:
    pdf.setFillGray(HELP_FILL_GRAY)
    pdf.rect(left, bottom, size, size, stroke=0, fill=1)
    padding = min(TEXT_CELL_PADDING, size * 0.08)
    _draw_fitted_text(
        pdf,
        ", ".join(cell.words),
        left + padding,
        bottom + padding,
        size - 2 * padding,
        size - 2 * padding,
        prefix="Pomůcka:",
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
                elif isinstance(cell, HelpCell):
                    cell_left = left + column_index * cell_size
                    _draw_help_cell(
                        pdf,
                        cell,
                        cell_left,
                        cell_bottom,
                        cell_size,
                    )

        font_size = cell_size * LETTER_SIZE_RATIO
        _register_text_cell_fonts()
        pdf.setFillColorRGB(0, 0, 0)
        for row_index, row in enumerate(crossword.grid.cells):
            center_y = bottom + grid_height - (row_index + 0.5) * cell_size
            for column_index, cell in enumerate(row):
                if isinstance(cell, (LegendCell, EmptyCell, HelpCell)):
                    continue
                center_x = left + (column_index + 0.5) * cell_size
                text_width = pdfmetrics.stringWidth(
                    cell.value,
                    LETTER_FONT,
                    font_size,
                )
                fitted_size = min(
                    font_size,
                    font_size * cell_size * 0.8 / text_width,
                )
                baseline = center_y - fitted_size * LETTER_BASELINE_OFFSET
                pdf.setFont(LETTER_FONT, fitted_size)
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

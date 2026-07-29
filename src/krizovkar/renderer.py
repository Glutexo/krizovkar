"""Vektorové vykreslení křížovkové mřížky do PDF."""

from __future__ import annotations

import re
from functools import cache
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO
from xml.sax.saxutils import escape

import pymupdf_fonts
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A0, A1, A2, A3, A4, A5, A6, LEGAL, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from krizovkar.localization import system_error_message
from krizovkar.model import (
    CrosswordGrid,
    EmptyCell,
    ExternalClue,
    Grid,
    HelpCell,
    LegendArrow,
    LegendCell,
    LetterCell,
    SecretArrow,
    SecretCell,
    SecretPrompt,
    SecretPromptPlacement,
)
from krizovkar.typography import mark_czech_hyphenation, protect_czech_prepositions

PAGE_MARGIN = 15 * mm
MAX_CELL_SIZE = 12 * mm
INNER_LINE_WIDTH = 0.75
STRONG_LINE_WIDTH = 1.25
LETTER_FONT = "KrizovkarNotoSansBold"
LETTER_SIZE_RATIO = 0.58
LETTER_BASELINE_OFFSET = 0.35
SECRET_FILL_GRAY = 0.85
SECRET_BEAK_DEPTH_RATIO = 0.28
SECRET_BEAK_BASE_RATIO = 0.82
SECRET_BEAK_NUMBERED_BASE_RATIO = 0.46
SECRET_BEAK_NUMBERED_OFFSET_RATIO = 0.18
SECRET_BEAK_LETTER_OFFSET_RATIO = 0.1
LEGEND_FILL_GRAY = 0.93
HELP_FILL_GRAY = 0.93
TEXT_CELL_FONT = "KrizovkarNotoSans"
TEXT_CELL_BOLD_FONT = "KrizovkarNotoSansBold"
NUMBER_FONT = TEXT_CELL_BOLD_FONT
NUMBER_MAX_FONT_SIZE = 7.0
NUMBER_SIZE_RATIO = 0.2
NUMBER_INSET_RATIO = 0.07
TEXT_CELL_MAX_FONT_SIZE = 6.0
TEXT_CELL_MIN_FONT_SIZE = 2.0
TEXT_CELL_FONT_STEP = 0.25
TEXT_CELL_PADDING = 1.5
_UNBREAKABLE_TEXT = re.compile(r"[^ \t\r\n]+")
LEGEND_SEPARATOR_LINE_WIDTH = 0.4
ARROW_LINE_WIDTH = 0.75
ARROW_LENGTH_RATIO = 0.18
ARROW_HEAD_RATIO = 0.38
EMPTY_SYMBOL_INSET_RATIO = 0.3
EMPTY_SYMBOL_LINE_WIDTH = 0.65
EXTERNAL_CLUE_FONT_SIZE = 8.0
EXTERNAL_CLUE_LEADING = 9.6
EXTERNAL_CLUE_MIN_AREA_WIDTH = 100 * mm
EXTERNAL_CLUE_COLUMN_GAP = 6 * mm
EXTERNAL_CLUE_GRID_GAP = 7 * mm
SECRET_PROMPT_FONT_SIZE = 9.0
SECRET_PROMPT_LEADING = 11.0
SECRET_PROMPT_SPACING = 2 * mm
SECRET_PROMPT_GRID_GAP = 4 * mm
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
_ARROW_VECTORS: dict[SecretArrow, tuple[float, float]] = {
    "up": (0.0, 1.0),
    "right": (1.0, 0.0),
    "down": (0.0, -1.0),
    "left": (-1.0, 0.0),
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
    if not cell.texts:
        return

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
        if text is not None:
            padding = min(
                TEXT_CELL_PADDING,
                size * 0.08,
                section_height * 0.15,
            )
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
    direction: LegendArrow,
    left: float,
    bottom: float,
    size: float,
    section_bottom: float,
    section_height: float,
) -> None:
    length = size * ARROW_LENGTH_RATIO
    inset = max(INNER_LINE_WIDTH, size * 0.04)

    if direction == "right":
        tip_x = left + size - inset
        tip_y = section_bottom + section_height * 0.22
    else:
        tip_x = left + size * 0.78
        tip_y = bottom + inset
    _draw_arrow(pdf, direction, tip_x, tip_y, length)


def _draw_arrow(
    pdf: Canvas,
    direction: SecretArrow,
    tip_x: float,
    tip_y: float,
    length: float,
) -> None:
    direction_x, direction_y = _ARROW_VECTORS[direction]
    perpendicular_x, perpendicular_y = -direction_y, direction_x
    head = length * ARROW_HEAD_RATIO
    tail_x = tip_x - direction_x * length
    tail_y = tip_y - direction_y * length
    head_center_x = tip_x - direction_x * head
    head_center_y = tip_y - direction_y * head

    pdf.saveState()
    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.setLineWidth(ARROW_LINE_WIDTH)
    pdf.setLineCap(1)
    pdf.setLineJoin(1)
    pdf.line(tail_x, tail_y, tip_x, tip_y)
    pdf.line(
        tip_x,
        tip_y,
        head_center_x + perpendicular_x * head,
        head_center_y + perpendicular_y * head,
    )
    pdf.line(
        tip_x,
        tip_y,
        head_center_x - perpendicular_x * head,
        head_center_y - perpendicular_y * head,
    )
    pdf.restoreState()


def _secret_beak_points(
    direction: SecretArrow,
    left: float,
    bottom: float,
    size: float,
    *,
    numbered: bool = False,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    direction_x, direction_y = _ARROW_VECTORS[direction]
    perpendicular_x, perpendicular_y = -direction_y, direction_x
    base_center_x = left + size * (0.5 - direction_x * 0.5)
    base_center_y = bottom + size * (0.5 - direction_y * 0.5)
    number_conflict = numbered and direction in {"right", "down"}
    base_ratio = (
        SECRET_BEAK_NUMBERED_BASE_RATIO
        if number_conflict
        else SECRET_BEAK_BASE_RATIO
    )
    if number_conflict:
        offset = size * SECRET_BEAK_NUMBERED_OFFSET_RATIO
        if direction == "right":
            base_center_y -= offset
        else:
            base_center_x += offset

    half_base = size * base_ratio / 2
    base_start = (
        base_center_x + perpendicular_x * half_base,
        base_center_y + perpendicular_y * half_base,
    )
    tip = (
        base_center_x + direction_x * size * SECRET_BEAK_DEPTH_RATIO,
        base_center_y + direction_y * size * SECRET_BEAK_DEPTH_RATIO,
    )
    base_end = (
        base_center_x - perpendicular_x * half_base,
        base_center_y - perpendicular_y * half_base,
    )
    return base_start, tip, base_end


def _draw_secret_beak(
    pdf: Canvas,
    direction: SecretArrow,
    left: float,
    bottom: float,
    size: float,
    *,
    numbered: bool = False,
) -> None:
    base_start, tip, base_end = _secret_beak_points(
        direction,
        left,
        bottom,
        size,
        numbered=numbered,
    )
    path = pdf.beginPath()
    path.moveTo(*base_start)
    path.lineTo(*tip)
    path.lineTo(*base_end)
    path.close()

    pdf.saveState()
    pdf.setFillColorRGB(0, 0, 0)
    pdf.drawPath(path, stroke=0, fill=1)
    pdf.restoreState()


def _secret_letter_center(
    direction: SecretArrow,
    center_x: float,
    center_y: float,
    size: float,
) -> tuple[float, float]:
    direction_x, direction_y = _ARROW_VECTORS[direction]
    offset = size * SECRET_BEAK_LETTER_OFFSET_RATIO
    return (
        center_x + direction_x * offset,
        center_y + direction_y * offset,
    )


def _draw_cell_number(
    pdf: Canvas,
    number: int,
    left: float,
    bottom: float,
    size: float,
) -> None:
    _register_text_cell_fonts()
    font_size = min(NUMBER_MAX_FONT_SIZE, size * NUMBER_SIZE_RATIO)
    inset = size * NUMBER_INSET_RATIO

    pdf.saveState()
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont(NUMBER_FONT, font_size)
    pdf.drawString(
        left + inset,
        bottom + size - inset - font_size * 0.82,
        str(number),
    )
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


def _draw_letter_cell(
    pdf: Canvas,
    cell: LetterCell | SecretCell,
    center_x: float,
    center_y: float,
    cell_size: float,
    font_size: float,
) -> None:
    assert cell.value is not None
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


def _secret_prompt_paragraph(prompt: SecretPrompt) -> Paragraph:
    _register_text_cell_fonts()
    text = mark_czech_hyphenation(
        protect_czech_prepositions(prompt.text)
    )
    style = ParagraphStyle(
        name="secret-prompt",
        fontName=TEXT_CELL_FONT,
        fontSize=SECRET_PROMPT_FONT_SIZE,
        leading=SECRET_PROMPT_LEADING,
        alignment=TA_LEFT if prompt.alignment == "left" else TA_RIGHT,
        hyphenationLang="",
        splitLongWords=0,
        spaceBefore=0,
        spaceAfter=0,
    )
    return Paragraph(escape(text), style)


def _prepare_secret_prompts(
    prompts: tuple[SecretPrompt, ...],
    placement: SecretPromptPlacement,
    width: float,
    maximum_height: float,
) -> tuple[tuple[tuple[Paragraph, float], ...], float]:
    layouts: list[tuple[Paragraph, float]] = []
    for prompt in prompts:
        if prompt.placement != placement:
            continue
        paragraph = _secret_prompt_paragraph(prompt)
        _, paragraph_height = paragraph.wrap(width, maximum_height)
        layouts.append((paragraph, paragraph_height))

    total_height = sum(height for _, height in layouts)
    if layouts:
        total_height += SECRET_PROMPT_SPACING * (len(layouts) - 1)
    return tuple(layouts), total_height


def _draw_secret_prompts(
    pdf: Canvas,
    layouts: tuple[tuple[Paragraph, float], ...],
    left: float,
    bottom: float,
    height: float,
) -> None:
    top = bottom + height
    for paragraph, paragraph_height in layouts:
        paragraph_bottom = top - paragraph_height
        paragraph.drawOn(pdf, left, paragraph_bottom)
        top = paragraph_bottom - SECRET_PROMPT_SPACING


def _external_clue_paragraph(
    heading: str,
    clues: tuple[ExternalClue, ...],
) -> Paragraph:
    _register_text_cell_fonts()
    lines = []
    for clue in sorted(clues, key=lambda item: item.number):
        text = mark_czech_hyphenation(
            protect_czech_prepositions(clue.text)
        )
        lines.append(f"<b>{clue.number}.</b> {escape(text)}")
    content = f"<b>{escape(heading)}</b><br/>" + "<br/>".join(lines)
    style = ParagraphStyle(
        name="external-clues",
        fontName=TEXT_CELL_FONT,
        fontSize=EXTERNAL_CLUE_FONT_SIZE,
        leading=EXTERNAL_CLUE_LEADING,
        alignment=TA_LEFT,
        hyphenationLang="",
        splitLongWords=0,
        spaceBefore=0,
        spaceAfter=0,
    )
    return Paragraph(content, style)


def _prepare_external_clues(
    crossword: CrosswordGrid,
    page_width: float,
    page_height: float,
    provisional_grid_width: float,
) -> tuple[tuple[tuple[Paragraph, float, float], ...], float, float]:
    groups = []
    for direction, heading in (
        ("horizontal", "Vodorovně"),
        ("vertical", "Svisle"),
    ):
        clues = tuple(
            clue for clue in crossword.clues if clue.direction == direction
        )
        if clues:
            groups.append((heading, clues))
    if not groups:
        return (), 0.0, 0.0

    available_width = page_width - 2 * PAGE_MARGIN
    area_width = min(
        available_width,
        max(provisional_grid_width, EXTERNAL_CLUE_MIN_AREA_WIDTH),
    )
    total_column_gap = EXTERNAL_CLUE_COLUMN_GAP * (len(groups) - 1)
    column_width = (area_width - total_column_gap) / len(groups)
    maximum_height = page_height - 2 * PAGE_MARGIN
    layouts: list[tuple[Paragraph, float, float]] = []
    clue_height = 0.0
    for group_index, (heading, clues) in enumerate(groups):
        paragraph = _external_clue_paragraph(heading, clues)
        _, paragraph_height = paragraph.wrap(column_width, maximum_height)
        offset = group_index * (column_width + EXTERNAL_CLUE_COLUMN_GAP)
        layouts.append((paragraph, offset, paragraph_height))
        clue_height = max(clue_height, paragraph_height)
    return tuple(layouts), area_width, clue_height


def _draw_external_clues(
    pdf: Canvas,
    layouts: tuple[tuple[Paragraph, float, float], ...],
    left: float,
    bottom: float,
    height: float,
) -> None:
    for paragraph, offset, paragraph_height in layouts:
        paragraph.drawOn(
            pdf,
            left + offset,
            bottom + height - paragraph_height,
        )


def _draw_inner_grid_lines(
    pdf: Canvas,
    grid: Grid,
    left: float,
    bottom: float,
    cell_size: float,
) -> None:
    grid_width = grid.width * cell_size
    grid_height = grid.height * cell_size

    pdf.saveState()
    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.setLineWidth(INNER_LINE_WIDTH)
    pdf.setLineCap(0)
    for column in range(1, grid.width):
        x = left + column * cell_size
        pdf.line(x, bottom, x, bottom + grid_height)
    for row in range(1, grid.height):
        y = bottom + row * cell_size
        pdf.line(left, y, left + grid_width, y)
    pdf.restoreState()


def _draw_strong_grid_lines(
    pdf: Canvas,
    grid: Grid,
    left: float,
    bottom: float,
    cell_size: float,
) -> None:
    grid_width = grid.width * cell_size
    grid_height = grid.height * cell_size

    pdf.saveState()
    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.setLineWidth(STRONG_LINE_WIDTH)
    pdf.setLineCap(0)
    if grid.cells is not None:
        for row_index, row in enumerate(grid.cells):
            cell_bottom = bottom + grid_height - (row_index + 1) * cell_size
            for column_index, cell in enumerate(row):
                if not isinstance(cell, (LetterCell, SecretCell)):
                    continue
                cell_left = left + column_index * cell_size
                if "right" in cell.bars:
                    x = cell_left + cell_size
                    pdf.line(x, cell_bottom, x, cell_bottom + cell_size)
                if "bottom" in cell.bars:
                    pdf.line(
                        cell_left,
                        cell_bottom,
                        cell_left + cell_size,
                        cell_bottom,
                    )
    pdf.rect(left, bottom, grid_width, grid_height, stroke=1, fill=0)
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
    target: str | Path | BinaryIO,
    page_size: tuple[float, float],
    *,
    filled: bool,
) -> None:
    page_width, page_height = page_size
    width = crossword.grid.width
    height = crossword.grid.height
    available_width = page_width - 2 * PAGE_MARGIN
    available_height = page_height - 2 * PAGE_MARGIN
    cell_size = min(MAX_CELL_SIZE, available_width / width)
    for _ in range(50):
        provisional_grid_width = width * cell_size
        above_layouts, above_height = _prepare_secret_prompts(
            crossword.secret_prompts,
            "above",
            provisional_grid_width,
            available_height,
        )
        below_layouts, below_height = _prepare_secret_prompts(
            crossword.secret_prompts,
            "below",
            provisional_grid_width,
            available_height,
        )
        clue_layouts, clue_area_width, clue_height = _prepare_external_clues(
            crossword,
            page_width,
            page_height,
            provisional_grid_width,
        )
        clue_gap = EXTERNAL_CLUE_GRID_GAP if clue_layouts else 0.0
        above_gap = SECRET_PROMPT_GRID_GAP if above_layouts else 0.0
        below_gap = SECRET_PROMPT_GRID_GAP if below_layouts else 0.0
        outside_height = (
            clue_height
            + clue_gap
            + below_height
            + below_gap
            + above_gap
            + above_height
        )
        available_grid_height = available_height - outside_height
        if available_grid_height <= 0:
            raise RenderError(
                "obsah vně mřížky se nevejde na zvolenou stránku"
            )
        next_cell_size = min(
            cell_size,
            available_grid_height / height,
        )
        if next_cell_size == cell_size:
            break
        cell_size = next_cell_size
    else:
        raise RenderError("sazbu obsahu vně mřížky se nepodařilo ustálit")

    grid_width = width * cell_size
    grid_height = height * cell_size
    left = (page_width - grid_width) / 2
    content_height = grid_height + outside_height
    content_bottom = (page_height - content_height) / 2
    below_prompt_bottom = content_bottom + clue_height + clue_gap
    bottom = below_prompt_bottom + below_height + below_gap
    above_prompt_bottom = bottom + grid_height + above_gap
    clue_left = (page_width - clue_area_width) / 2

    canvas_target = str(target) if isinstance(target, (str, Path)) else target
    pdf = Canvas(canvas_target, pagesize=page_size, pageCompression=1)
    pdf.setTitle(f"Křížovkář – mřížka {width} × {height}")
    pdf.setCreator("Křížovkář")
    has_unfilled_cells = (
        crossword.grid.cells is not None
        and any(
            (
                isinstance(cell, (LetterCell, SecretCell))
                and cell.value is None
            )
            or (
                isinstance(cell, LegendCell)
                and (not cell.texts or any(text is None for text in cell.texts))
            )
            for row in crossword.grid.cells
            for cell in row
        )
    )
    if crossword.grid.cells is None:
        subject = "Prázdná křížovková mřížka"
    elif filled and not has_unfilled_cells:
        subject = "Vyplněná křížovková mřížka"
    else:
        subject = "Nevyplněná křížovková mřížka"
    pdf.setSubject(subject)
    pdf.setStrokeColorRGB(0, 0, 0)

    if crossword.grid.cells is not None:
        for row_index, row in enumerate(crossword.grid.cells):
            cell_bottom = bottom + grid_height - (row_index + 1) * cell_size
            for column_index, cell in enumerate(row):
                cell_left = left + column_index * cell_size
                if isinstance(cell, SecretCell):
                    pdf.setFillGray(SECRET_FILL_GRAY)
                    pdf.rect(
                        cell_left,
                        cell_bottom,
                        cell_size,
                        cell_size,
                        stroke=0,
                        fill=1,
                    )
                    if cell.arrow is not None:
                        _draw_secret_beak(
                            pdf,
                            cell.arrow,
                            cell_left,
                            cell_bottom,
                            cell_size,
                            numbered=cell.number is not None,
                        )
                elif isinstance(cell, LegendCell):
                    _draw_legend_cell(
                        pdf,
                        cell,
                        cell_left,
                        cell_bottom,
                        cell_size,
                    )
                elif isinstance(cell, EmptyCell):
                    _draw_empty_cell(
                        pdf,
                        cell_left,
                        cell_bottom,
                        cell_size,
                    )
                elif isinstance(cell, HelpCell):
                    _draw_help_cell(
                        pdf,
                        cell,
                        cell_left,
                        cell_bottom,
                        cell_size,
                    )
                if (
                    isinstance(cell, (LetterCell, SecretCell))
                    and cell.number is not None
                ):
                    _draw_cell_number(
                        pdf,
                        cell.number,
                        cell_left,
                        cell_bottom,
                        cell_size,
                    )

    if crossword.grid.cells is not None and filled:
        font_size = cell_size * LETTER_SIZE_RATIO
        _register_text_cell_fonts()
        pdf.setFillColorRGB(0, 0, 0)
        for row_index, row in enumerate(crossword.grid.cells):
            center_y = bottom + grid_height - (row_index + 0.5) * cell_size
            for column_index, cell in enumerate(row):
                if (
                    not isinstance(cell, (LetterCell, SecretCell))
                    or cell.value is None
                ):
                    continue
                center_x = left + (column_index + 0.5) * cell_size
                cell_center_y = center_y
                if isinstance(cell, SecretCell) and cell.arrow is not None:
                    center_x, cell_center_y = _secret_letter_center(
                        cell.arrow,
                        center_x,
                        cell_center_y,
                        cell_size,
                    )
                _draw_letter_cell(
                    pdf,
                    cell,
                    center_x,
                    cell_center_y,
                    cell_size,
                    font_size,
                )

    _draw_inner_grid_lines(
        pdf,
        crossword.grid,
        left,
        bottom,
        cell_size,
    )

    _draw_strong_grid_lines(
        pdf,
        crossword.grid,
        left,
        bottom,
        cell_size,
    )
    if clue_layouts:
        _draw_external_clues(
            pdf,
            clue_layouts,
            clue_left,
            content_bottom,
            clue_height,
        )
    if below_layouts:
        _draw_secret_prompts(
            pdf,
            below_layouts,
            left,
            below_prompt_bottom,
            below_height,
        )
    if above_layouts:
        _draw_secret_prompts(
            pdf,
            above_layouts,
            left,
            above_prompt_bottom,
            above_height,
        )
    pdf.showPage()
    pdf.save()


def render_pdf(
    crossword: CrosswordGrid,
    output: str | Path,
    *,
    overwrite: bool = False,
    page_format: str = DEFAULT_PAGE_FORMAT,
    filled: bool = True,
) -> Path:
    """Vykreslí vyplněnou či nevyplněnou křížovku atomicky do PDF."""

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

        _write_pdf(
            crossword,
            temporary_path,
            page_size,
            filled=filled,
        )
        temporary_path.replace(output_path)
    except OSError as error:
        raise RenderError(
            f"PDF nelze zapsat ({output_path}): {system_error_message(error)}"
        ) from error
    finally:
        if "temporary_path" in locals():
            temporary_path.unlink(missing_ok=True)

    return output_path


def render_pdf_stream(
    crossword: CrosswordGrid,
    output: BinaryIO,
    *,
    page_format: str = DEFAULT_PAGE_FORMAT,
    filled: bool = True,
) -> None:
    """Vykreslí vyplněnou či nevyplněnou křížovku do binárního proudu."""

    page_size = resolve_page_size(page_format)
    try:
        _write_pdf(
            crossword,
            output,
            page_size,
            filled=filled,
        )
    except OSError as error:
        raise RenderError(
            f"PDF nelze zapsat: {system_error_message(error)}"
        ) from error

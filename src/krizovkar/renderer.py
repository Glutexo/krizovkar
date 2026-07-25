"""Vektorové vykreslení křížovkové mřížky do PDF."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from reportlab.lib.pagesizes import A0, A1, A2, A3, A4, A5, A6, LEGAL, LETTER
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from krizovkar.model import Crossword

PAGE_MARGIN = 15 * mm
MAX_CELL_SIZE = 12 * mm
INNER_LINE_WIDTH = 0.5
OUTER_LINE_WIDTH = 1.25
LETTER_FONT = "Helvetica-Bold"
LETTER_SIZE_RATIO = 0.58
LETTER_BASELINE_OFFSET = 0.35
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
    crossword: Crossword,
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
        font_size = cell_size * LETTER_SIZE_RATIO
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont(LETTER_FONT, font_size)
        for row_index, row in enumerate(crossword.grid.cells):
            center_y = bottom + grid_height - (row_index + 0.5) * cell_size
            baseline = center_y - font_size * LETTER_BASELINE_OFFSET
            for column_index, cell in enumerate(row):
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
    crossword: Crossword,
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

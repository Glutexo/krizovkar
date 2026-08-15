"""Sazba křížovky do LaTeXu a překlad výsledného PDF."""

from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import BinaryIO, TextIO

from krizovkar.localization import system_error_message
from krizovkar.model import (
    CrosswordGrid,
    EmptyCell,
    ExternalClue,
    HelpCell,
    LegendArrow,
    LegendCell,
    LetterCell,
    SecretArrow,
    SecretCell,
    SecretPrompt,
)
from krizovkar.typography import mark_czech_hyphenation, protect_czech_prepositions

CELL_SIZE_MM = 12.0
CELL_PADDING_MM = 0.6
MINIMUM_CLUE_AREA_WIDTH_MM = 100.0
CLUE_COLUMN_GAP_MM = 6.0
CLUE_GRID_GAP_MM = 7.0
PROMPT_GRID_GAP_MM = 4.0
PROMPT_SPACING_MM = 2.0
PAGE_MARGIN_MM = 15.0
INNER_LINE_WIDTH_PT = 0.75
STRONG_LINE_WIDTH_PT = 1.25
SECRET_BEAK_DEPTH_RATIO = 0.28
SECRET_BEAK_BASE_RATIO = 0.82
SECRET_BEAK_NUMBERED_BASE_RATIO = 0.46
SECRET_BEAK_NUMBERED_OFFSET_RATIO = 0.18
SECRET_BEAK_LETTER_OFFSET_RATIO = 0.1
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
LUALATEX_EXECUTABLE = "lualatex"
_POINTS_PER_MM = 72.0 / 25.4
_PAGE_DIMENSIONS_MM = {
    "A0": (841.0, 1189.0),
    "A1": (594.0, 841.0),
    "A2": (420.0, 594.0),
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A6": (105.0, 148.0),
    "LETTER": (215.9, 279.4),
    "LEGAL": (215.9, 355.6),
}
_ARROW_VECTORS: dict[SecretArrow, tuple[float, float]] = {
    "up": (0.0, 1.0),
    "right": (1.0, 0.0),
    "down": (0.0, -1.0),
    "left": (-1.0, 0.0),
}
_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "#": r"\#",
    "$": r"\$",
    "%": r"\%",
    "&": r"\&",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
    "|": r"\textbar{}",
    '"': r"\textquotedbl{}",
    "`": r"\textasciigrave{}",
    "\u00a0": "~",
    "\u00ad": r"\-",
    "\n": " ",
    "\r": " ",
    "\t": " ",
}


class RenderError(RuntimeError):
    """LaTeX nebo PDF nelze bezpečně vytvořit."""


def resolve_page_size(page_format: str) -> tuple[float, float]:
    """Vrátí rozměr stránky v typografických bodech."""

    normalized = page_format.upper()
    try:
        width_mm, height_mm = _PAGE_DIMENSIONS_MM[normalized]
    except KeyError as error:
        supported = ", ".join(SUPPORTED_PAGE_FORMATS)
        raise RenderError(
            f"nepodporovaný formát stránky {page_format!r}; "
            f"podporované formáty: {supported}"
        ) from error
    return width_mm * _POINTS_PER_MM, height_mm * _POINTS_PER_MM


def _format_number(value: float) -> str:
    return f"{value:.6g}"


def _millimetres(value: float) -> str:
    return f"{_format_number(value)}mm"


def _point(x: float, y: float) -> str:
    return f"({_format_number(x)},{_format_number(y)})"


def _escape_latex(text: str, *, typography: bool = False) -> str:
    if typography:
        text = mark_czech_hyphenation(protect_czech_prepositions(text))
    return "".join(_LATEX_ESCAPES.get(character, character) for character in text)


def _cell_text_command(
    text: str,
    center_x: float,
    center_y: float,
    width_mm: float,
    height_mm: float,
    *,
    prefix: str | None = None,
) -> str:
    content = _escape_latex(text, typography=True)
    if prefix is not None:
        content = rf"\textbf{{{_escape_latex(prefix)}}} {content}"
    return (
        rf"\node[inner sep=0pt] at {_point(center_x, center_y)} "
        rf"{{\KrizovkarCellText{{{_millimetres(width_mm)}}}"
        rf"{{{_millimetres(height_mm)}}}{{{content}}}}};"
    )


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


def _legend_arrow_command(
    direction: LegendArrow,
    left: float,
    bottom: float,
    section_bottom: float,
    section_height: float,
) -> str:
    if direction == "right":
        tip = (left + 0.96, section_bottom + section_height * 0.22)
        tail = (tip[0] - 0.18, tip[1])
    else:
        tip = (left + 0.78, bottom + 0.04)
        tail = (tip[0], tip[1] + 0.18)
    return (
        rf"\draw[line width=0.75pt,-{{Latex[length=1.3mm,width=1.1mm]}}] "
        rf"{_point(*tail)} -- {_point(*tip)};"
    )


def _append_legend_cell(
    lines: list[str],
    cell: LegendCell,
    left: float,
    bottom: float,
) -> None:
    lines.append(rf"\fill[black!7] {_point(left, bottom)} rectangle ++(1,1);")
    if not cell.texts:
        return

    section_height = 1.0 / len(cell.texts)
    for section_index in range(1, len(cell.texts)):
        separator_y = bottom + 1.0 - section_index * section_height
        lines.append(
            rf"\draw[line width=0.4pt] {_point(left, separator_y)} -- "
            rf"{_point(left + 1.0, separator_y)};"
        )

    text_width_mm = CELL_SIZE_MM - 2 * CELL_PADDING_MM
    text_height_mm = max(
        section_height * CELL_SIZE_MM - 2 * CELL_PADDING_MM,
        0.1,
    )
    for section_index, text in enumerate(cell.texts):
        section_bottom = bottom + 1.0 - (section_index + 1) * section_height
        if text is not None:
            lines.append(
                _cell_text_command(
                    text,
                    left + 0.5,
                    section_bottom + section_height / 2,
                    text_width_mm,
                    text_height_mm,
                )
            )
        if section_index < len(cell.arrows):
            lines.append(
                _legend_arrow_command(
                    cell.arrows[section_index],
                    left,
                    bottom,
                    section_bottom,
                    section_height,
                )
            )


def _append_secret_cell(
    lines: list[str],
    cell: SecretCell,
    left: float,
    bottom: float,
) -> None:
    lines.append(rf"\fill[black!15] {_point(left, bottom)} rectangle ++(1,1);")
    if cell.arrow is None:
        return
    points = _secret_beak_points(
        cell.arrow,
        left,
        bottom,
        1.0,
        numbered=cell.number is not None,
    )
    lines.append(
        "\\fill " + " -- ".join(_point(*point) for point in points) + " -- cycle;"
    )


def _append_empty_cell(lines: list[str], left: float, bottom: float) -> None:
    lines.extend(
        (
            rf"\draw[gray!70,line width=0.65pt] "
            rf"{_point(left + 0.3, bottom + 0.3)} -- "
            rf"{_point(left + 0.7, bottom + 0.7)};",
            rf"\draw[gray!70,line width=0.65pt] "
            rf"{_point(left + 0.3, bottom + 0.7)} -- "
            rf"{_point(left + 0.7, bottom + 0.3)};",
        )
    )


def _append_help_cell(
    lines: list[str],
    cell: HelpCell,
    left: float,
    bottom: float,
) -> None:
    lines.append(rf"\fill[black!7] {_point(left, bottom)} rectangle ++(1,1);")
    lines.append(
        _cell_text_command(
            ", ".join(cell.words),
            left + 0.5,
            bottom + 0.5,
            CELL_SIZE_MM - 2 * CELL_PADDING_MM,
            CELL_SIZE_MM - 2 * CELL_PADDING_MM,
            prefix="Pomůcka:",
        )
    )


def _append_number(
    lines: list[str],
    number: int,
    left: float,
    bottom: float,
) -> None:
    lines.append(
        rf"\node[anchor=north west,inner sep=0pt,font=\bfseries\fontsize{{7pt}}{{7pt}}"
        rf"\selectfont] at {_point(left + 0.07, bottom + 0.93)} "
        rf"{{{number}}};"
    )


def _append_letter(
    lines: list[str],
    cell: LetterCell | SecretCell,
    left: float,
    bottom: float,
) -> None:
    assert cell.value is not None
    center_x = left + 0.5
    center_y = bottom + 0.5
    if isinstance(cell, SecretCell) and cell.arrow is not None:
        center_x, center_y = _secret_letter_center(
            cell.arrow,
            center_x,
            center_y,
            1.0,
        )
    lines.append(
        rf"\node[inner sep=0pt] at {_point(center_x, center_y)} "
        rf"{{\KrizovkarLetter{{9.6mm}}{{{_escape_latex(cell.value)}}}}};"
    )


def _grid_commands(crossword: CrosswordGrid, *, filled: bool) -> list[str]:
    grid = crossword.grid
    lines = [
        rf"\begin{{tikzpicture}}[x={_millimetres(CELL_SIZE_MM)},"
        rf"y={_millimetres(CELL_SIZE_MM)},line cap=butt,line join=miter]"
    ]
    if grid.cells is not None:
        for row_index, row in enumerate(grid.cells):
            bottom = grid.height - row_index - 1
            for column_index, cell in enumerate(row):
                left = float(column_index)
                if isinstance(cell, SecretCell):
                    _append_secret_cell(lines, cell, left, bottom)
                elif isinstance(cell, LegendCell):
                    _append_legend_cell(lines, cell, left, bottom)
                elif isinstance(cell, EmptyCell):
                    _append_empty_cell(lines, left, bottom)
                elif isinstance(cell, HelpCell):
                    _append_help_cell(lines, cell, left, bottom)
                if (
                    isinstance(cell, (LetterCell, SecretCell))
                    and cell.number is not None
                ):
                    _append_number(lines, cell.number, left, bottom)

        if filled:
            for row_index, row in enumerate(grid.cells):
                bottom = grid.height - row_index - 1
                for column_index, cell in enumerate(row):
                    if (
                        isinstance(cell, (LetterCell, SecretCell))
                        and cell.value is not None
                    ):
                        _append_letter(lines, cell, float(column_index), bottom)

    for column in range(1, grid.width):
        lines.append(
            rf"\draw[line width={_format_number(INNER_LINE_WIDTH_PT)}pt] "
            rf"{_point(column, 0)} -- {_point(column, grid.height)};"
        )
    for row in range(1, grid.height):
        lines.append(
            rf"\draw[line width={_format_number(INNER_LINE_WIDTH_PT)}pt] "
            rf"{_point(0, row)} -- {_point(grid.width, row)};"
        )

    if grid.cells is not None:
        for row_index, row in enumerate(grid.cells):
            bottom = grid.height - row_index - 1
            for column_index, cell in enumerate(row):
                if not isinstance(cell, (LetterCell, SecretCell)):
                    continue
                left = float(column_index)
                if "right" in cell.bars:
                    lines.append(
                        rf"\draw[line width={_format_number(STRONG_LINE_WIDTH_PT)}pt] "
                        rf"{_point(left + 1, bottom)} -- "
                        rf"{_point(left + 1, bottom + 1)};"
                    )
                if "bottom" in cell.bars:
                    lines.append(
                        rf"\draw[line width={_format_number(STRONG_LINE_WIDTH_PT)}pt] "
                        rf"{_point(left, bottom)} -- {_point(left + 1, bottom)};"
                    )

    lines.extend(
        (
            rf"\draw[line width={_format_number(STRONG_LINE_WIDTH_PT)}pt] "
            rf"{_point(0, 0)} rectangle {_point(grid.width, grid.height)};",
            r"\end{tikzpicture}",
        )
    )
    return lines


def _append_prompt_block(
    lines: list[str],
    prompts: tuple[SecretPrompt, ...],
    grid_width_mm: float,
) -> None:
    lines.extend(
        (
            r"\makebox[\linewidth][c]{%",
            rf"\begin{{minipage}}{{{_millimetres(grid_width_mm)}}}",
            r"\fontsize{9pt}{11pt}\selectfont",
        )
    )
    for prompt_index, prompt in enumerate(prompts):
        alignment = r"\raggedright" if prompt.alignment == "left" else r"\raggedleft"
        lines.append(
            rf"{{{alignment} {_escape_latex(prompt.text, typography=True)}\par}}"
        )
        if prompt_index + 1 < len(prompts):
            lines.append(rf"\vspace{{{_millimetres(PROMPT_SPACING_MM)}}}")
    lines.extend((r"\end{minipage}%", r"}"))


def _clue_groups(
    clues: tuple[ExternalClue, ...],
) -> tuple[tuple[str, tuple[ExternalClue, ...]], ...]:
    groups = []
    for direction, heading in (
        ("horizontal", "Vodorovně"),
        ("vertical", "Svisle"),
    ):
        selected = tuple(
            sorted(
                (clue for clue in clues if clue.direction == direction),
                key=lambda clue: clue.number,
            )
        )
        if selected:
            groups.append((heading, selected))
    return tuple(groups)


def _append_clue_block(
    lines: list[str],
    groups: tuple[tuple[str, tuple[ExternalClue, ...]], ...],
    area_width_mm: float,
) -> None:
    column_width_mm = (
        area_width_mm - CLUE_COLUMN_GAP_MM * (len(groups) - 1)
    ) / len(groups)
    lines.extend(
        (
            r"\makebox[\linewidth][c]{%",
            r"{\fontsize{8pt}{9.6pt}\selectfont",
        )
    )
    for group_index, (heading, clues) in enumerate(groups):
        if group_index:
            lines.append(rf"\hspace{{{_millimetres(CLUE_COLUMN_GAP_MM)}}}%")
        lines.extend(
            (
                rf"\begin{{minipage}}[t]{{{_millimetres(column_width_mm)}}}",
                rf"\textbf{{{_escape_latex(heading)}}}\par",
            )
        )
        for clue in clues:
            lines.append(
                rf"\textbf{{{clue.number}.}} "
                rf"{_escape_latex(clue.text, typography=True)}\par"
            )
        lines.append(r"\end{minipage}%")
    lines.extend((r"}%", r"}"))


def create_latex_source(
    crossword: CrosswordGrid,
    *,
    page_format: str = DEFAULT_PAGE_FORMAT,
    filled: bool = True,
) -> str:
    """Vytvoří samostatně přeložitelnou LaTeXovou šablonu křížovky."""

    normalized_format = page_format.upper()
    resolve_page_size(normalized_format)
    page_width_mm, page_height_mm = _PAGE_DIMENSIONS_MM[normalized_format]
    grid_width_mm = crossword.grid.width * CELL_SIZE_MM
    clue_groups = _clue_groups(crossword.clues)
    clue_area_width_mm = (
        max(grid_width_mm, MINIMUM_CLUE_AREA_WIDTH_MM)
        if clue_groups
        else grid_width_mm
    )
    content_width_mm = max(grid_width_mm, clue_area_width_mm)
    above_prompts = tuple(
        prompt for prompt in crossword.secret_prompts if prompt.placement == "above"
    )
    below_prompts = tuple(
        prompt for prompt in crossword.secret_prompts if prompt.placement == "below"
    )

    lines = [
        "% Automaticky vytvořil Křížovkář. Soubor lze před překladem upravit.",
        (
            "% Překlad: lualatex -interaction=nonstopmode -halt-on-error "
            "-no-shell-escape soubor.tex"
        ),
        r"\documentclass[10pt]{article}",
        (
            r"\usepackage[paperwidth="
            + _millimetres(page_width_mm)
            + ",paperheight="
            + _millimetres(page_height_mm)
            + ",margin="
            + _millimetres(PAGE_MARGIN_MM)
            + r"]{geometry}"
        ),
        r"\usepackage{fontspec}",
        r"\usepackage[czech]{babel}",
        r"\usepackage{tikz}",
        r"\usetikzlibrary{arrows.meta,babel}",
        r"\usepackage{adjustbox}",
        r"\setsansfont[BoldFont={lmsans10-bold.otf}]{lmsans10-regular.otf}",
        r"\renewcommand{\familydefault}{\sfdefault}",
        r"\pagestyle{empty}",
        r"\setlength{\parindent}{0pt}",
        r"\newcommand{\KrizovkarCellText}[3]{%",
        r"  \adjustbox{max width=#1,max totalheight=#2}{%",
        (
            r"    \parbox{#1}{\centering\fontsize{6pt}{6.3pt}\selectfont"
            r"\sloppy\hspace{0pt}#3}%"
        ),
        r"  }%",
        r"}",
        r"\newcommand{\KrizovkarLetter}[2]{%",
        r"  \adjustbox{max width=#1,max totalheight=8mm}{%",
        r"    \bfseries\fontsize{20pt}{20pt}\selectfont #2%",
        r"  }%",
        r"}",
        r"\begin{document}",
        r"\vspace*{\fill}",
        r"\noindent\makebox[\textwidth][c]{%",
        r"\begin{adjustbox}{max totalsize={\textwidth}{\textheight}}",
        rf"\begin{{minipage}}{{{_millimetres(content_width_mm)}}}",
    ]

    if above_prompts:
        lines.append("% Zadání tajenky nad mřížkou")
        _append_prompt_block(lines, above_prompts, grid_width_mm)
        lines.append(rf"\vspace{{{_millimetres(PROMPT_GRID_GAP_MM)}}}")

    lines.extend(("% Křížovková mřížka", r"\makebox[\linewidth][c]{%"))
    lines.extend(_grid_commands(crossword, filled=filled))
    lines.append(r"}")

    if below_prompts:
        lines.append(rf"\vspace{{{_millimetres(PROMPT_GRID_GAP_MM)}}}")
        lines.append("% Zadání tajenky pod mřížkou")
        _append_prompt_block(lines, below_prompts, grid_width_mm)

    if clue_groups:
        lines.append(rf"\vspace{{{_millimetres(CLUE_GRID_GAP_MM)}}}")
        lines.append("% Vnější číslované legendy")
        _append_clue_block(lines, clue_groups, clue_area_width_mm)

    lines.extend(
        (
            r"\end{minipage}",
            r"\end{adjustbox}%",
            r"}",
            r"\vspace*{\fill}",
            r"\end{document}",
            "",
        )
    )
    return "\n".join(lines)


def render_latex(
    crossword: CrosswordGrid,
    output: str | Path,
    *,
    overwrite: bool = False,
    page_format: str = DEFAULT_PAGE_FORMAT,
    filled: bool = True,
) -> Path:
    """Zapíše LaTeXovou šablonu atomicky do souboru."""

    output_path = Path(output)
    if output_path.exists() and not overwrite:
        raise RenderError(f"výstupní soubor již existuje: {output_path}")
    source = create_latex_source(
        crossword,
        page_format=page_format,
        filled=filled,
    )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{output_path.name}.",
            suffix=".tex",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(source)
        temporary_path.replace(output_path)
    except OSError as error:
        raise RenderError(
            f"LaTeX nelze zapsat ({output_path}): {system_error_message(error)}"
        ) from error
    except UnicodeError as error:
        raise RenderError(
            f"LaTeX nelze zapsat ({output_path}): "
            "text nelze zakódovat jako UTF-8"
        ) from error
    finally:
        if "temporary_path" in locals():
            temporary_path.unlink(missing_ok=True)
    return output_path


def render_latex_stream(
    crossword: CrosswordGrid,
    output: TextIO,
    *,
    page_format: str = DEFAULT_PAGE_FORMAT,
    filled: bool = True,
) -> None:
    """Zapíše LaTeXovou šablonu do textového proudu."""

    source = create_latex_source(
        crossword,
        page_format=page_format,
        filled=filled,
    )
    try:
        output.write(source)
    except OSError as error:
        raise RenderError(
            f"LaTeX nelze zapsat: {system_error_message(error)}"
        ) from error
    except UnicodeError as error:
        raise RenderError(
            "LaTeX nelze zapsat: výstup nepodporuje český text v UTF-8"
        ) from error


def _compilation_diagnostic(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    error_lines = [line for line in lines if line.startswith("!")]
    if error_lines:
        return error_lines[-1][:1000]
    if not lines:
        return "LuaLaTeX nevrátil podrobnosti chyby"
    return "\n".join(lines[-8:])[-2000:]


def _run_lualatex(source: Path, output_directory: Path) -> Path:
    command = (
        LUALATEX_EXECUTABLE,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-no-shell-escape",
        f"-output-directory={output_directory}",
        source.name,
    )
    try:
        result = subprocess.run(
            command,
            cwd=source.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as error:
        raise RenderError(
            "LuaLaTeX nebyl nalezen; nainstalujte TeX Live s příkazem "
            f"{LUALATEX_EXECUTABLE}"
        ) from error
    except OSError as error:
        raise RenderError(
            f"LuaLaTeX nelze spustit: {system_error_message(error)}"
        ) from error

    if result.returncode != 0:
        raise RenderError(
            "LuaLaTeX nedokázal sestavit PDF:\n"
            f"{_compilation_diagnostic(result.stdout)}"
        )
    pdf_path = output_directory / f"{source.stem}.pdf"
    if not pdf_path.is_file():
        raise RenderError("LuaLaTeX skončil bez vytvoření PDF")
    return pdf_path


def render_pdf(
    crossword: CrosswordGrid,
    output: str | Path,
    *,
    overwrite: bool = False,
    page_format: str = DEFAULT_PAGE_FORMAT,
    filled: bool = True,
) -> Path:
    """Vytvoří LaTeXovou šablonu a atomicky ji přeloží do PDF."""

    output_path = Path(output)
    if output_path.exists() and not overwrite:
        raise RenderError(f"výstupní soubor již existuje: {output_path}")
    source = create_latex_source(
        crossword,
        page_format=page_format,
        filled=filled,
    )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(
            prefix=f".{output_path.name}.",
            dir=output_path.parent,
        ) as directory:
            temporary_directory = Path(directory)
            latex_path = temporary_directory / "krizovkar.tex"
            latex_path.write_text(source, encoding="utf-8", newline="\n")
            pdf_path = _run_lualatex(latex_path, temporary_directory)
            pdf_path.replace(output_path)
    except OSError as error:
        raise RenderError(
            f"PDF nelze zapsat ({output_path}): {system_error_message(error)}"
        ) from error
    return output_path


def render_pdf_stream(
    crossword: CrosswordGrid,
    output: BinaryIO,
    *,
    page_format: str = DEFAULT_PAGE_FORMAT,
    filled: bool = True,
) -> None:
    """Vytvoří LaTeXovou šablonu a přeloží ji do PDF proudu."""

    source = create_latex_source(
        crossword,
        page_format=page_format,
        filled=filled,
    )
    try:
        with TemporaryDirectory(prefix="krizovkar-pdf-") as directory:
            temporary_directory = Path(directory)
            latex_path = temporary_directory / "krizovkar.tex"
            latex_path.write_text(source, encoding="utf-8", newline="\n")
            pdf_path = _run_lualatex(latex_path, temporary_directory)
            with pdf_path.open("rb") as compiled_pdf:
                while chunk := compiled_pdf.read(64 * 1024):
                    output.write(chunk)
    except OSError as error:
        raise RenderError(
            f"PDF nelze zapsat: {system_error_message(error)}"
        ) from error

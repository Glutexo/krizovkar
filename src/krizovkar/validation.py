"""Oddělení blokujících chyb formátu od varování kvality mřížky."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from krizovkar.model import (
    CrosswordGrid,
    LegendCell,
    LetterCell,
    ModelError,
    SecretCell,
    load_crossword_grid,
)

ValidationSeverity = Literal["error", "warning"]
AnswerDirection = Literal["right", "down"]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Jedna blokující chyba nebo neblokující výhrada ke kvalitě."""

    severity: ValidationSeverity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Výsledek validace se samostatnými chybami a varováními."""

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity == "warning"
        )

    @property
    def is_valid(self) -> bool:
        """Platný je dokument bez blokující chyby, i když má varování."""

        return not self.errors


def _cell_path(row: int, column: int) -> str:
    return f"$.grid.cells[{row}][{column}]"


def _warning(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(
        severity="warning",
        code=code,
        path=path,
        message=message,
    )


def _answer_directions(
    crossword: CrosswordGrid,
    row: int,
    column: int,
) -> tuple[AnswerDirection, ...]:
    cells = crossword.grid.cells
    assert cells is not None
    directions: list[AnswerDirection] = []
    if column + 1 < crossword.grid.width and isinstance(
        cells[row][column + 1],
        (LetterCell, SecretCell),
    ):
        directions.append("right")
    if row + 1 < crossword.grid.height and isinstance(
        cells[row + 1][column],
        (LetterCell, SecretCell),
    ):
        directions.append("down")
    return tuple(directions)


def _letter_component_count(crossword: CrosswordGrid) -> int:
    cells = crossword.grid.cells
    assert cells is not None
    remaining = {
        (row, column)
        for row, cell_row in enumerate(cells)
        for column, cell in enumerate(cell_row)
        if isinstance(cell, (LetterCell, SecretCell))
    }
    component_count = 0

    while remaining:
        component_count += 1
        stack = [remaining.pop()]
        while stack:
            row, column = stack.pop()
            for neighbor in (
                (row - 1, column),
                (row + 1, column),
                (row, column - 1),
                (row, column + 1),
            ):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)

    return component_count


def _word_start_warnings(crossword: CrosswordGrid) -> list[ValidationIssue]:
    cells = crossword.grid.cells
    assert cells is not None
    issues: list[ValidationIssue] = []

    for row, cell_row in enumerate(cells):
        for column, cell in enumerate(cell_row):
            if not isinstance(cell, (LetterCell, SecretCell)):
                continue

            left_cell = cells[row][column - 1] if column > 0 else None
            continues_from_left = isinstance(
                left_cell,
                (LetterCell, SecretCell),
            ) and "right" not in left_cell.bars
            has_inline_horizontal_clue = isinstance(left_cell, LegendCell)
            if (
                not continues_from_left
                and not has_inline_horizontal_clue
                and cell.number is None
            ):
                clue_column = (
                    column
                    if isinstance(left_cell, (LetterCell, SecretCell))
                    else max(0, column - 1)
                )
                issues.append(
                    _warning(
                        "layout.missing-legend",
                        _cell_path(row, clue_column),
                        "vodorovné heslo nemá vepsanou ani číselnou legendu",
                    )
                )

            above_cell = cells[row - 1][column] if row > 0 else None
            continues_from_above = isinstance(
                above_cell,
                (LetterCell, SecretCell),
            ) and "bottom" not in above_cell.bars
            has_inline_vertical_clue = isinstance(above_cell, LegendCell)
            if (
                not continues_from_above
                and not has_inline_vertical_clue
                and cell.number is None
            ):
                clue_row = (
                    row
                    if isinstance(above_cell, (LetterCell, SecretCell))
                    else max(0, row - 1)
                )
                issues.append(
                    _warning(
                        "layout.missing-legend",
                        _cell_path(clue_row, column),
                        "svislé heslo nemá vepsanou ani číselnou legendu",
                    )
                )

    return issues


def check_crossword_grid(crossword: CrosswordGrid) -> ValidationReport:
    """Posoudí kvalitu jednotné křížovkové mřížky bez jejího odmítnutí."""

    cells = crossword.grid.cells
    if cells is None:
        return ValidationReport(
            (
                _warning(
                    "grid.unfinished",
                    "$.grid.cells",
                    "mřížka zatím nemá určený obsah buněk",
                ),
            )
        )

    issues: list[ValidationIssue] = []
    if any(
        (
            isinstance(cell, (LetterCell, SecretCell))
            and cell.value is None
        )
        or (
            isinstance(cell, LegendCell)
            and (not cell.texts or any(text is None for text in cell.texts))
        )
        for row in cells
        for cell in row
    ):
        issues.append(
            _warning(
                "grid.unfinished",
                "$.grid.cells",
                "mřížka obsahuje dosud nevyplněná písmena nebo legendy",
            )
        )
    component_count = _letter_component_count(crossword)
    if component_count > 1:
        issues.append(
            _warning(
                "layout.disconnected-letters",
                "$.grid.cells",
                f"písmenné buňky tvoří {component_count} oddělených ostrovů; "
                "všechna slova mají být navzájem propojená",
            )
        )

    for row, cell_row in enumerate(cells):
        for column, cell in enumerate(cell_row):
            if not isinstance(cell, LegendCell):
                continue

            path = _cell_path(row, column)
            directions = _answer_directions(crossword, row, column)
            if cell.texts and directions and len(cell.texts) != len(directions):
                issues.append(
                    _warning(
                        "legend.text-count",
                        f"{path}.texts",
                        "počet textů legendy neodpovídá počtu "
                        "navazujících směrů",
                    )
                )
            if cell.arrows:
                issues.append(
                    _warning(
                        "legend.arrows",
                        f"{path}.arrows",
                        "směr má být patrný z rozložení bez šipek",
                    )
                )
                if len(cell.arrows) != len(cell.texts):
                    issues.append(
                        _warning(
                            "legend.arrow-count",
                            f"{path}.arrows",
                            "počet šipek neodpovídá počtu textů legendy",
                        )
                    )

            if not directions:
                issues.append(
                    _warning(
                        "legend.no-direction",
                        path,
                        "z legendy bezprostředně nevychází heslo doprava ani dolů",
                    )
                )

    issues.extend(_word_start_warnings(crossword))

    return ValidationReport(tuple(issues))


def validate_crossword_grid_file(
    source: str | Path | TextIO,
) -> ValidationReport:
    """Ověří datový model ze souboru nebo proudu a posoudí jeho kvalitu."""

    try:
        crossword = load_crossword_grid(source)
    except ModelError as error:
        return ValidationReport(
            (
                ValidationIssue(
                    severity="error",
                    code="data-model",
                    path="$",
                    message=str(error),
                ),
            )
        )
    return check_crossword_grid(crossword)


def check_dense_swedish_grid(crossword: CrosswordGrid) -> ValidationReport:
    """Zachová původní veřejný název obecné kontroly mřížky."""

    return check_crossword_grid(crossword)


def validate_dense_swedish_grid_file(
    source: str | Path | TextIO,
) -> ValidationReport:
    """Zachová původní veřejný název obecné kontroly souboru."""

    return validate_crossword_grid_file(source)

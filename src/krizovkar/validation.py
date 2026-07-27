"""Oddělení blokujících chyb formátu od varování kvality mřížky."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


def _has_classic_annotations(crossword: CrosswordGrid) -> bool:
    cells = crossword.grid.cells
    assert cells is not None
    return bool(crossword.clues) or any(
        isinstance(cell, (LetterCell, SecretCell))
        and (cell.number is not None or cell.bars)
        for row in cells
        for cell in row
    )


def _word_start_warnings(crossword: CrosswordGrid) -> list[ValidationIssue]:
    cells = crossword.grid.cells
    assert cells is not None
    issues: list[ValidationIssue] = []

    for row, cell_row in enumerate(cells):
        for column, cell in enumerate(cell_row):
            if not isinstance(cell, (LetterCell, SecretCell)):
                continue

            left_is_letter = column > 0 and isinstance(
                cells[row][column - 1],
                (LetterCell, SecretCell),
            )
            if not left_is_letter and (
                column == 0
                or not isinstance(cells[row][column - 1], LegendCell)
            ):
                clue_column = max(0, column - 1)
                issues.append(
                    _warning(
                        "layout.missing-legend",
                        _cell_path(row, clue_column),
                        "vodorovné heslo nemá bezprostředně vlevo legendu",
                    )
                )

            above_is_letter = row > 0 and isinstance(
                cells[row - 1][column],
                (LetterCell, SecretCell),
            )
            if not above_is_letter and (
                row == 0
                or not isinstance(cells[row - 1][column], LegendCell)
            ):
                clue_row = max(0, row - 1)
                issues.append(
                    _warning(
                        "layout.missing-legend",
                        _cell_path(clue_row, column),
                        "svislé heslo nemá bezprostředně nad sebou legendu",
                    )
                )

    return issues


def check_dense_swedish_grid(crossword: CrosswordGrid) -> ValidationReport:
    """Posoudí kvalitu husté švédské mřížky bez jejího odmítnutí."""

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

    legend_count = 0

    for row, cell_row in enumerate(cells):
        for column, cell in enumerate(cell_row):
            if not isinstance(cell, LegendCell):
                continue

            path = _cell_path(row, column)
            directions = _answer_directions(crossword, row, column)
            legend_count += 1

            if directions and len(cell.texts) != len(directions):
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

    if not legend_count:
        if _has_classic_annotations(crossword):
            return ValidationReport(tuple(issues))
        issues.append(
            _warning(
                "layout.no-legends",
                "$.grid.cells",
                "mřížka neobsahuje žádnou legendu",
            )
        )
        return ValidationReport(tuple(issues))

    issues.extend(_word_start_warnings(crossword))

    return ValidationReport(tuple(issues))


def validate_dense_swedish_grid_file(source: str | Path) -> ValidationReport:
    """Ověří datový model souboru a poté neblokujícím způsobem jeho kvalitu."""

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
    return check_dense_swedish_grid(crossword)

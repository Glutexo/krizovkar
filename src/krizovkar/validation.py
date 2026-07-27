"""Oddělení blokujících chyb formátu od varování kvality mřížky."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from krizovkar.model import (
    CrosswordGrid,
    EmptyCell,
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

    directions_by_legend: dict[tuple[int, int], tuple[AnswerDirection, ...]] = {}

    for row, cell_row in enumerate(cells):
        for column, cell in enumerate(cell_row):
            if not isinstance(cell, LegendCell):
                continue

            path = _cell_path(row, column)
            directions = _answer_directions(crossword, row, column)
            directions_by_legend[(row, column)] = directions

            if len(cell.texts) != 1:
                issues.append(
                    _warning(
                        "legend.text-count",
                        f"{path}.texts",
                        "dobrá bezšipková legenda má právě jeden text",
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
            elif len(directions) > 1:
                issues.append(
                    _warning(
                        "legend.ambiguous-direction",
                        path,
                        "z legendy vychází heslo doprava i dolů, "
                        "takže směr není jednoznačný",
                    )
                )

    if not directions_by_legend:
        issues.append(
            _warning(
                "layout.no-legends",
                "$.grid.cells",
                "mřížka neobsahuje žádnou legendu",
            )
        )
        return ValidationReport(tuple(issues))

    legend_rows = {
        row
        for (row, _), directions in directions_by_legend.items()
        if directions == ("down",)
    }
    legend_columns = {
        column
        for (_, column), directions in directions_by_legend.items()
        if directions == ("right",)
    }

    if 0 not in legend_rows:
        issues.append(
            _warning(
                "layout.top-edge",
                "$.grid.cells[0]",
                "horní strana není úplnou legendovou hranou",
            )
        )
    if 0 not in legend_columns:
        issues.append(
            _warning(
                "layout.left-edge",
                "$.grid.cells",
                "levá strana není úplnou legendovou hranou",
            )
        )

    if legend_rows and legend_columns:
        for row, cell_row in enumerate(cells):
            for column, cell in enumerate(cell_row):
                path = _cell_path(row, column)
                on_legend_row = row in legend_rows
                on_legend_column = column in legend_columns

                if on_legend_row and on_legend_column:
                    if not isinstance(cell, EmptyCell):
                        issues.append(
                            _warning(
                                "layout.legend-intersection",
                                path,
                                "průsečík legendového řádku a sloupce "
                                "má být nevyplňovaný",
                            )
                        )
                elif on_legend_row or on_legend_column:
                    if not isinstance(cell, LegendCell):
                        issues.append(
                            _warning(
                                "layout.missing-legend",
                                path,
                                "legendová hrana má být souvisle pokrytá legendami",
                            )
                        )
                elif isinstance(cell, EmptyCell):
                    issues.append(
                        _warning(
                            "layout.unnecessary-empty",
                            path,
                            "nevyplňovaná buňka neleží v průsečíku "
                            "legendových hran",
                        )
                    )

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

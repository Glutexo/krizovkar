"""Testy oddělení chyb datového modelu od varování kvality."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from krizovkar.cli import main
from krizovkar.model import (
    CrosswordGrid,
    EmptyCell,
    Grid,
    LegendCell,
    LetterCell,
    write_crossword_grid,
)
from krizovkar.validation import (
    check_dense_swedish_grid,
    validate_dense_swedish_grid_file,
)


def _legend() -> LegendCell:
    return LegendCell(texts=("Legenda",))


def _good_dense_grid() -> CrosswordGrid:
    empty = EmptyCell()
    letter = LetterCell(value="A")
    cells = (
        (empty, _legend(), _legend(), empty, _legend()),
        (_legend(), letter, letter, _legend(), letter),
        (_legend(), letter, letter, _legend(), letter),
        (empty, _legend(), _legend(), empty, _legend()),
        (_legend(), letter, letter, _legend(), letter),
    )
    return CrosswordGrid(
        format_name="krizovkar",
        kind="grid",
        version=1,
        grid=Grid(width=5, height=5, cells=cells),
    )


def _replace_cell(
    crossword: CrosswordGrid,
    row: int,
    column: int,
    replacement: EmptyCell | LegendCell | LetterCell,
) -> CrosswordGrid:
    assert crossword.grid.cells is not None
    rows = [list(cell_row) for cell_row in crossword.grid.cells]
    rows[row][column] = replacement
    return CrosswordGrid(
        format_name=crossword.format_name,
        kind=crossword.kind,
        version=crossword.version,
        grid=Grid(
            width=crossword.grid.width,
            height=crossword.grid.height,
            cells=tuple(tuple(cell_row) for cell_row in rows),
        ),
    )


class QualityValidationTest(unittest.TestCase):
    def test_good_dense_grid_has_no_warning(self) -> None:
        report = check_dense_swedish_grid(_good_dense_grid())

        self.assertTrue(report.is_valid)
        self.assertEqual((), report.errors)
        self.assertEqual((), report.warnings)

    def test_format_valid_legend_choices_are_only_warnings(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            1,
            0,
            LegendCell(
                texts=("První", "Druhý"),
                arrows=("right",),
            ),
        )

        report = check_dense_swedish_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertEqual((), report.errors)
        self.assertEqual(
            {
                "legend.arrow-count",
                "legend.arrows",
                "legend.text-count",
            },
            {issue.code for issue in report.warnings},
        )

    def test_unnecessary_empty_cell_is_only_a_warning(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            2,
            2,
            EmptyCell(),
        )

        report = check_dense_swedish_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertEqual(
            ("layout.unnecessary-empty",),
            tuple(issue.code for issue in report.warnings),
        )
        self.assertEqual("$.grid.cells[2][2]", report.warnings[0].path)

    def test_missing_legend_on_axis_is_only_a_warning(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            0,
            2,
            LetterCell(value="A"),
        )

        report = check_dense_swedish_grid(crossword)

        self.assertTrue(report.is_valid)
        missing = tuple(
            issue
            for issue in report.warnings
            if issue.code == "layout.missing-legend"
        )
        self.assertEqual(1, len(missing))
        self.assertEqual("$.grid.cells[0][2]", missing[0].path)

    def test_ambiguous_direction_is_only_a_warning(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            1,
            1,
            LegendCell(texts=("Navíc",)),
        )

        report = check_dense_swedish_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertIn(
            "legend.ambiguous-direction",
            {issue.code for issue in report.warnings},
        )


class FileValidationTest(unittest.TestCase):
    def test_invalid_data_model_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid: {width: 0, height: 5}\n",
                encoding="utf-8",
            )

            report = validate_dense_swedish_grid_file(source)

        self.assertFalse(report.is_valid)
        self.assertEqual(("data-model",), tuple(i.code for i in report.errors))
        self.assertEqual((), report.warnings)

    def test_validate_command_returns_success_for_warning(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            1,
            0,
            LegendCell(texts=("Legenda",), arrows=("right",)),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "warning.yaml"
            write_crossword_grid(crossword, source)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["validate", str(source)])

        self.assertEqual(0, result)
        self.assertIn("formálně platná", stdout.getvalue())
        self.assertIn("varování [legend.arrows]", stderr.getvalue())

    def test_validate_command_returns_error_for_invalid_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.yaml"
            source.write_text("není: mřížka\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["validate", str(source)])

        self.assertEqual(2, result)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("chyba [data-model]", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

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
    SecretCell,
    load_crossword_grid,
    write_crossword_grid,
)
from krizovkar.validation import (
    check_crossword_grid,
    validate_crossword_grid_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRID_CLASSIC_EXAMPLE = PROJECT_ROOT / "examples" / "grid-classic.yaml"
GRID_MIXED_CLUES_EXAMPLE = PROJECT_ROOT / "examples" / "grid-mixed-clues.yaml"


def _legend() -> LegendCell:
    return LegendCell(texts=("Legenda",))


def _good_dense_grid() -> CrosswordGrid:
    empty = EmptyCell()
    letter = LetterCell(value="A")
    cells = (
        (empty, _legend(), _legend(), _legend()),
        (_legend(), letter, letter, letter),
        (_legend(), letter, letter, letter),
        (_legend(), letter, letter, letter),
    )
    return CrosswordGrid(
        format_name="krizovkar",
        kind="grid",
        version=1,
        grid=Grid(width=4, height=4, cells=cells),
    )


def _disconnected_dense_grid() -> CrosswordGrid:
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
    replacement: EmptyCell | LegendCell | LetterCell | SecretCell,
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
        report = check_crossword_grid(_good_dense_grid())

        self.assertTrue(report.is_valid)
        self.assertEqual((), report.errors)
        self.assertEqual((), report.warnings)

    def test_numbered_grid_with_external_clues_has_no_warning(self) -> None:
        crossword = load_crossword_grid(GRID_CLASSIC_EXAMPLE)

        report = check_crossword_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertEqual((), report.warnings)

    def test_numbered_grid_without_clues_has_no_warning(self) -> None:
        crossword = CrosswordGrid(
            format_name="krizovkar",
            kind="grid",
            version=1,
            grid=Grid(
                width=1,
                height=1,
                cells=((LetterCell(value="A", number=1),),),
            ),
        )

        report = check_crossword_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertEqual((), report.warnings)

    def test_inline_and_numbered_clues_can_share_one_grid(self) -> None:
        crossword = load_crossword_grid(GRID_MIXED_CLUES_EXAMPLE)

        report = check_crossword_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertEqual((), report.warnings)

    def test_numbered_word_after_bar_is_checked_as_a_new_start(self) -> None:
        crossword = load_crossword_grid(GRID_MIXED_CLUES_EXAMPLE)
        assert crossword.grid.cells is not None
        rows = [list(row) for row in crossword.grid.cells]
        rows[2][2] = LetterCell(value="O")
        crossword = CrosswordGrid(
            format_name=crossword.format_name,
            kind=crossword.kind,
            version=crossword.version,
            grid=Grid(
                width=crossword.grid.width,
                height=crossword.grid.height,
                cells=tuple(tuple(row) for row in rows),
            ),
        )

        report = check_crossword_grid(crossword)

        self.assertIn(
            "layout.missing-legend",
            {issue.code for issue in report.warnings},
        )

    def test_disconnected_letter_islands_are_only_a_warning(self) -> None:
        report = check_crossword_grid(_disconnected_dense_grid())

        self.assertTrue(report.is_valid)
        self.assertEqual(
            ("layout.disconnected-letters",),
            tuple(issue.code for issue in report.warnings),
        )
        self.assertIn("4 oddělených ostrovů", report.warnings[0].message)

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

        report = check_crossword_grid(crossword)

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

    def test_double_legend_for_right_and_down_is_without_warning(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            2,
            2,
            LegendCell(texts=("Doprava", "Dolů")),
        )

        report = check_crossword_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertEqual((), report.warnings)

    def test_secret_cell_arrow_is_without_warning(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            2,
            2,
            SecretCell(value="A", arrow="right"),
        )

        report = check_crossword_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertEqual((), report.warnings)

    def test_empty_cell_before_words_is_only_a_warning(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            2,
            2,
            EmptyCell(),
        )

        report = check_crossword_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertEqual(
            ("layout.missing-legend", "layout.missing-legend"),
            tuple(issue.code for issue in report.warnings),
        )
        self.assertTrue(
            all(issue.path == "$.grid.cells[2][2]" for issue in report.warnings)
        )

    def test_missing_legend_on_axis_is_only_a_warning(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            0,
            2,
            LetterCell(value="A"),
        )

        report = check_crossword_grid(crossword)

        self.assertTrue(report.is_valid)
        missing = tuple(
            issue
            for issue in report.warnings
            if issue.code == "layout.missing-legend"
        )
        self.assertEqual(1, len(missing))
        self.assertEqual("$.grid.cells[0][2]", missing[0].path)

    def test_one_text_for_two_directions_is_only_a_warning(self) -> None:
        crossword = _replace_cell(
            _good_dense_grid(),
            1,
            1,
            LegendCell(texts=("Navíc",)),
        )

        report = check_crossword_grid(crossword)

        self.assertTrue(report.is_valid)
        self.assertIn(
            "legend.text-count",
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

            report = validate_crossword_grid_file(source)

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

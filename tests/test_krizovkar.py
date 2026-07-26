"""Integrační testy prvního příkazu Křížovkáře."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from reportlab.lib.pagesizes import A5

from krizovkar.cli import main
from krizovkar.model import (
    Coordinate,
    EmptyCell,
    GridDimensions,
    HelpCell,
    LegendCell,
    ModelError,
    SecretCell,
    WordPlacement,
    load_crossword_grid,
    load_crossword_specification,
)
from krizovkar.renderer import RenderError, resolve_page_size

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRID_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "grid-minimal.yaml"
GRID_EMPTY_EXAMPLE = PROJECT_ROOT / "examples" / "grid-empty.yaml"
GRID_HELP_EXAMPLE = PROJECT_ROOT / "examples" / "grid-help.yaml"
GRID_LEGEND_EXAMPLE = PROJECT_ROOT / "examples" / "grid-legend.yaml"
GRID_RANDOM_LETTERS_EXAMPLE = PROJECT_ROOT / "examples" / "grid-random-letters.yaml"
GRID_SECRET_EXAMPLE = PROJECT_ROOT / "examples" / "grid-secret.yaml"
SPECIFICATION_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "specification-minimal.yaml"
SPECIFICATION_PLACED_WORDS_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-placed-words.yaml"
)


class ModelTest(unittest.TestCase):
    def test_loads_minimal_example(self) -> None:
        crossword = load_crossword_grid(GRID_MINIMAL_EXAMPLE)

        self.assertEqual("krizovkar", crossword.format_name)
        self.assertEqual("grid", crossword.kind)
        self.assertEqual(1, crossword.version)
        self.assertEqual(15, crossword.grid.width)
        self.assertEqual(10, crossword.grid.height)
        self.assertIsNone(crossword.grid.cells)

    def test_loads_grid_filled_with_letter_cells(self) -> None:
        crossword = load_crossword_grid(GRID_RANDOM_LETTERS_EXAMPLE)

        self.assertIsNotNone(crossword.grid.cells)
        assert crossword.grid.cells is not None
        self.assertEqual(10, len(crossword.grid.cells))
        self.assertTrue(all(len(row) == 15 for row in crossword.grid.cells))
        self.assertEqual("W", crossword.grid.cells[0][0].value)
        self.assertEqual("I", crossword.grid.cells[-1][-1].value)

    def test_loads_minimal_specification(self) -> None:
        specification = load_crossword_specification(SPECIFICATION_MINIMAL_EXAMPLE)

        self.assertEqual("krizovkar", specification.format_name)
        self.assertEqual("specification", specification.kind)
        self.assertEqual(1, specification.version)
        self.assertIsNone(specification.grid)
        self.assertEqual((), specification.words)
        self.assertIsNone(specification.help_position)

    def test_loads_specification_with_placed_words(self) -> None:
        specification = load_crossword_specification(SPECIFICATION_PLACED_WORDS_EXAMPLE)

        self.assertEqual(GridDimensions(width=7, height=6), specification.grid)
        self.assertEqual(3, len(specification.words))
        first = specification.words[0]
        self.assertIsInstance(first, WordPlacement)
        self.assertEqual("LABE", first.answer)
        self.assertEqual(Coordinate(row=2, column=2), first.start)
        self.assertEqual("horizontal", first.direction)
        self.assertEqual("Česká řeka", first.legend)
        self.assertFalse(first.in_help)
        self.assertEqual(
            ("LES", "EMU"),
            tuple(word.answer for word in specification.words if word.in_help),
        )
        self.assertIsNone(specification.help_position)

    def test_loads_explicit_help_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "explicit-help.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 3}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "    in_help: true\n"
                "help:\n"
                "  position: {row: 3, column: 3}\n",
                encoding="utf-8",
            )

            specification = load_crossword_specification(source)

            self.assertEqual(Coordinate(row=3, column=3), specification.help_position)

    def test_rejects_word_outside_specification_grid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "word-outside-grid.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 3}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 2, column: 2}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.words\[0\].*přesahuje"):
                load_crossword_specification(source)

    def test_rejects_conflicting_word_intersection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "conflicting-intersection.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 3}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 2, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "  - answer: AX\n"
                "    start: {row: 2, column: 2}\n"
                "    direction: vertical\n"
                "    legend: Zkratka\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.words\[1\].*v rozporu"):
                load_crossword_specification(source)

    def test_rejects_help_position_occupied_by_word(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "occupied-help.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 3}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "    in_help: true\n"
                "help:\n"
                "  position: {row: 1, column: 2}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.help\.position"):
                load_crossword_specification(source)

    def test_rejects_automatic_help_without_empty_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "full-grid.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 1, height: 1}\n"
                "words:\n"
                "  - answer: A\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Písmeno\n"
                "    in_help: true\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, "nemá prázdnou buňku"):
                load_crossword_specification(source)

    def test_loads_secret_cells(self) -> None:
        crossword = load_crossword_grid(GRID_SECRET_EXAMPLE)

        assert crossword.grid.cells is not None
        secret_cells = crossword.grid.cells[3][2:9]
        self.assertTrue(all(isinstance(cell, SecretCell) for cell in secret_cells))
        self.assertEqual("TAJENKA", "".join(cell.value for cell in secret_cells))

    def test_loads_single_and_double_legend(self) -> None:
        crossword = load_crossword_grid(GRID_LEGEND_EXAMPLE)

        assert crossword.grid.cells is not None
        single = crossword.grid.cells[0][0]
        double = crossword.grid.cells[2][3]
        self.assertIsInstance(single, LegendCell)
        self.assertIsInstance(double, LegendCell)
        assert isinstance(single, LegendCell)
        assert isinstance(double, LegendCell)
        self.assertEqual(("Česká řeka",), single.texts)
        self.assertEqual(("Savec", "Pohoří"), double.texts)
        self.assertEqual(("right",), single.arrows)
        self.assertEqual(("right", "down"), double.arrows)

    def test_rejects_legend_with_mismatched_arrow_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "mismatched-arrows.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: legend, texts: [První, Druhý], "
                "arrows: [right]}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, "pro každý text"):
                load_crossword_grid(source)

    def test_loads_empty_cells(self) -> None:
        crossword = load_crossword_grid(GRID_EMPTY_EXAMPLE)

        assert crossword.grid.cells is not None
        empty_cells = [
            cell
            for row in crossword.grid.cells
            for cell in row
            if isinstance(cell, EmptyCell)
        ]
        self.assertEqual(10, len(empty_cells))

    def test_loads_help_cell(self) -> None:
        crossword = load_crossword_grid(GRID_HELP_EXAMPLE)

        assert crossword.grid.cells is not None
        help_cell = crossword.grid.cells[2][3]
        self.assertIsInstance(help_cell, HelpCell)
        assert isinstance(help_cell, HelpCell)
        self.assertEqual(("ARA", "EMU", "ÍRÁN"), help_cell.words)

    def test_grid_loader_rejects_specification(self) -> None:
        with self.assertRaisesRegex(ModelError, r"\$\.kind"):
            load_crossword_grid(SPECIFICATION_MINIMAL_EXAMPLE)

    def test_rejects_non_positive_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 0\n"
                "  height: 10\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.grid\.width"):
                load_crossword_grid(source)

    def test_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "duplicate.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 15\n"
                "  width: 20\n"
                "  height: 10\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, "duplicate key"):
                load_crossword_grid(source)

    def test_rejects_row_with_wrong_number_of_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "short-row.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 2\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: A}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"grid\.width"):
                load_crossword_grid(source)

    def test_rejects_invalid_letter_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid-letter.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: AA}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ModelError, r"\$\.grid\.cells\[0\]\[0\]\.value"
            ):
                load_crossword_grid(source)

    def test_rejects_unknown_cell_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unknown-cell.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: unknown, value: A}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.grid\.cells\[0\]\[0\]\.type"):
                load_crossword_grid(source)

    def test_rejects_legend_with_three_texts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "long-legend.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: legend, texts: [První, Druhý, Třetí]}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ModelError, r"\$\.grid\.cells\[0\]\[0\]\.texts"
            ):
                load_crossword_grid(source)

    def test_rejects_content_in_empty_cell(self) -> None:
        invalid_contents = ("value: A", "texts: [Legenda]", "words: [Pomůcka]")
        for content in invalid_contents:
            with (
                self.subTest(content=content),
                tempfile.TemporaryDirectory() as directory,
            ):
                source = Path(directory) / "nonempty-empty-cell.yaml"
                source.write_text(
                    "format: krizovkar\n"
                    "kind: grid\n"
                    "version: 1\n"
                    "grid:\n"
                    "  width: 1\n"
                    "  height: 1\n"
                    "  cells:\n"
                    f"    - [{{type: empty, {content}}}]\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ModelError, r"\$\.grid\.cells\[0\]\[0\]"):
                    load_crossword_grid(source)

    def test_rejects_invalid_help_words(self) -> None:
        invalid_words = ("[]", '["   "]')
        for words in invalid_words:
            with (
                self.subTest(words=words),
                tempfile.TemporaryDirectory() as directory,
            ):
                source = Path(directory) / "invalid-help.yaml"
                source.write_text(
                    "format: krizovkar\n"
                    "kind: grid\n"
                    "version: 1\n"
                    "grid:\n"
                    "  width: 1\n"
                    "  height: 1\n"
                    "  cells:\n"
                    f"    - [{{type: help, words: {words}}}]\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    ModelError, r"\$\.grid\.cells\[0\]\[0\]\.words"
                ):
                    load_crossword_grid(source)

    def test_rejects_help_without_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "help-without-words.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: help}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.grid\.cells\[0\]\[0\]"):
                load_crossword_grid(source)


class CommandTest(unittest.TestCase):
    def test_page_format_names_are_case_insensitive(self) -> None:
        self.assertEqual(A5, resolve_page_size("a5"))

    def test_rejects_unsupported_page_format(self) -> None:
        with self.assertRaisesRegex(RenderError, "nepodporovaný formát stránky"):
            resolve_page_size("A7")

    def test_render_creates_pdf_and_refuses_accidental_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossword.pdf"
            command = [
                "render",
                str(GRID_LEGEND_EXAMPLE),
                "--output",
                str(output),
                "--page-format",
                "A5",
            ]

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(command)

            self.assertEqual(0, result)
            self.assertIn("PDF vytvořeno:", stdout.getvalue())
            pdf = output.read_bytes()
            self.assertTrue(pdf.startswith(b"%PDF-"))
            self.assertIn(b"%%EOF", pdf[-1024:])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                second_result = main(command)

            self.assertEqual(2, second_result)
            self.assertIn("již existuje", stderr.getvalue())

            with redirect_stdout(io.StringIO()):
                forced_result = main([*command, "--force"])

            self.assertEqual(0, forced_result)

    def test_render_handles_empty_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "empty-cells.pdf"

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "render",
                        str(GRID_EMPTY_EXAMPLE),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))

    def test_render_handles_help_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "help-cell.pdf"

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "render",
                        str(GRID_HELP_EXAMPLE),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()

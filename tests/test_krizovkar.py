"""Integrační testy prvního příkazu Křížovkáře."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from reportlab.lib.pagesizes import A5

from krizovkar.cli import main
from krizovkar.model import ModelError, load_crossword
from krizovkar.renderer import RenderError, resolve_page_size

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "minimal.yaml"
RANDOM_LETTERS_EXAMPLE = PROJECT_ROOT / "examples" / "random-letters.yaml"


class ModelTest(unittest.TestCase):
    def test_loads_minimal_example(self) -> None:
        crossword = load_crossword(MINIMAL_EXAMPLE)

        self.assertEqual("krizovkar", crossword.format_name)
        self.assertEqual(1, crossword.version)
        self.assertEqual(15, crossword.grid.width)
        self.assertEqual(10, crossword.grid.height)
        self.assertIsNone(crossword.grid.cells)

    def test_loads_grid_filled_with_letter_cells(self) -> None:
        crossword = load_crossword(RANDOM_LETTERS_EXAMPLE)

        self.assertIsNotNone(crossword.grid.cells)
        assert crossword.grid.cells is not None
        self.assertEqual(10, len(crossword.grid.cells))
        self.assertTrue(all(len(row) == 15 for row in crossword.grid.cells))
        self.assertEqual("W", crossword.grid.cells[0][0].value)
        self.assertEqual("I", crossword.grid.cells[-1][-1].value)

    def test_rejects_non_positive_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.yaml"
            source.write_text(
                "format: krizovkar\nversion: 1\ngrid:\n  width: 0\n  height: 10\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.grid\.width"):
                load_crossword(source)

    def test_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "duplicate.yaml"
            source.write_text(
                "format: krizovkar\n"
                "version: 1\n"
                "grid:\n"
                "  width: 15\n"
                "  width: 20\n"
                "  height: 10\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, "duplicate key"):
                load_crossword(source)

    def test_rejects_row_with_wrong_number_of_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "short-row.yaml"
            source.write_text(
                "format: krizovkar\n"
                "version: 1\n"
                "grid:\n"
                "  width: 2\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: A}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"grid\.width"):
                load_crossword(source)

    def test_rejects_invalid_letter_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid-letter.yaml"
            source.write_text(
                "format: krizovkar\n"
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
                load_crossword(source)


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
                str(RANDOM_LETTERS_EXAMPLE),
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


if __name__ == "__main__":
    unittest.main()

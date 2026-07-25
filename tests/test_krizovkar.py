"""Integrační testy prvního příkazu Křížovkáře."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from krizovkar.cli import main
from krizovkar.model import ModelError, load_crossword

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "minimal.yaml"


class ModelTest(unittest.TestCase):
    def test_loads_minimal_example(self) -> None:
        crossword = load_crossword(MINIMAL_EXAMPLE)

        self.assertEqual("krizovkar", crossword.format_name)
        self.assertEqual(1, crossword.version)
        self.assertEqual(15, crossword.grid.width)
        self.assertEqual(10, crossword.grid.height)

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


class CommandTest(unittest.TestCase):
    def test_render_creates_pdf_and_refuses_accidental_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossword.pdf"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(["render", str(MINIMAL_EXAMPLE), "--output", str(output)])

            self.assertEqual(0, result)
            self.assertIn("PDF vytvořeno:", stdout.getvalue())
            pdf = output.read_bytes()
            self.assertTrue(pdf.startswith(b"%PDF-"))
            self.assertIn(b"%%EOF", pdf[-1024:])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                second_result = main(
                    ["render", str(MINIMAL_EXAMPLE), "--output", str(output)]
                )

            self.assertEqual(2, second_result)
            self.assertIn("již existuje", stderr.getvalue())

            with redirect_stdout(io.StringIO()):
                forced_result = main(
                    [
                        "render",
                        str(MINIMAL_EXAMPLE),
                        "--output",
                        str(output),
                        "--force",
                    ]
                )

            self.assertEqual(0, forced_result)


if __name__ == "__main__":
    unittest.main()

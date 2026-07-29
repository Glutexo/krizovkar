"""Testy logiky grafického rozhraní bez otevírání okna."""

from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from krizovkar.generator import GenerationError
from krizovkar.gui import (
    GuiInputError,
    TemplateSettings,
    _configure_tk_runtime,
    create_template,
    main,
    parse_template_settings,
)
from krizovkar.model import (
    TemplateEmptyCell,
    TemplateLegendCell,
    TemplateLetterCell,
    load_crossword_template,
    write_crossword_template,
)


class GuiTest(unittest.TestCase):
    def test_configures_bundled_tk_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library_root = Path(directory) / "lib"
            tcl_library = library_root / f"tcl{tk.TclVersion:.1f}"
            tk_library = library_root / f"tk{tk.TkVersion:.1f}"
            tcl_library.mkdir(parents=True)
            tk_library.mkdir()
            with (
                patch("krizovkar.gui.sys.base_prefix", directory),
                patch.dict(os.environ, {}, clear=True),
            ):
                _configure_tk_runtime()

                self.assertEqual(str(tcl_library), os.environ["TCL_LIBRARY"])
                self.assertEqual(str(tk_library), os.environ["TK_LIBRARY"])

    def test_parses_template_settings(self) -> None:
        self.assertEqual(
            TemplateSettings(layout="swedish", width=15, height=10),
            parse_template_settings("swedish", " 15 ", "10"),
        )

    def test_rejects_unknown_layout(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "Vyberte způsob rozvržení"):
            parse_template_settings("", "15", "10")

    def test_rejects_non_integer_dimension(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "Počet sloupců musí být celé"):
            parse_template_settings("swedish", "patnáct", "10")

    def test_rejects_non_positive_dimension(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "Počet řádků musí být kladný"):
            parse_template_settings("swedish", "15", "0")

    def test_creates_swedish_template(self) -> None:
        template = create_template(
            TemplateSettings(layout="swedish", width=5, height=5)
        )
        cells = tuple(cell for row in template.grid.cells for cell in row)

        self.assertTrue(any(isinstance(cell, TemplateLegendCell) for cell in cells))
        self.assertTrue(any(isinstance(cell, TemplateEmptyCell) for cell in cells))
        self.assertTrue(any(isinstance(cell, TemplateLetterCell) for cell in cells))

    def test_creates_numbered_template(self) -> None:
        template = create_template(
            TemplateSettings(layout="numbered", width=5, height=5)
        )

        self.assertTrue(
            all(
                isinstance(cell, TemplateLetterCell)
                for row in template.grid.cells
                for cell in row
            )
        )

    def test_saves_created_template_in_project_format(self) -> None:
        template = create_template(
            TemplateSettings(layout="swedish", width=5, height=5)
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sablona.yaml"

            write_crossword_template(template, output)

            self.assertEqual(template, load_crossword_template(output))

    def test_reports_unsupported_template_size(self) -> None:
        with self.assertRaises(GenerationError):
            create_template(TemplateSettings(layout="swedish", width=3, height=3))

    def test_main_reports_unavailable_tk(self) -> None:
        error_output = StringIO()
        with (
            patch("krizovkar.gui.tk.Tk", side_effect=tk.TclError("bez displeje")),
            redirect_stderr(error_output),
        ):
            exit_code = main()

        self.assertEqual(2, exit_code)
        self.assertIn("grafické rozhraní nelze spustit", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()

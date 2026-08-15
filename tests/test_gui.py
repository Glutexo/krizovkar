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

from krizovkar.gui import (
    GuiInputError,
    SpecificationSettings,
    _configure_tk_runtime,
    create_blank_template,
    create_specification,
    create_template,
    main,
    parse_specification_settings,
    parse_template_settings,
    parse_word_placement,
    prepare_crossword,
)
from krizovkar.model import (
    Coordinate,
    LegendCell,
    LetterCell,
    WordPlacement,
    load_crossword_specification,
    write_crossword_specification,
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

    def test_parses_specification_settings(self) -> None:
        self.assertEqual(
            SpecificationSettings(width=15, height=10),
            parse_specification_settings(" 15 ", "10"),
        )

    def test_rejects_non_integer_dimension(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "Počet sloupců musí být celé"):
            parse_specification_settings("patnáct", "10")

    def test_rejects_non_positive_dimension(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "Počet řádků musí být kladný"):
            parse_specification_settings("15", "0")

    def test_limits_automatically_generated_template_size(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "nejvýše 50"):
            parse_template_settings("51", "10")

    def test_parses_and_normalizes_word(self) -> None:
        self.assertEqual(
            WordPlacement(
                answer="CHATA",
                start=Coordinate(row=2, column=3),
                direction="vertical",
                legend="Stavení",
                in_help=True,
            ),
            parse_word_placement(
                " chata ",
                " Stavení ",
                "2",
                "3",
                "vertical",
                True,
            ),
        )

    def test_rejects_empty_word_legend(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "Vyplňte legendu"):
            parse_word_placement("LABE", "  ", "1", "1", "horizontal", False)

    def test_creates_specification_from_placed_words(self) -> None:
        word = parse_word_placement(
            "LABE",
            "Česká řeka",
            "2",
            "2",
            "horizontal",
            False,
        )

        specification = create_specification(
            SpecificationSettings(width=7, height=6),
            (word,),
        )

        self.assertEqual("specification", specification.kind)
        self.assertEqual((word,), specification.words)
        self.assertEqual(7, specification.grid.width)
        self.assertEqual(6, specification.grid.height)

    def test_refuses_specification_without_words(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "alespoň jedno heslo"):
            create_specification(
                SpecificationSettings(width=15, height=10),
                (),
            )

    def test_refuses_word_outside_grid(self) -> None:
        word = parse_word_placement(
            "LABE",
            "Česká řeka",
            "3",
            "2",
            "horizontal",
            False,
        )

        with self.assertRaisesRegex(GuiInputError, "přesahuje mřížku"):
            create_specification(
                SpecificationSettings(width=3, height=3),
                (word,),
            )

    def test_refuses_conflicting_intersection(self) -> None:
        horizontal = parse_word_placement(
            "ABC",
            "Abeceda",
            "2",
            "1",
            "horizontal",
            False,
        )
        vertical = parse_word_placement(
            "AX",
            "Zkratka",
            "1",
            "2",
            "vertical",
            False,
        )

        with self.assertRaisesRegex(GuiInputError, "v rozporu"):
            create_specification(
                SpecificationSettings(width=3, height=3),
                (horizontal, vertical),
            )

    def test_saves_created_specification_in_project_format(self) -> None:
        word = parse_word_placement(
            "LABE",
            "Česká řeka",
            "2",
            "2",
            "horizontal",
            False,
        )
        specification = create_specification(
            SpecificationSettings(width=7, height=6),
            (word,),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "zadani.yaml"

            write_crossword_specification(specification, output)

            self.assertEqual(
                specification,
                load_crossword_specification(output),
            )

    def test_creates_selected_template_from_gui_specification(self) -> None:
        word = parse_word_placement(
            "LABE",
            "Česká řeka",
            "2",
            "2",
            "horizontal",
            False,
        )
        specification = create_specification(
            SpecificationSettings(width=7, height=6),
            (word,),
        )

        template = create_template(specification, "swedish")

        self.assertEqual("LABE", template.slots[0].answer)
        self.assertIsNotNone(template.slots[0].legend_position)

    def test_prepares_printable_crossword_from_placed_words(self) -> None:
        word = parse_word_placement(
            "LABE",
            "Česká řeka",
            "2",
            "2",
            "horizontal",
            False,
        )
        specification = create_specification(
            SpecificationSettings(width=7, height=6),
            (word,),
        )

        prepared = prepare_crossword(specification, "swedish")

        self.assertEqual("template", prepared.template.kind)
        self.assertEqual("grid", prepared.grid.kind)
        assert prepared.grid.grid.cells is not None
        self.assertIsInstance(prepared.grid.grid.cells[1][0], LegendCell)
        first_letter = prepared.grid.grid.cells[1][1]
        self.assertIsInstance(first_letter, LetterCell)
        assert isinstance(first_letter, LetterCell)
        self.assertEqual("L", first_letter.value)

    def test_creates_blank_numbered_template_without_words(self) -> None:
        template = create_blank_template(
            SpecificationSettings(width=7, height=6),
            "numbered",
        )

        self.assertEqual("template", template.kind)
        self.assertEqual(7, template.grid.width)
        self.assertEqual(6, template.grid.height)
        self.assertTrue(template.slots)
        self.assertTrue(all(slot.legend_position is None for slot in template.slots))

    def test_reports_too_small_blank_template_as_gui_error(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "nelze rozdělit"):
            create_blank_template(
                SpecificationSettings(width=2, height=2),
                "swedish",
            )

    def test_reports_template_layout_error_as_gui_input_error(self) -> None:
        word = parse_word_placement(
            "LABE",
            "Česká řeka",
            "1",
            "1",
            "horizontal",
            False,
        )
        specification = create_specification(
            SpecificationSettings(width=7, height=6),
            (word,),
        )

        with self.assertRaisesRegex(GuiInputError, "vepsaná legenda"):
            create_template(specification, "swedish")

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

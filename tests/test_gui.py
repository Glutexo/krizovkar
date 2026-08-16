"""Testy logiky grafického rozhraní bez otevírání okna."""

from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, call, patch

from krizovkar.generator import create_grid_from_template
from krizovkar.gui import (
    CrosswordApplication,
    GuiInputError,
    TemplateSettings,
    _configure_tk_runtime,
    clear_template_slot,
    create_blank_template,
    fill_template_slot,
    main,
    parse_slot_content,
    parse_template_settings,
    slot_coordinates,
    template_is_complete,
    template_slot_pattern,
)
from krizovkar.model import (
    LetterCell,
    load_crossword_template,
    write_crossword_template,
)
from krizovkar.renderer import RenderError

PDF_BYTES = b"%PDF-1.7\n%%EOF\n"


def _fake_lualatex(source: Path, output_directory: Path) -> Path:
    assert source.read_text(encoding="utf-8").startswith(
        "% Automaticky vytvořil Křížovkář."
    )
    output = output_directory / f"{source.stem}.pdf"
    output.write_bytes(PDF_BYTES)
    return output


def _filled_numbered_template():
    template = create_blank_template(TemplateSettings(3, 3), "numbered")
    entries = {
        "h1": ("ABC", "První řádek"),
        "h2": ("DEF", "Druhý řádek"),
        "h3": ("GHI", "Třetí řádek"),
        "v1": ("ADG", "První sloupec"),
        "v2": ("BEH", "Druhý sloupec"),
        "v3": ("CFI", "Třetí sloupec"),
    }
    for identifier, (answer, clue) in entries.items():
        template = fill_template_slot(template, identifier, answer, clue)
    return template


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
            TemplateSettings(width=15, height=10),
            parse_template_settings(" 15 ", "10"),
        )

    def test_rejects_non_integer_dimension(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "Počet sloupců musí být celé"):
            parse_template_settings("patnáct", "10")

    def test_rejects_non_positive_dimension(self) -> None:
        with self.assertRaisesRegex(
            GuiInputError,
            "Počet řádků musí být kladný",
        ):
            parse_template_settings("15", "0")

    def test_limits_automatically_generated_template_size(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "nejvýše 50"):
            parse_template_settings("51", "10")

    def test_parses_and_normalizes_slot_content(self) -> None:
        self.assertEqual(
            ("CHATA", "Stavení"),
            parse_slot_content(" chata ", " Stavení ", 4),
        )

    def test_rejects_answer_with_wrong_slot_length(self) -> None:
        with self.assertRaisesRegex(
            GuiInputError,
            "místo má 5 polí, ale heslo má 4 pole",
        ):
            parse_slot_content("CHATA", "Stavení", 5)

    def test_rejects_empty_clue(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "Vyplňte nápovědu"):
            parse_slot_content("CHATA", "  ", 4)

    def test_creates_swedish_template_before_words(self) -> None:
        template = create_blank_template(
            TemplateSettings(width=7, height=6),
            "swedish",
        )

        self.assertEqual("template", template.kind)
        self.assertTrue(template.slots)
        self.assertTrue(all(slot.answer is None for slot in template.slots))
        self.assertTrue(
            any(slot.legend_position is not None for slot in template.slots)
        )

    def test_creates_numbered_template_before_words(self) -> None:
        template = create_blank_template(
            TemplateSettings(width=7, height=6),
            "numbered",
        )

        self.assertTrue(template.slots)
        self.assertTrue(all(slot.legend_position is None for slot in template.slots))

    def test_reports_too_small_template_as_gui_error(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "nelze rozdělit"):
            create_blank_template(
                TemplateSettings(width=2, height=2),
                "swedish",
            )

    def test_returns_slot_coordinates_in_answer_order(self) -> None:
        template = create_blank_template(TemplateSettings(7, 6), "swedish")
        vertical = next(slot for slot in template.slots if slot.direction == "vertical")

        coordinates = slot_coordinates(vertical)

        self.assertEqual(vertical.length, len(coordinates))
        self.assertEqual(vertical.start, coordinates[0])
        self.assertEqual(vertical.start.row + 1, coordinates[1].row)
        self.assertEqual(vertical.start.column, coordinates[1].column)

    def test_fills_selected_template_slot(self) -> None:
        template = create_blank_template(TemplateSettings(7, 6), "swedish")

        filled = fill_template_slot(
            template,
            "h1",
            "abcdef",
            "Prvních šest písmen",
        )

        slot = next(slot for slot in filled.slots if slot.identifier == "h1")
        self.assertEqual("ABCDEF", slot.answer)
        self.assertEqual("Prvních šest písmen", slot.clue)
        grid = create_grid_from_template(filled)
        assert grid.grid.cells is not None
        first_letter = grid.grid.cells[slot.start.row - 1][slot.start.column - 1]
        self.assertIsInstance(first_letter, LetterCell)
        assert isinstance(first_letter, LetterCell)
        self.assertEqual("A", first_letter.value)

    def test_shows_letters_known_from_crossings(self) -> None:
        template = create_blank_template(TemplateSettings(7, 6), "swedish")
        template = fill_template_slot(template, "h1", "ABCDEF", "Abeceda")

        self.assertEqual(
            ("A", None, None, None, None),
            template_slot_pattern(template, "v1"),
        )

    def test_rejects_conflicting_crossing(self) -> None:
        template = create_blank_template(TemplateSettings(7, 6), "swedish")
        template = fill_template_slot(template, "h1", "ABCDEF", "Abeceda")

        with self.assertRaisesRegex(
            GuiInputError,
            "musí být v 1. poli písmeno 'A', ne 'Z'",
        ):
            fill_template_slot(template, "v1", "ZABAK", "Obojživelník")

    def test_rejects_duplicate_answer(self) -> None:
        template = create_blank_template(TemplateSettings(7, 6), "swedish")
        template = fill_template_slot(template, "h1", "ABCDEF", "Abeceda")

        with self.assertRaisesRegex(GuiInputError, "už je použité"):
            fill_template_slot(template, "h2", "ABCDEF", "Totéž heslo")

    def test_clears_selected_template_slot(self) -> None:
        template = create_blank_template(TemplateSettings(7, 6), "swedish")
        template = fill_template_slot(template, "h1", "ABCDEF", "Abeceda")

        cleared = clear_template_slot(template, "h1")

        slot = next(slot for slot in cleared.slots if slot.identifier == "h1")
        self.assertIsNone(slot.answer)
        self.assertIsNone(slot.clue)

    def test_recognizes_complete_crossword(self) -> None:
        template = _filled_numbered_template()

        self.assertTrue(template_is_complete(template))

        template = clear_template_slot(template, "v3")
        self.assertFalse(template_is_complete(template))

    def test_saves_partially_filled_template_in_project_format(self) -> None:
        template = create_blank_template(TemplateSettings(7, 6), "swedish")
        template = fill_template_slot(template, "h1", "ABCDEF", "Abeceda")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "krizovka.yaml"

            write_crossword_template(template, output)

            self.assertEqual(template, load_crossword_template(output))

    def test_updating_template_keeps_crossword_document(self) -> None:
        application = Mock()
        crossword = Mock()
        new_template = create_blank_template(TemplateSettings(3, 3), "numbered")
        application._template = crossword
        application.width_value.get.return_value = "3"
        application.height_value.get.return_value = "3"
        application.layout_value.get.return_value = "numbered"

        with patch(
            "krizovkar.gui.create_blank_template",
            return_value=new_template,
        ):
            CrosswordApplication.create_new_template(application)

        self.assertIs(new_template, application._base_template)
        self.assertIs(crossword, application._template)
        application.create_crossword_from_template.assert_not_called()

    def test_creating_first_template_keeps_crossword_document_empty(self) -> None:
        application = Mock()
        new_template = create_blank_template(TemplateSettings(3, 3), "numbered")
        application._template = None
        application.width_value.get.return_value = "3"
        application.height_value.get.return_value = "3"
        application.layout_value.get.return_value = "numbered"

        with patch(
            "krizovkar.gui.create_blank_template",
            return_value=new_template,
        ):
            CrosswordApplication.create_new_template(application)

        self.assertIs(new_template, application._base_template)
        self.assertIsNone(application._template)
        application.create_crossword_from_template.assert_not_called()

    def test_empty_crossword_offers_creation_from_current_template(self) -> None:
        application = Mock()
        application._template = None

        CrosswordApplication._refresh_crossword_view(application)

        application.replace_crossword_template_button.configure.assert_called_once_with(
            text="Vytvořit podle aktuální šablony"
        )
        application._set_slot_form_state.assert_called_once_with("disabled")

    def test_crossword_is_created_explicitly_from_template(self) -> None:
        application = Mock()
        template = create_blank_template(TemplateSettings(3, 3), "numbered")
        application._base_template = template
        application._template = None
        application._layout = "numbered"

        CrosswordApplication.create_crossword_from_template(
            application,
            select_document=False,
        )

        self.assertIs(template, application._template)
        self.assertEqual("numbered", application._crossword_layout)
        application._rebuild_slot_tree.assert_called_once_with()
        application._refresh_crossword_view.assert_called_once_with()
        application.notebook.select.assert_not_called()

    def test_crossword_pdf_actions_choose_puzzle_and_solution(self) -> None:
        application = Mock()
        grid = Mock()
        application._complete_grid_or_error.return_value = grid
        application.crossword_page_format_value.get.return_value = "A5"

        CrosswordApplication.save_crossword_pdf(application)
        CrosswordApplication.save_solution_pdf(application)

        self.assertEqual(
            [
                call(
                    grid,
                    filled=False,
                    title="Uložit křížovku bez písmen",
                    initialfile="krizovka.pdf",
                    success_message="Křížovka bez písmen byla uložena",
                    page_format="A5",
                    document="crossword",
                ),
                call(
                    grid,
                    filled=True,
                    title="Uložit řešení křížovky",
                    initialfile="reseni.pdf",
                    success_message="Řešení bylo uloženo",
                    page_format="A5",
                    document="crossword",
                ),
            ],
            application._save_pdf.call_args_list,
        )

    def test_blank_template_pdf_action_uses_unfilled_template(self) -> None:
        application = Mock()
        application._base_template = create_blank_template(
            TemplateSettings(3, 3),
            "numbered",
        )
        application.template_page_format_value.get.return_value = "Letter"

        with patch("krizovkar.gui.create_grid_from_template") as create_grid:
            CrosswordApplication.save_blank_template_pdf(application)

        create_grid.assert_called_once_with(application._base_template)
        application._save_pdf.assert_called_once_with(
            create_grid.return_value,
            filled=False,
            title="Uložit šablonu k tisku",
            initialfile="sablona.pdf",
            success_message="Šablona k tisku byla uložena",
            page_format="Letter",
            document="template",
        )

    def test_current_document_actions_follow_selected_tab(self) -> None:
        application = Mock()
        application.notebook.index.side_effect = (0, 1, 0, 1)

        CrosswordApplication.save_current_document_data(application)
        CrosswordApplication.save_current_document_data(application)
        CrosswordApplication.save_current_document_pdf(application)
        CrosswordApplication.save_current_document_pdf(application)

        application.save_blank_template_data.assert_called_once_with()
        application.save_current_template_data.assert_called_once_with()
        application.save_blank_template_pdf.assert_called_once_with()
        application.save_crossword_pdf.assert_called_once_with()

    def test_file_menu_follows_template_document(self) -> None:
        application = Mock()
        application.notebook.index.return_value = 0
        application._base_template = Mock()

        CrosswordApplication._refresh_file_menu(application)

        self.assertEqual(
            [
                call(0, label="Uložit šablonu (YAML)…", state="normal"),
                call(
                    1,
                    label="Uložit šablonu k tisku (PDF)…",
                    state="normal",
                ),
                call(3, state="disabled"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )

    def test_file_menu_enables_complete_crossword_outputs(self) -> None:
        application = Mock()
        application.notebook.index.return_value = 1
        application._template = _filled_numbered_template()

        CrosswordApplication._refresh_file_menu(application)

        self.assertEqual(
            [
                call(0, label="Uložit křížovku (YAML)…", state="normal"),
                call(
                    1,
                    label="Uložit křížovku bez písmen (PDF)…",
                    state="normal",
                ),
                call(3, state="normal"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )

    def test_saves_pdf_through_renderer_without_manual_dialog(self) -> None:
        template = _filled_numbered_template()
        grid = create_grid_from_template(template)
        application = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "krizovka.pdf"
            application._choose_output.return_value = (output, False)

            with patch(
                "krizovkar.renderer._run_lualatex",
                side_effect=_fake_lualatex,
            ):
                CrosswordApplication._save_pdf(
                    application,
                    grid,
                    filled=False,
                    title="Uložit křížovku bez písmen",
                    initialfile="krizovka.pdf",
                    success_message="Křížovka bez písmen byla uložena",
                    page_format="A5",
                    document="crossword",
                )

            self.assertEqual(PDF_BYTES, output.read_bytes())

        application._choose_output.assert_called_once_with(
            title="Uložit křížovku bez písmen",
            initialfile="krizovka.pdf",
            extension=".pdf",
            filetypes=(("PDF soubory", "*.pdf"), ("Všechny soubory", "*")),
            overwrite_title="Přepsat PDF?",
        )
        self.assertEqual(
            [
                call("crossword", "Vytvářím PDF…"),
                call(
                    "crossword",
                    f"Křížovka bez písmen byla uložena: {output}",
                    success=True,
                ),
            ],
            application._set_document_status.call_args_list,
        )
        self.assertEqual(
            [call(cursor="watch"), call(cursor="")],
            application.root.configure.call_args_list,
        )
        application.root.update_idletasks.assert_called_once_with()
        application._show_action_error.assert_not_called()

    def test_pdf_render_error_is_shown_and_restores_cursor(self) -> None:
        application = Mock()
        application._choose_output.return_value = (Path("sablona.pdf"), False)

        with patch(
            "krizovkar.gui.render_pdf",
            side_effect=RenderError("nainstalujte TeX Live"),
        ):
            CrosswordApplication._save_pdf(
                application,
                Mock(),
                filled=False,
                title="Uložit šablonu k tisku",
                initialfile="sablona.pdf",
                success_message="Šablona k tisku byla uložena",
                page_format="A4",
                document="template",
            )

        application._show_action_error.assert_called_once_with(
            "PDF nelze vytvořit",
            "nainstalujte TeX Live",
            document="template",
        )
        application._set_document_status.assert_called_once_with(
            "template",
            "Vytvářím PDF…",
        )
        self.assertEqual(
            [call(cursor="watch"), call(cursor="")],
            application.root.configure.call_args_list,
        )

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

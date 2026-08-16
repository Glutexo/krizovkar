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
    CrosswordDocumentWindow,
    GuiInputError,
    TemplateSettings,
    _configure_tk_runtime,
    clear_template_slot,
    create_blank_template,
    fill_template_slot,
    load_editable_document,
    main,
    parse_slot_content,
    parse_template_settings,
    slot_coordinates,
    template_is_complete,
    template_layout,
    template_slot_pattern,
)
from krizovkar.model import (
    CrosswordDocument,
    LetterCell,
    create_crossword_document,
    load_crossword_document,
    load_crossword_template,
    write_crossword_document,
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


def _filled_numbered_crossword():
    template = create_crossword_document(
        create_blank_template(TemplateSettings(3, 3), "numbered")
    )
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
        template = _filled_numbered_crossword()

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

    def test_recognizes_layout_stored_in_document(self) -> None:
        swedish = create_blank_template(TemplateSettings(7, 6), "swedish")
        numbered = create_blank_template(TemplateSettings(7, 6), "numbered")

        self.assertEqual("swedish", template_layout(swedish))
        self.assertEqual("numbered", template_layout(numbered))

    def test_filling_crossword_preserves_document_kind(self) -> None:
        crossword = create_crossword_document(
            create_blank_template(TemplateSettings(7, 6), "swedish")
        )

        filled = fill_template_slot(
            crossword,
            "h1",
            "ABCDEF",
            "Abeceda",
        )

        self.assertIsInstance(filled, CrosswordDocument)
        self.assertEqual("crossword", filled.kind)

    def test_gui_loader_selects_editor_from_yaml_kind(self) -> None:
        template = create_blank_template(TemplateSettings(3, 3), "numbered")
        crossword = create_crossword_document(template)
        with tempfile.TemporaryDirectory() as directory:
            template_path = Path(directory) / "sablona.yaml"
            crossword_path = Path(directory) / "krizovka.yaml"
            write_crossword_template(template, template_path)
            write_crossword_document(crossword, crossword_path)

            loaded_template = load_editable_document(template_path)
            loaded_crossword = load_editable_document(crossword_path)

        self.assertEqual("template", loaded_template.kind)
        self.assertIsInstance(loaded_crossword, CrosswordDocument)

    def test_template_update_changes_only_its_document_window(self) -> None:
        window = Mock()
        new_template = create_blank_template(TemplateSettings(3, 3), "numbered")
        window.width_value.get.return_value = "3"
        window.height_value.get.return_value = "3"
        window.layout_value.get.return_value = "numbered"

        with patch(
            "krizovkar.gui.create_blank_template",
            return_value=new_template,
        ):
            CrosswordDocumentWindow.create_new_template(window)

        self.assertIs(new_template, window._base_template)
        window._set_dirty.assert_called_once_with(True)
        window._refresh_template_view.assert_called_once_with()

    def test_template_opens_crossword_in_new_document_window(self) -> None:
        window = Mock()
        template = create_blank_template(TemplateSettings(3, 3), "numbered")
        window._base_template = template

        CrosswordDocumentWindow.create_crossword_from_template(window)

        window.application.new_crossword_document.assert_called_once_with(template)
        window._set_template_status.assert_called_once_with(
            "Křížovka podle této šablony byla otevřena v novém okně.",
            success=True,
        )

    def test_application_creates_crossword_as_new_document(self) -> None:
        application = Mock()
        template = create_blank_template(TemplateSettings(3, 3), "numbered")
        expected_window = Mock()
        application._open_window.return_value = expected_window

        result = CrosswordApplication.new_crossword_document(
            application,
            template,
        )

        document = application._open_window.call_args.args[0]
        self.assertIsInstance(document, CrosswordDocument)
        self.assertEqual("crossword", document.kind)
        application._open_window.assert_called_once_with(document, dirty=True)
        self.assertIs(expected_window, result)

    def test_application_owner_stays_hidden_behind_document_windows(self) -> None:
        root = Mock()

        application = CrosswordApplication(root)

        root.withdraw.assert_called_once_with()
        self.assertEqual([], application._windows)

    def test_application_exits_after_last_document_window_closes(self) -> None:
        root = Mock()
        application = CrosswordApplication(root)
        first = Mock()
        second = Mock()
        application._windows = [first, second]

        application.close_window(first)

        first.root.destroy.assert_called_once_with()
        root.destroy.assert_not_called()

        application.close_window(second)

        second.root.destroy.assert_called_once_with()
        root.destroy.assert_called_once_with()

    def test_application_opens_yaml_in_new_document_window(self) -> None:
        application = Mock()
        parent = Mock()
        template = create_blank_template(TemplateSettings(3, 3), "numbered")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sablona.yaml"
            write_crossword_template(template, source)

            result = CrosswordApplication.open_document(
                application,
                source,
                parent=parent,
            )

        loaded = application._open_window.call_args.args[0]
        self.assertEqual(template, loaded)
        application._open_window.assert_called_once_with(
            loaded,
            path=source,
            dirty=False,
        )
        self.assertIs(application._open_window.return_value, result)

    def test_crossword_window_writes_its_document_kind(self) -> None:
        window = Mock()
        crossword = create_crossword_document(
            create_blank_template(TemplateSettings(3, 3), "numbered")
        )
        window._document.return_value = crossword
        window._document_kind = "crossword"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "krizovka.yaml"

            saved = CrosswordDocumentWindow._write_document(
                window,
                output,
                overwrite=False,
            )

            self.assertEqual(crossword, load_crossword_document(output))

        self.assertTrue(saved)
        self.assertEqual(output, window._path)
        window._set_dirty.assert_called_once_with(False)

    def test_window_title_identifies_file_and_unsaved_changes(self) -> None:
        window = Mock()
        window._path = Path("krizovka.yaml")
        window._dirty = True
        window._document_kind = "crossword"

        CrosswordDocumentWindow._update_title(window)

        window.root.title.assert_called_once_with(
            "*krizovka.yaml — Křížovkář"
        )

    def test_closing_dirty_window_can_discard_document_changes(self) -> None:
        window = Mock()
        window._dirty = True
        window._path = Path("sablona.yaml")

        with patch(
            "krizovkar.gui.messagebox.askyesnocancel",
            return_value=False,
        ):
            CrosswordDocumentWindow.request_close(window)

        window.save_document.assert_not_called()
        window.application.close_window.assert_called_once_with(window)

    def test_crossword_pdf_actions_choose_puzzle_and_solution(self) -> None:
        application = Mock()
        grid = Mock()
        application._complete_grid_or_error.return_value = grid
        application.crossword_page_format_value.get.return_value = "A5"

        CrosswordDocumentWindow.save_crossword_pdf(application)
        CrosswordDocumentWindow.save_solution_pdf(application)

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
            CrosswordDocumentWindow.save_blank_template_pdf(application)

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

    def test_current_pdf_action_follows_window_document(self) -> None:
        template_window = Mock()
        template_window._document_kind = "template"
        crossword_window = Mock()
        crossword_window._document_kind = "crossword"

        CrosswordDocumentWindow.save_current_document_pdf(template_window)
        CrosswordDocumentWindow.save_current_document_pdf(crossword_window)

        template_window.save_blank_template_pdf.assert_called_once_with()
        template_window.save_crossword_pdf.assert_not_called()
        crossword_window.save_crossword_pdf.assert_called_once_with()
        crossword_window.save_blank_template_pdf.assert_not_called()

    def test_file_menu_follows_template_document(self) -> None:
        application = Mock()
        application._document_kind = "template"

        CrosswordDocumentWindow._refresh_file_menu(application)

        self.assertEqual(
            [
                call(3, label="Uložit šablonu"),
                call(4, label="Uložit šablonu jako…"),
                call(
                    6,
                    label="Uložit šablonu k tisku (PDF)…",
                    state="normal",
                ),
                call(7, state="disabled"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )

    def test_file_menu_enables_complete_crossword_outputs(self) -> None:
        application = Mock()
        application._document_kind = "crossword"
        application._template = _filled_numbered_crossword()

        CrosswordDocumentWindow._refresh_file_menu(application)

        self.assertEqual(
            [
                call(3, label="Uložit křížovku"),
                call(4, label="Uložit křížovku jako…"),
                call(
                    6,
                    label="Uložit křížovku bez písmen (PDF)…",
                    state="normal",
                ),
                call(7, state="normal"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )

    def test_saves_pdf_through_renderer_without_manual_dialog(self) -> None:
        template = _filled_numbered_crossword()
        grid = create_grid_from_template(template)
        application = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "krizovka.pdf"
            application._choose_output.return_value = (output, False)

            with patch(
                "krizovkar.renderer._run_lualatex",
                side_effect=_fake_lualatex,
            ):
                CrosswordDocumentWindow._save_pdf(
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
            CrosswordDocumentWindow._save_pdf(
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
            exit_code = main([])

        self.assertEqual(2, exit_code)
        self.assertIn("grafické rozhraní nelze spustit", error_output.getvalue())

    def test_main_opens_new_template_document_window(self) -> None:
        root = Mock()
        application = Mock()
        with (
            patch("krizovkar.gui.tk.Tk", return_value=root),
            patch(
                "krizovkar.gui.CrosswordApplication",
                return_value=application,
            ),
        ):
            exit_code = main([])

        self.assertEqual(0, exit_code)
        application.new_template_document.assert_called_once_with()
        application.open_document.assert_not_called()
        root.mainloop.assert_called_once_with()

    def test_main_opens_each_given_yaml_in_its_own_document_window(self) -> None:
        root = Mock()
        application = Mock()
        application.open_document.side_effect = (Mock(), Mock())
        with (
            patch("krizovkar.gui.tk.Tk", return_value=root),
            patch(
                "krizovkar.gui.CrosswordApplication",
                return_value=application,
            ),
        ):
            exit_code = main(["prvni.yaml", "druhy.yml"])

        self.assertEqual(0, exit_code)
        self.assertEqual(
            [
                call(Path("prvni.yaml"), parent=root),
                call(Path("druhy.yml"), parent=root),
            ],
            application.open_document.call_args_list,
        )
        application.new_template_document.assert_not_called()
        root.mainloop.assert_called_once_with()

    def test_main_exits_when_no_given_yaml_can_be_opened(self) -> None:
        root = Mock()
        application = Mock()
        application.open_document.return_value = None
        with (
            patch("krizovkar.gui.tk.Tk", return_value=root),
            patch(
                "krizovkar.gui.CrosswordApplication",
                return_value=application,
            ),
        ):
            exit_code = main(["neplatny.yaml"])

        self.assertEqual(2, exit_code)
        root.destroy.assert_called_once_with()
        root.mainloop.assert_not_called()


if __name__ == "__main__":
    unittest.main()

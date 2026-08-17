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

from krizovkar.generator import (
    create_grid_from_crossword,
)
from krizovkar.gui import (
    CrosswordApplication,
    CrosswordDocumentWindow,
    CrosswordSettings,
    GuiInputError,
    _configure_tk_runtime,
    _crossword_generation_layout,
    _keyboard_shortcut,
    _recent_document_label,
    _recent_documents_storage_path,
    _RecentDocuments,
    clear_crossword_slot,
    create_blank_template,
    crossword_is_complete,
    crossword_slot_pattern,
    fill_crossword_slot,
    main,
    parse_crossword_settings,
    parse_slot_content,
    slot_coordinates,
)
from krizovkar.model import (
    CrosswordDocument,
    CrosswordTemplate,
    LetterCell,
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
    crossword = create_blank_template(CrosswordSettings(3, 3), "numbered")
    entries = {
        "h1": ("ABC", "První řádek"),
        "h2": ("DEF", "Druhý řádek"),
        "h3": ("GHI", "Třetí řádek"),
        "v1": ("ADG", "První sloupec"),
        "v2": ("BEH", "Druhý sloupec"),
        "v3": ("CFI", "Třetí sloupec"),
    }
    for identifier, (answer, clue) in entries.items():
        crossword = fill_crossword_slot(crossword, identifier, answer, clue)
    return crossword


class GuiTest(unittest.TestCase):
    def test_recent_documents_use_macos_application_support(self) -> None:
        with (
            patch("krizovkar.gui.sys.platform", "darwin"),
            patch(
                "krizovkar.gui.Path.home",
                return_value=Path("/Users/test"),
            ),
        ):
            storage_path = _recent_documents_storage_path()

        self.assertEqual(
            Path(
                "/Users/test/Library/Application Support/krizovkar/"
                "recent-documents.json"
            ),
            storage_path,
        )

    def test_recent_documents_are_deduplicated_limited_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "recent-documents.json"
            paths = [
                Path(directory) / f"dokument-{index}.yaml"
                for index in range(12)
            ]
            recent_documents = _RecentDocuments(storage_path)

            for path in paths:
                recent_documents.add(path)

            expected = tuple(reversed(paths[-10:]))
            self.assertEqual(expected, recent_documents.paths)
            self.assertEqual(
                expected,
                _RecentDocuments(storage_path).paths,
            )

            recent_documents.add(paths[5])

            self.assertEqual(paths[5], recent_documents.paths[0])
            self.assertEqual(10, len(recent_documents.paths))

            recent_documents.clear()

            self.assertFalse(storage_path.exists())
            self.assertEqual((), recent_documents.paths)

    def test_recent_documents_ignore_invalid_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "recent-documents.json"
            storage_path.write_text("{neplatný json", encoding="utf-8")

            recent_documents = _RecentDocuments(storage_path)

        self.assertEqual((), recent_documents.paths)

    def test_duplicate_recent_document_names_include_their_directories(self) -> None:
        first = Path("prvni") / "krizovka.yaml"
        second = Path("druha") / "krizovka.yaml"
        unique = Path("treti") / "tajenka.yaml"
        paths = (first, second, unique)

        self.assertEqual(
            f"krizovka.yaml — {first.parent}",
            _recent_document_label(first, paths),
        )
        self.assertEqual(
            "tajenka.yaml",
            _recent_document_label(unique, paths),
        )

    def test_keyboard_shortcuts_follow_operating_system_conventions(self) -> None:
        with patch("krizovkar.gui.sys.platform", "darwin"):
            new_shortcut = _keyboard_shortcut("n")
            save_as_shortcut = _keyboard_shortcut("s", shift=True)

        self.assertEqual("Command-N", new_shortcut.accelerator)
        self.assertEqual("<Command-n>", new_shortcut.sequence)
        self.assertEqual("Command-Shift-S", save_as_shortcut.accelerator)
        self.assertEqual("<Command-Shift-S>", save_as_shortcut.sequence)

        with patch("krizovkar.gui.sys.platform", "linux"):
            new_shortcut = _keyboard_shortcut("n")
            save_as_shortcut = _keyboard_shortcut("s", shift=True)

        self.assertEqual("Ctrl+N", new_shortcut.accelerator)
        self.assertEqual("<Control-n>", new_shortcut.sequence)
        self.assertEqual("Ctrl+Shift+S", save_as_shortcut.accelerator)
        self.assertEqual("<Control-Shift-S>", save_as_shortcut.sequence)

    def test_menu_uses_macos_tk_command_accelerators(self) -> None:
        window = Mock()
        menu = Mock()
        file_menu = Mock()
        recent_documents_menu = Mock()
        export_menu = Mock()

        with (
            patch("krizovkar.gui.sys.platform", "darwin"),
            patch(
                "krizovkar.gui.tk.Menu",
                side_effect=(
                    menu,
                    file_menu,
                    recent_documents_menu,
                    export_menu,
                ),
            ),
        ):
            CrosswordDocumentWindow._build_menu(window)

        self.assertEqual(
            [
                "Command-N",
                "Command-O",
                "Command-S",
                "Command-Shift-S",
                "Command-W",
            ],
            [
                item.kwargs["accelerator"]
                for item in file_menu.add_command.call_args_list
            ],
        )
        self.assertEqual(
            [
                call("<Command-n>", window._new_event),
                call("<Command-o>", window._open_event),
                call("<Command-s>", window._save_event),
                call("<Command-Shift-S>", window._save_as_event),
                call("<Command-w>", window._close_event),
            ],
            window.root.bind.call_args_list,
        )
        file_menu.add_cascade.assert_any_call(
            label="Otevřít poslední",
            menu=recent_documents_menu,
        )

    def test_application_menu_is_available_without_document(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        application.root = Mock()
        application.choose_document = Mock()
        menu = Mock()
        file_menu = Mock()
        recent_documents_menu = Mock()

        with (
            patch("krizovkar.gui.sys.platform", "darwin"),
            patch(
                "krizovkar.gui.tk.Menu",
                side_effect=(menu, file_menu, recent_documents_menu),
            ),
        ):
            application._build_menu()

        commands = file_menu.add_command.call_args_list
        self.assertEqual(
            ["Nová šablona", "Otevřít…"],
            [item.kwargs["label"] for item in commands],
        )
        self.assertEqual(
            ["Command-N", "Command-O"],
            [item.kwargs["accelerator"] for item in commands],
        )
        commands[1].kwargs["command"]()
        application.choose_document.assert_called_once_with(parent=None)
        file_menu.add_cascade.assert_called_once_with(
            label="Otevřít poslední",
            menu=recent_documents_menu,
        )
        menu.add_cascade.assert_called_once_with(
            label="Soubor",
            menu=file_menu,
        )
        application.root.configure.assert_called_once_with(menu=menu)
        self.assertEqual(
            [
                call("<Command-n>", application._new_event),
                call("<Command-o>", application._open_event),
            ],
            application.root.bind.call_args_list,
        )

    def test_application_recent_menu_works_without_document(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        recent_document = Path("krizovka.yaml")
        application._recent_documents = Mock(paths=(recent_document,))
        application.recent_documents_menu = Mock()
        application.open_recent_document = Mock()
        application.clear_recent_documents = Mock()

        with patch("krizovkar.gui.sys.platform", "darwin"):
            application._refresh_recent_documents_menu()

        commands = application.recent_documents_menu.add_command.call_args_list
        self.assertEqual(
            ["krizovka.yaml", "Vymazat nabídku"],
            [item.kwargs["label"] for item in commands],
        )
        commands[0].kwargs["command"]()
        application.open_recent_document.assert_called_once_with(
            recent_document,
            parent=None,
        )
        application.recent_documents_menu.add_separator.assert_called_once_with()

    def test_recent_documents_menu_opens_files_and_can_be_cleared(self) -> None:
        window = Mock()
        first = Path("prvni") / "krizovka.yaml"
        second = Path("druha") / "krizovka.yaml"
        other = Path("treti") / "tajenka.yaml"
        window.application.recent_document_paths = (first, second, other)

        CrosswordDocumentWindow._refresh_recent_documents_menu(window)

        window.recent_documents_menu.delete.assert_called_once_with(0, "end")
        calls = window.recent_documents_menu.add_command.call_args_list
        self.assertEqual(
            [
                f"krizovka.yaml — {first.parent}",
                f"krizovka.yaml — {second.parent}",
                "tajenka.yaml",
                "Vymazat nabídku",
            ],
            [item.kwargs["label"] for item in calls],
        )
        calls[0].kwargs["command"]()
        window.application.open_recent_document.assert_called_once_with(
            first,
            parent=window.root,
        )
        self.assertIs(
            window.application.clear_recent_documents,
            calls[-1].kwargs["command"],
        )
        window.recent_documents_menu.add_separator.assert_called_once_with()

    def test_empty_recent_documents_menu_has_disabled_placeholder(self) -> None:
        window = Mock()
        window.application.recent_document_paths = ()

        CrosswordDocumentWindow._refresh_recent_documents_menu(window)

        window.recent_documents_menu.add_command.assert_called_once_with(
            label="Žádné nedávné dokumenty",
            state="disabled",
        )
        window.recent_documents_menu.add_separator.assert_not_called()

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

    def test_parses_crossword_settings(self) -> None:
        self.assertEqual(
            CrosswordSettings(width=15, height=10),
            parse_crossword_settings(" 15 ", "10"),
        )

    def test_rejects_non_integer_dimension(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "Počet sloupců musí být celé"):
            parse_crossword_settings("patnáct", "10")

    def test_rejects_non_positive_dimension(self) -> None:
        with self.assertRaisesRegex(
            GuiInputError,
            "Počet řádků musí být kladný",
        ):
            parse_crossword_settings("15", "0")

    def test_limits_automatically_generated_crossword_size(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "nejvýše 50"):
            parse_crossword_settings("51", "10")

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
        crossword = create_blank_template(
            CrosswordSettings(width=7, height=6),
            "swedish",
        )

        self.assertIsInstance(crossword, CrosswordTemplate)
        self.assertNotIsInstance(crossword, CrosswordDocument)
        self.assertEqual("template", crossword.kind)
        self.assertTrue(crossword.slots)
        self.assertTrue(all(slot.answer is None for slot in crossword.slots))
        self.assertTrue(
            any(slot.legend_position is not None for slot in crossword.slots)
        )

    def test_creates_numbered_template_before_words(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=7, height=6),
            "numbered",
        )

        self.assertTrue(crossword.slots)
        self.assertTrue(
            all(slot.legend_position is None for slot in crossword.slots)
        )

    def test_reports_too_small_crossword_as_gui_error(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "nelze rozdělit"):
            create_blank_template(
                CrosswordSettings(width=2, height=2),
                "swedish",
            )

    def test_returns_slot_coordinates_in_answer_order(self) -> None:
        crossword = create_blank_template(CrosswordSettings(7, 6), "swedish")
        vertical = next(
            slot for slot in crossword.slots if slot.direction == "vertical"
        )

        coordinates = slot_coordinates(vertical)

        self.assertEqual(vertical.length, len(coordinates))
        self.assertEqual(vertical.start, coordinates[0])
        self.assertEqual(vertical.start.row + 1, coordinates[1].row)
        self.assertEqual(vertical.start.column, coordinates[1].column)

    def test_fills_selected_crossword_slot(self) -> None:
        crossword = create_blank_template(CrosswordSettings(7, 6), "swedish")

        filled = fill_crossword_slot(
            crossword,
            "h1",
            "abcdef",
            "Prvních šest písmen",
        )

        slot = next(slot for slot in filled.slots if slot.identifier == "h1")
        self.assertEqual("ABCDEF", slot.answer)
        self.assertEqual("Prvních šest písmen", slot.clue)
        grid = create_grid_from_crossword(filled)
        assert grid.grid.cells is not None
        first_letter = grid.grid.cells[slot.start.row - 1][slot.start.column - 1]
        self.assertIsInstance(first_letter, LetterCell)
        assert isinstance(first_letter, LetterCell)
        self.assertEqual("A", first_letter.value)

    def test_shows_letters_known_from_crossings(self) -> None:
        crossword = create_blank_template(CrosswordSettings(7, 6), "swedish")
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "ABCDEF",
            "Abeceda",
        )

        self.assertEqual(
            ("A", None, None, None, None),
            crossword_slot_pattern(crossword, "v1"),
        )

    def test_rejects_conflicting_crossing(self) -> None:
        crossword = create_blank_template(CrosswordSettings(7, 6), "swedish")
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "ABCDEF",
            "Abeceda",
        )

        with self.assertRaisesRegex(
            GuiInputError,
            "musí být v 1. poli písmeno 'A', ne 'Z'",
        ):
            fill_crossword_slot(crossword, "v1", "ZABAK", "Obojživelník")

    def test_rejects_duplicate_answer(self) -> None:
        crossword = create_blank_template(CrosswordSettings(7, 6), "swedish")
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "ABCDEF",
            "Abeceda",
        )

        with self.assertRaisesRegex(GuiInputError, "už je použité"):
            fill_crossword_slot(crossword, "h2", "ABCDEF", "Totéž heslo")

    def test_clears_selected_crossword_slot(self) -> None:
        crossword = create_blank_template(CrosswordSettings(7, 6), "swedish")
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "ABCDEF",
            "Abeceda",
        )

        cleared = clear_crossword_slot(crossword, "h1")

        slot = next(slot for slot in cleared.slots if slot.identifier == "h1")
        self.assertIsNone(slot.answer)
        self.assertIsNone(slot.clue)

    def test_recognizes_complete_crossword(self) -> None:
        crossword = _filled_numbered_crossword()

        self.assertTrue(crossword_is_complete(crossword))

        crossword = clear_crossword_slot(crossword, "v3")
        self.assertFalse(crossword_is_complete(crossword))

    def test_saves_partially_filled_crossword_in_project_format(self) -> None:
        crossword = create_blank_template(CrosswordSettings(7, 6), "swedish")
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "ABCDEF",
            "Abeceda",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "krizovka.yaml"

            write_crossword_document(crossword, output)

            self.assertEqual(crossword, load_crossword_document(output))

    def test_selects_generator_for_rebuilding_crossword(self) -> None:
        swedish = create_blank_template(CrosswordSettings(7, 6), "swedish")
        numbered = create_blank_template(CrosswordSettings(7, 6), "numbered")

        self.assertEqual("swedish", _crossword_generation_layout(swedish))
        self.assertEqual("numbered", _crossword_generation_layout(numbered))

    def test_filling_template_creates_crossword_document(self) -> None:
        crossword = create_blank_template(CrosswordSettings(7, 6), "swedish")

        filled = fill_crossword_slot(
            crossword,
            "h1",
            "ABCDEF",
            "Abeceda",
        )

        self.assertIsInstance(filled, CrosswordDocument)
        self.assertEqual("crossword", filled.kind)

    def test_dimension_controls_form_the_crossword_preview_heading(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        parent = Mock()
        window.height_value = Mock()
        window.width_value = Mock()
        window.dimension_error_value = Mock()
        window._preview_cell_clicked = Mock()
        preview_frame = Mock()
        controls = Mock()
        height_spinbox = Mock()
        width_spinbox = Mock()
        preview = Mock()

        with (
            patch(
                "krizovkar.gui.ttk.LabelFrame",
                return_value=preview_frame,
            ) as label_frame_type,
            patch("krizovkar.gui.ttk.Frame", return_value=controls),
            patch("krizovkar.gui.ttk.Label") as label_type,
            patch(
                "krizovkar.gui.ttk.Spinbox",
                side_effect=(height_spinbox, width_spinbox),
            ) as spinbox_type,
            patch(
                "krizovkar.gui.CrosswordPreview",
                return_value=preview,
            ) as preview_type,
        ):
            window._build_crossword_preview(parent)

        label_frame_type.assert_called_once_with(parent, padding=12)
        preview_frame.configure.assert_called_once_with(labelwidget=controls)
        self.assertEqual(
            [
                call(
                    controls,
                    from_=1,
                    to=50,
                    width=5,
                    textvariable=window.height_value,
                ),
                call(
                    controls,
                    from_=1,
                    to=50,
                    width=5,
                    textvariable=window.width_value,
                ),
            ],
            spinbox_type.call_args_list,
        )
        self.assertEqual("Řádky", label_type.call_args_list[0].kwargs["text"])
        self.assertEqual("Sloupce", label_type.call_args_list[1].kwargs["text"])
        preview_type.assert_called_once_with(
            preview_frame,
            width=620,
            height=390,
        )
        self.assertIs(height_spinbox, window.height_spinbox)
        self.assertIs(width_spinbox, window.width_spinbox)
        self.assertIs(preview, window.crossword_preview)
        preview.set_cell_click_handler.assert_called_once_with(
            window._preview_cell_clicked
        )

    def test_crossword_watches_dimensions_for_live_resizing(self) -> None:
        window = Mock()

        CrosswordDocumentWindow._watch_inputs(window)

        for value in (
            window.width_value,
            window.height_value,
        ):
            value.trace_add.assert_called_once_with(
                "write",
                window._dimension_input_changed,
            )

    def test_dimension_change_replaces_pending_resize(self) -> None:
        window = Mock()
        window._changing_dimension_values = False
        window._resize_job = "předchozí"
        window.after.return_value = "nová"

        with patch("krizovkar.gui._CROSSWORD_RESIZE_DELAY_MS", 321):
            CrosswordDocumentWindow._dimension_input_changed(window)

        window.dimension_error_value.set.assert_called_once_with("")
        window.after_cancel.assert_called_once_with("předchozí")
        window.after.assert_called_once_with(
            321,
            window._resize_crossword_from_inputs,
        )
        self.assertEqual("nová", window._resize_job)

    def test_live_resize_changes_only_its_document_window(self) -> None:
        window = Mock()
        window._crossword = create_blank_template(
            CrosswordSettings(4, 4),
            "numbered",
        )
        window._generation_layout = "numbered"
        new_crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window.width_value.get.return_value = "3"
        window.height_value.get.return_value = "3"

        with patch(
            "krizovkar.gui.create_blank_template",
            return_value=new_crossword,
        ) as create_crossword:
            CrosswordDocumentWindow._resize_crossword_from_inputs(window)

        create_crossword.assert_called_once_with(
            CrosswordSettings(3, 3),
            "numbered",
        )
        self.assertIs(new_crossword, window._crossword)
        self.assertEqual("numbered", window._generation_layout)
        self.assertIsNone(window._resize_job)
        window._set_dirty.assert_called_once_with(True)
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()

    def test_live_resize_preserves_matching_document(self) -> None:
        window = Mock()
        crossword = create_blank_template(CrosswordSettings(3, 3), "numbered")
        window._crossword = crossword
        window._generation_layout = "numbered"
        window.width_value.get.return_value = "3"
        window.height_value.get.return_value = "3"

        with patch("krizovkar.gui.create_blank_template") as create_crossword:
            CrosswordDocumentWindow._resize_crossword_from_inputs(window)

        create_crossword.assert_not_called()
        self.assertIs(crossword, window._crossword)
        window._set_dirty.assert_not_called()
        window._refresh_crossword_view.assert_not_called()

    def test_live_resize_keeps_last_preview_for_invalid_value(
        self,
    ) -> None:
        window = Mock()
        crossword = create_blank_template(CrosswordSettings(3, 3), "numbered")
        window._crossword = crossword
        window._generation_layout = "numbered"
        window.width_value.get.return_value = ""
        window.height_value.get.return_value = "3"

        with patch("krizovkar.gui.create_blank_template") as create_crossword:
            CrosswordDocumentWindow._resize_crossword_from_inputs(window)

        create_crossword.assert_not_called()
        self.assertIs(crossword, window._crossword)
        window.dimension_error_value.set.assert_called_once_with(
            "Počet sloupců musí být celé číslo."
        )
        window._show_action_error.assert_not_called()
        window._set_dirty.assert_not_called()
        window._refresh_crossword_view.assert_not_called()

    def test_live_resize_requires_confirmation_for_filled_crossword(self) -> None:
        window = Mock()
        crossword = create_blank_template(CrosswordSettings(3, 3), "numbered")
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "ABC",
            "První řádek",
        )
        window._crossword = crossword
        window._generation_layout = "numbered"
        window.width_value.get.return_value = "4"
        window.height_value.get.return_value = "4"

        with (
            patch(
                "krizovkar.gui.messagebox.askyesno",
                return_value=False,
            ) as ask,
            patch("krizovkar.gui.create_blank_template") as create_crossword,
        ):
            CrosswordDocumentWindow._resize_crossword_from_inputs(window)

        ask.assert_called_once()
        window._restore_dimension_values.assert_called_once_with(crossword)
        create_crossword.assert_not_called()
        self.assertIs(crossword, window._crossword)
        window._set_dirty.assert_not_called()

    def test_application_creates_crossword_as_new_document(self) -> None:
        application = Mock()
        crossword = create_blank_template(CrosswordSettings(3, 3), "numbered")
        expected_window = Mock()
        application._open_window.return_value = expected_window

        with patch(
            "krizovkar.gui.create_blank_template",
            return_value=crossword,
        ) as create_crossword:
            result = CrosswordApplication.new_crossword_document(application)

        create_crossword.assert_called_once_with(
            CrosswordSettings(15, 10),
            "swedish",
        )
        application._open_window.assert_called_once_with(crossword, dirty=True)
        self.assertIs(expected_window, result)

    def test_crossword_progress_does_not_assign_a_global_type(self) -> None:
        window = Mock()
        window._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window._filled_slot_count.return_value = 0

        CrosswordDocumentWindow._refresh_crossword_view(window)

        message = window.progress_value.set.call_args.args[0]
        self.assertTrue(message.startswith("Šablona 3 × 3. "))
        self.assertNotIn("švéd", message)
        self.assertNotIn("číslovan", message)
        window._refresh_crossword_preview.assert_called_once_with()
        window._refresh_file_menu.assert_called_once_with()

    def test_application_owner_stays_hidden_behind_document_windows(self) -> None:
        root = Mock()

        with (
            patch.object(
                CrosswordApplication,
                "_configure_no_document_window",
            ),
            patch.object(CrosswordApplication, "_build_menu"),
        ):
            application = CrosswordApplication(root)

        root.withdraw.assert_called_once_with()
        self.assertEqual([], application._windows)

    def test_application_stays_open_after_last_document_window_closes(self) -> None:
        root = Mock()
        with (
            patch.object(
                CrosswordApplication,
                "_configure_no_document_window",
            ),
            patch.object(CrosswordApplication, "_build_menu"),
        ):
            application = CrosswordApplication(root)
        first = Mock()
        second = Mock()
        application._windows = [first, second]
        application.show_no_document_state = Mock()

        application.close_window(first)

        first.root.destroy.assert_called_once_with()
        root.destroy.assert_not_called()
        application.show_no_document_state.assert_not_called()

        application.close_window(second)

        second.root.destroy.assert_called_once_with()
        root.destroy.assert_not_called()
        application.show_no_document_state.assert_called_once_with()

    def test_application_shows_owner_window_without_document_off_macos(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        application.root = Mock()

        with patch("krizovkar.gui.sys.platform", "linux"):
            application.show_no_document_state()

        application.root.deiconify.assert_called_once_with()
        application.root.lift.assert_called_once_with()

        application.root.reset_mock()
        with patch("krizovkar.gui.sys.platform", "darwin"):
            application.show_no_document_state()

        application.root.deiconify.assert_not_called()
        application.root.lift.assert_not_called()

    def test_application_opens_template_in_new_document_window(self) -> None:
        application = Mock()
        parent = Mock()
        crossword = create_blank_template(CrosswordSettings(3, 3), "numbered")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sablona.yaml"
            write_crossword_template(crossword, source)

            result = CrosswordApplication.open_document(
                application,
                source,
                parent=parent,
            )

        loaded = application._open_window.call_args.args[0]
        self.assertEqual(crossword, loaded)
        application._open_window.assert_called_once_with(
            loaded,
            path=source,
            dirty=False,
        )
        application.remember_recent_document.assert_called_once_with(source)
        self.assertIs(application._open_window.return_value, result)

    def test_missing_recent_document_is_removed(self) -> None:
        application = Mock()
        parent = Mock()
        source = Path("/neexistujici/krizovka.yaml")

        with patch("krizovkar.gui.messagebox.showerror") as show_error:
            result = CrosswordApplication.open_recent_document(
                application,
                source,
                parent=parent,
            )

        self.assertIsNone(result)
        application._recent_documents.remove.assert_called_once_with(source)
        application.open_document.assert_not_called()
        show_error.assert_called_once_with(
            "Dokument nelze otevřít",
            f"Soubor {source} už neexistuje a byl odebrán "
            "z nabídky posledních dokumentů.",
            parent=parent,
        )

    def test_crossword_window_writes_template_document_kind(self) -> None:
        window = Mock()
        crossword = create_blank_template(CrosswordSettings(3, 3), "numbered")
        window._document.return_value = crossword
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sablona.yaml"

            saved = CrosswordDocumentWindow._write_document(
                window,
                output,
                overwrite=False,
            )

            self.assertEqual(crossword, load_crossword_template(output))

        self.assertTrue(saved)
        self.assertEqual(output, window._path)
        window._set_dirty.assert_called_once_with(False)
        window.application.remember_recent_document.assert_called_once_with(output)

    def test_window_title_identifies_file_and_unsaved_changes(self) -> None:
        window = Mock()
        path = Path("krizovka.yaml")
        window._path = path
        window._dirty = True

        with patch("krizovkar.gui.sys.platform", "darwin"):
            CrosswordDocumentWindow._update_title(window)

        window.root.title.assert_called_once_with(
            "*krizovka.yaml — Křížovkář"
        )
        window.root.attributes.assert_called_once_with(
            "-titlepath",
            str(path.absolute()),
        )

    def test_new_macos_document_has_no_proxy_icon(self) -> None:
        window = Mock()
        window._path = None
        window._dirty = True
        window._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )

        with patch("krizovkar.gui.sys.platform", "darwin"):
            CrosswordDocumentWindow._update_title(window)

        window.root.title.assert_called_once_with("*Nová šablona — Křížovkář")
        window.root.attributes.assert_called_once_with("-titlepath", "")

    def test_other_platforms_do_not_set_macos_proxy_icon(self) -> None:
        window = Mock()
        window._path = Path("krizovka.yaml")
        window._dirty = False

        with patch("krizovkar.gui.sys.platform", "linux"):
            CrosswordDocumentWindow._update_title(window)

        window.root.attributes.assert_not_called()

    def test_closing_dirty_window_can_discard_document_changes(self) -> None:
        window = Mock()
        window._dirty = True
        window._path = Path("krizovka.yaml")

        with patch(
            "krizovkar.gui.messagebox.askyesnocancel",
            return_value=False,
        ):
            CrosswordDocumentWindow.request_close(window)

        window.save_document.assert_not_called()
        window.application.close_window.assert_called_once_with(window)

    def test_crossword_pdf_actions_choose_puzzle_and_solution(self) -> None:
        application = Mock()
        application._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        solution = Mock()
        application._complete_grid_or_error.return_value = solution

        with patch("krizovkar.gui.create_grid_from_template") as create_grid:
            CrosswordDocumentWindow.save_crossword_pdf(application)
            CrosswordDocumentWindow.save_solution_pdf(application)

        self.assertEqual(
            [
                call(
                    create_grid.return_value,
                    filled=False,
                    title="Exportovat křížovku bez písmen",
                    initialfile="krizovka.pdf",
                ),
                call(
                    solution,
                    filled=True,
                    title="Exportovat řešení s písmeny",
                    initialfile="reseni.pdf",
                ),
            ],
            application._save_pdf.call_args_list,
        )
        create_grid.assert_called_once_with(application._crossword)

    def test_export_actions_offer_crossword_and_solution(self) -> None:
        crossword_window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        crossword_window.export_menu = Mock()

        CrosswordDocumentWindow._add_export_actions(crossword_window)

        self.assertEqual(
            [
                call(
                    label="Křížovku bez písmen (PDF)…",
                    command=crossword_window.save_crossword_pdf,
                ),
                call(
                    label="Řešení s písmeny (PDF)…",
                    command=crossword_window.save_solution_pdf,
                    state="disabled",
                ),
            ],
            crossword_window.export_menu.add_command.call_args_list,
        )

    def test_toolbar_offers_export_off_macos(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.export_menu = Mock()
        toolbar = Mock()
        export_button = Mock()

        with (
            patch("krizovkar.gui.sys.platform", "linux"),
            patch(
                "krizovkar.gui.ttk.Frame",
                return_value=toolbar,
            ) as frame_type,
            patch(
                "krizovkar.gui.ttk.Menubutton",
                return_value=export_button,
            ) as menubutton_type,
            patch("krizovkar.gui.ttk.Button") as button_type,
        ):
            CrosswordDocumentWindow._build_toolbar(window)

        frame_type.assert_called_once_with(window, padding=(14, 0, 14, 10))
        toolbar.grid.assert_called_once_with(row=0, column=0, sticky="ew")
        button_type.assert_not_called()
        menubutton_type.assert_called_once_with(
            toolbar,
            text="Exportovat",
            menu=window.export_menu,
        )
        export_button.pack.assert_called_once_with(side="left", padx=(0, 6))
        self.assertIs(toolbar, window.toolbar)
        self.assertEqual({"export": export_button}, window._toolbar_controls)

    def test_macos_toolbar_is_attached_to_window_chrome(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.root = Mock()
        native_toolbar = Mock()

        with (
            patch("krizovkar.gui.sys.platform", "darwin"),
            patch(
                "krizovkar.gui._create_macos_toolbar",
                return_value=native_toolbar,
            ) as create_toolbar,
            patch("krizovkar.gui.ttk.Frame") as frame_type,
        ):
            window._build_toolbar()

        root, items = create_toolbar.call_args.args
        self.assertIs(window.root, root)
        self.assertEqual(["export"], [item.identifier for item in items])
        self.assertEqual(["Exportovat"], [item.label for item in items])
        self.assertEqual(
            ["Křížovku bez písmen (PDF)…", "Řešení s písmeny (PDF)…"],
            [action.label for action in items[0].menu_actions],
        )
        self.assertIs(native_toolbar, window.toolbar)
        frame_type.assert_not_called()

    def test_file_menu_enables_complete_crossword_outputs(self) -> None:
        application = Mock()
        application._save_menu_index = 4
        application._save_as_menu_index = 5
        application._crossword = _filled_numbered_crossword()

        CrosswordDocumentWindow._refresh_file_menu(application)

        self.assertEqual(
            [
                call(4, label="Uložit křížovku"),
                call(5, label="Uložit křížovku jako…"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [
                call(0, state="normal"),
                call(1, state="normal"),
            ],
            application.export_menu.entryconfigure.call_args_list,
        )
        application._configure_toolbar_action.assert_called_once_with(
            "export",
            "normal",
        )

    def test_file_menu_disables_incomplete_crossword_outputs(self) -> None:
        application = Mock()
        application._save_menu_index = 4
        application._save_as_menu_index = 5
        application._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )

        CrosswordDocumentWindow._refresh_file_menu(application)

        self.assertEqual(
            [
                call(4, label="Uložit šablonu"),
                call(5, label="Uložit šablonu jako…"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [call(0, state="normal"), call(1, state="disabled")],
            application.export_menu.entryconfigure.call_args_list,
        )
        application._configure_toolbar_action.assert_called_once_with(
            "export",
            "normal",
        )

    def test_page_format_is_chosen_in_export_dialog_and_remembered(self) -> None:
        window = Mock()
        window._page_format = "A4"

        with patch("krizovkar.gui.PdfExportDialog") as dialog_type:
            dialog_type.return_value.result = "A5"
            page_format = CrosswordDocumentWindow._choose_page_format(
                window,
                title="Exportovat křížovku bez písmen",
            )

        self.assertEqual("A5", page_format)
        dialog_type.assert_called_once_with(
            window.root,
            title="Exportovat křížovku bez písmen",
            initial_page_format="A4",
        )
        self.assertEqual("A5", window._page_format)

    def test_cancelled_page_format_dialog_keeps_previous_format(self) -> None:
        window = Mock()
        window._page_format = "A4"

        with patch("krizovkar.gui.PdfExportDialog") as dialog_type:
            dialog_type.return_value.result = None
            page_format = CrosswordDocumentWindow._choose_page_format(
                window,
                title="Exportovat křížovku bez písmen",
            )

        self.assertIsNone(page_format)
        self.assertEqual("A4", window._page_format)

    def test_saves_pdf_with_format_chosen_in_export_dialog(self) -> None:
        crossword = _filled_numbered_crossword()
        grid = create_grid_from_crossword(crossword)
        application = Mock()
        application._choose_page_format.return_value = "A5"
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
                    title="Exportovat křížovku bez písmen",
                    initialfile="krizovka.pdf",
                )

            self.assertEqual(PDF_BYTES, output.read_bytes())

        application._choose_page_format.assert_called_once_with(
            title="Exportovat křížovku bez písmen",
        )
        application._choose_output.assert_called_once_with(
            title="Exportovat křížovku bez písmen",
            initialfile="krizovka.pdf",
            extension=".pdf",
            filetypes=(("PDF soubory", "*.pdf"), ("Všechny soubory", "*")),
            overwrite_title="Přepsat PDF?",
        )
        self.assertEqual(
            [call(cursor="watch"), call(cursor="")],
            application.root.configure.call_args_list,
        )
        application.root.update_idletasks.assert_called_once_with()
        application._show_action_error.assert_not_called()

    def test_cancelled_export_dialog_does_not_choose_output(self) -> None:
        application = Mock()
        application._choose_page_format.return_value = None

        CrosswordDocumentWindow._save_pdf(
            application,
            Mock(),
            filled=False,
            title="Exportovat křížovku bez písmen",
            initialfile="krizovka.pdf",
        )

        application._choose_output.assert_not_called()

    def test_pdf_render_error_is_shown_and_restores_cursor(self) -> None:
        application = Mock()
        application._choose_page_format.return_value = "A4"
        application._choose_output.return_value = (Path("krizovka.pdf"), False)

        with patch(
            "krizovkar.gui.render_pdf",
            side_effect=RenderError("nainstalujte TeX Live"),
        ):
            CrosswordDocumentWindow._save_pdf(
                application,
                Mock(),
                filled=False,
                title="Exportovat křížovku bez písmen",
                initialfile="krizovka.pdf",
            )

        application._show_action_error.assert_called_once_with(
            "PDF nelze vytvořit",
            "nainstalujte TeX Live",
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

    def test_main_opens_system_file_dialog(self) -> None:
        root = Mock()
        application = Mock()
        application.choose_document.return_value = Mock()
        with (
            patch("krizovkar.gui.tk.Tk", return_value=root),
            patch(
                "krizovkar.gui.CrosswordApplication",
                return_value=application,
            ),
        ):
            exit_code = main([])

        self.assertEqual(0, exit_code)
        application.choose_document.assert_called_once_with(parent=None)
        application.show_no_document_state.assert_not_called()
        application.new_crossword_document.assert_not_called()
        application.open_document.assert_not_called()
        root.mainloop.assert_called_once_with()

    def test_main_stays_open_when_system_file_dialog_is_cancelled(self) -> None:
        root = Mock()
        application = Mock()
        application.choose_document.return_value = None
        with (
            patch("krizovkar.gui.tk.Tk", return_value=root),
            patch(
                "krizovkar.gui.CrosswordApplication",
                return_value=application,
            ),
        ):
            exit_code = main([])

        self.assertEqual(0, exit_code)
        application.choose_document.assert_called_once_with(parent=None)
        application.show_no_document_state.assert_called_once_with()
        root.destroy.assert_not_called()
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
        application.choose_document.assert_not_called()
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

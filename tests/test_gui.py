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
    CrosswordPreview,
    CrosswordSettings,
    CrosswordSourceWindow,
    GuiInputError,
    _answer_conflicts_with_crossing,
    _configure_tk_runtime,
    _create_help_menu,
    _create_view_menu,
    _create_window_menu,
    _keyboard_shortcut,
    _ReadOnlyText,
    _recent_document_label,
    _recent_documents_storage_path,
    _RecentDocuments,
    _template_generation_layout,
    clear_crossword_slot,
    create_blank_template,
    crossword_is_complete,
    crossword_slot_pattern,
    fill_crossword_slot,
    main,
    parse_slot_content,
    slot_coordinates,
)
from krizovkar.model import (
    CrosswordDocument,
    LetterCell,
    load_crossword_document,
    write_crossword_document,
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


def _resizable_preview() -> tuple[CrosswordPreview, Mock]:
    preview = CrosswordPreview.__new__(CrosswordPreview)
    preview._crossword = create_grid_from_crossword(
        create_blank_template(CrosswordSettings(7, 6), "numbered")
    )
    preview._grid_geometry = (100.0, 50.0, 20.0)
    resize_handler = Mock()
    preview._grid_resize_handler = resize_handler
    preview._minimum_dimension = 3
    preview._maximum_dimension = 50
    preview._resize_drag = None
    preview._resize_target = None
    preview._draw_resize_feedback = Mock()
    preview._set_resize_cursor = Mock()
    preview._cell_clicked = Mock()
    preview.delete = Mock()
    return preview, resize_handler


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
        view_menu = Mock()
        slot_list_placement_menu = Mock()
        window_menu = Mock()
        help_menu = Mock()
        window._slot_list_placement_variable = "slot_list_placement"
        window._slot_list_placement = "main"
        window._set_slot_list_placement = Mock()

        with (
            patch("krizovkar.gui.sys.platform", "darwin"),
            patch(
                "krizovkar.gui.tk.Menu",
                side_effect=(
                    menu,
                    file_menu,
                    recent_documents_menu,
                    export_menu,
                    view_menu,
                    slot_list_placement_menu,
                    window_menu,
                    help_menu,
                ),
            ) as menu_type,
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
        menu_type.assert_any_call(menu, name="window")
        menu_type.assert_any_call(menu, name="help")
        help_menu.add_command.assert_called_once()
        self.assertEqual(
            "Křížovkář na GitHubu",
            help_menu.add_command.call_args.kwargs["label"],
        )
        source_item = view_menu.add_command.call_args
        self.assertEqual("Zdroj YAML", source_item.kwargs["label"])
        self.assertEqual("normal", source_item.kwargs["state"])
        source_item.kwargs["command"]()
        window.application.show_source_window.assert_called_once_with(window)
        view_menu.add_separator.assert_called_once_with()
        view_menu.add_cascade.assert_called_once_with(
            label="Místa pro hesla",
            menu=slot_list_placement_menu,
        )
        slot_list_placement_menu.setvar.assert_called_once_with(
            "slot_list_placement",
            "main",
        )
        placement_items = slot_list_placement_menu.add_radiobutton.call_args_list
        self.assertEqual(
            ["V hlavním okně", "V samostatném okně"],
            [item.kwargs["label"] for item in placement_items],
        )
        self.assertEqual(
            ["main", "window"],
            [item.kwargs["value"] for item in placement_items],
        )
        self.assertTrue(
            all(
                item.kwargs["variable"] == "slot_list_placement"
                for item in placement_items
            )
        )
        placement_items[1].kwargs["command"]()
        window._set_slot_list_placement.assert_called_once_with("window")
        menu.add_cascade.assert_has_calls(
            [
                call(label="Soubor", menu=file_menu),
                call(label="Zobrazení", menu=view_menu),
                call(label="Okno", menu=window_menu),
                call(label="Nápověda", menu=help_menu),
            ]
        )

    def test_application_menu_is_available_without_document(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        application.root = Mock()
        application.choose_document = Mock()
        menu = Mock()
        file_menu = Mock()
        recent_documents_menu = Mock()
        view_menu = Mock()
        window_menu = Mock()
        help_menu = Mock()

        with (
            patch("krizovkar.gui.sys.platform", "darwin"),
            patch(
                "krizovkar.gui.tk.Menu",
                side_effect=(
                    menu,
                    file_menu,
                    recent_documents_menu,
                    view_menu,
                    window_menu,
                    help_menu,
                ),
            ) as menu_type,
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
        menu_type.assert_any_call(menu, name="window")
        menu_type.assert_any_call(menu, name="help")
        view_menu.add_command.assert_called_once_with(
            label="Zdroj YAML",
            state="disabled",
        )
        menu.add_cascade.assert_has_calls(
            [
                call(label="Soubor", menu=file_menu),
                call(label="Zobrazení", menu=view_menu),
                call(label="Okno", menu=window_menu),
                call(label="Nápověda", menu=help_menu),
            ]
        )
        application.root.configure.assert_called_once_with(menu=menu)
        self.assertEqual(
            [
                call("<Command-n>", application._new_event),
                call("<Command-o>", application._open_event),
            ],
            application.root.bind.call_args_list,
        )

    def test_help_menu_opens_project_repository_on_github(self) -> None:
        parent = Mock()
        help_menu = Mock()

        with (
            patch("krizovkar.gui.tk.Menu", return_value=help_menu),
            patch("krizovkar.gui.webbrowser.open_new_tab") as open_new_tab,
        ):
            created = _create_help_menu(parent)
            command = help_menu.add_command.call_args.kwargs["command"]
            command()

        self.assertIs(help_menu, created)
        open_new_tab.assert_called_once_with(
            "https://github.com/Glutexo/krizovkar"
        )

    def test_source_window_shows_read_only_yaml_for_document(self) -> None:
        source_window = CrosswordSourceWindow.__new__(CrosswordSourceWindow)
        source_window.root = Mock()
        source_window.source_text = Mock()
        document_window = Mock()
        document_window._path = Path("krizovka.yaml")
        document_window._dirty = True
        document_window._document.return_value = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        source_window._document_window = document_window
        source_window.source_text.yview.return_value = ()
        source_window.source_text.xview.return_value = ()

        source_window.show(reveal=True)

        source_window.root.transient.assert_not_called()
        source_window.root.title.assert_called_once_with(
            "Zdroj YAML — *krizovka.yaml"
        )
        yaml_source = source_window.source_text.replace_content.call_args.args[0]
        self.assertIn("format: krizovkar", yaml_source)
        self.assertIn("kind: crossword", yaml_source)
        source_window.root.deiconify.assert_called_once_with()
        source_window.root.lift.assert_called_once_with()
        source_window.source_text.focus_set.assert_called_once_with()

    def test_read_only_text_forwards_selection_and_scrolling_commands(
        self,
    ) -> None:
        text = _ReadOnlyText.__new__(_ReadOnlyText)
        text.tk = Mock()
        text._original_widget_command = "původní-widget"
        text.tk.call.return_value = "výsledek"

        scroll_result = text._dispatch_widget_command(
            "yview",
            "scroll",
            1,
            "units",
        )
        selection_result = text._dispatch_widget_command(
            "tag",
            "add",
            "sel",
            "1.0",
            "1.4",
        )

        self.assertEqual("výsledek", scroll_result)
        self.assertEqual("výsledek", selection_result)
        self.assertEqual(
            [
                call("původní-widget", "yview", "scroll", 1, "units"),
                call(
                    "původní-widget",
                    "tag",
                    "add",
                    "sel",
                    "1.0",
                    "1.4",
                ),
            ],
            text.tk.call.call_args_list,
        )

    def test_read_only_text_blocks_user_content_changes(self) -> None:
        text = _ReadOnlyText.__new__(_ReadOnlyText)
        text.tk = Mock()
        text._original_widget_command = "původní-widget"

        for command in ("insert", "delete", "replace"):
            with self.subTest(command=command):
                self.assertEqual(
                    "",
                    text._dispatch_widget_command(command, "1.0", "text"),
                )

        text.tk.call.assert_not_called()

    def test_read_only_text_replaces_content_through_internal_command(
        self,
    ) -> None:
        text = _ReadOnlyText.__new__(_ReadOnlyText)
        text.tk = Mock()
        text._original_widget_command = "původní-widget"

        text.replace_content("format: krizovkar\n")

        self.assertEqual(
            [
                call("původní-widget", "delete", "1.0", tk.END),
                call(
                    "původní-widget",
                    "insert",
                    "1.0",
                    "format: krizovkar\n",
                ),
            ],
            text.tk.call.call_args_list,
        )

    def test_other_platforms_refresh_window_menu_before_opening(self) -> None:
        parent = Mock()
        refresh = Mock()
        window_menu = Mock()

        with (
            patch("krizovkar.gui.sys.platform", "linux"),
            patch(
                "krizovkar.gui.tk.Menu",
                return_value=window_menu,
            ) as menu_type,
        ):
            created = _create_window_menu(parent, refresh)

        menu_type.assert_called_once_with(
            parent,
            name="window",
            postcommand=refresh,
        )
        self.assertIs(window_menu, created)

    def test_view_menu_contains_source_action(self) -> None:
        parent = Mock()
        menu = Mock()
        command = Mock()

        with patch("krizovkar.gui.tk.Menu", return_value=menu) as menu_type:
            created = _create_view_menu(parent, command)

        menu_type.assert_called_once_with(parent)
        menu.add_command.assert_called_once_with(
            label="Zdroj YAML",
            state="normal",
            command=command,
        )
        self.assertIs(menu, created)

    def test_window_menu_lists_open_windows_and_marks_current(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        first = Mock()
        first._path = None
        first._dirty = True
        second = Mock()
        second._path = Path("krizovka.yaml")
        second._dirty = False
        application._windows = [first, second]
        application._active_window = first
        application.activate_window = Mock()
        window_menu = Mock()

        application._populate_window_menu(window_menu, current=second)

        window_menu.delete.assert_called_once_with(0, "end")
        window_menu.setvar.assert_called_once_with(
            "krizovkar_active_window",
            str(id(second)),
        )
        items = window_menu.add_radiobutton.call_args_list
        self.assertEqual(
            ["*Nová šablona", "krizovka.yaml"],
            [item.kwargs["label"] for item in items],
        )
        self.assertEqual(
            [str(id(first)), str(id(second))],
            [item.kwargs["value"] for item in items],
        )
        self.assertTrue(
            all(
                item.kwargs["variable"] == "krizovkar_active_window"
                for item in items
            )
        )

        window_menu.add_command.assert_not_called()

        items[0].kwargs["command"]()

        application.activate_window.assert_called_once_with(first)

    def test_empty_window_menu_has_disabled_message(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        application._windows = []
        application._active_window = None
        window_menu = Mock()

        application._populate_window_menu(window_menu, current=None)

        window_menu.add_command.assert_called_once_with(
            label="Žádná otevřená okna",
            state="disabled",
        )
        window_menu.add_radiobutton.assert_not_called()

    def test_window_menu_restores_and_activates_selected_window(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        window = Mock()
        application._windows = [window]
        application.document_window_activated = Mock()

        application.activate_window(window)

        application.document_window_activated.assert_called_once_with(window)
        window.root.deiconify.assert_called_once_with()
        window.root.lift.assert_called_once_with()
        window.root.focus_force.assert_called_once_with()

    def test_document_window_menu_marks_its_owner_current(self) -> None:
        window = Mock()

        CrosswordDocumentWindow._refresh_window_menu(window)

        window.application._populate_window_menu.assert_called_once_with(
            window.window_menu,
            current=window,
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

        self.assertIsInstance(crossword, CrosswordDocument)
        self.assertEqual("crossword", crossword.kind)
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

    def test_live_crossing_check_waits_for_complete_ch_cell(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "CHAB",
            "Začíná českým CH",
        )

        self.assertFalse(
            _answer_conflicts_with_crossing(crossword, "v1", "C")
        )
        self.assertFalse(
            _answer_conflicts_with_crossing(crossword, "v1", "CH")
        )
        self.assertTrue(
            _answer_conflicts_with_crossing(crossword, "v1", "CA")
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

    def test_selects_layout_for_regenerating_template(self) -> None:
        swedish = create_blank_template(CrosswordSettings(7, 6), "swedish")
        numbered = create_blank_template(CrosswordSettings(7, 6), "numbered")

        self.assertEqual("swedish", _template_generation_layout(swedish))
        self.assertEqual("numbered", _template_generation_layout(numbered))

    def test_filling_template_keeps_the_same_crossword_document_kind(self) -> None:
        crossword = create_blank_template(CrosswordSettings(7, 6), "swedish")

        filled = fill_crossword_slot(
            crossword,
            "h1",
            "ABCDEF",
            "Abeceda",
        )

        self.assertIsInstance(filled, CrosswordDocument)
        self.assertEqual("crossword", filled.kind)

    def test_document_window_uses_compact_outer_padding(self) -> None:
        root = Mock()
        application = Mock()
        document = create_blank_template(
            CrosswordSettings(7, 6),
            "swedish",
        )

        with (
            patch(
                "krizovkar.gui.ttk.Frame.__init__",
                return_value=None,
            ) as frame_init,
            patch.object(CrosswordDocumentWindow, "_configure_window"),
            patch.object(CrosswordDocumentWindow, "_build_menu"),
            patch.object(CrosswordDocumentWindow, "_build_content"),
            patch.object(CrosswordDocumentWindow, "_rebuild_slot_tree"),
            patch.object(CrosswordDocumentWindow, "_refresh_crossword_view"),
            patch.object(CrosswordDocumentWindow, "_update_title"),
        ):
            window = CrosswordDocumentWindow(
                root,
                application=application,
                document=document,
                path=None,
                dirty=True,
            )

        frame_init.assert_called_once_with(root, padding=(12, 10))
        self.assertEqual("main", window._slot_list_placement)
        self.assertIsNone(window._slot_list_window)
        self.assertTrue(
            window._slot_list_placement_variable.startswith(
                "krizovkar_slot_list_placement_"
            )
        )

    def test_document_window_opens_at_minimum_width(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.root = Mock()
        window.grid = Mock()
        window.columnconfigure = Mock()
        window.rowconfigure = Mock()
        window.request_close = Mock()

        window._configure_window()

        window.root.geometry.assert_called_once_with("600x850")
        window.root.minsize.assert_called_once_with(600, 700)
        window.rowconfigure.assert_called_once_with(0, weight=1)
        window.root.bind.assert_called_once_with(
            "<FocusIn>",
            window._document_focus_in,
            add="+",
        )

    def test_crossword_preview_has_no_manual_dimension_controls(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        parent = Mock()
        window._preview_cell_clicked = Mock()
        window._template_layout = "swedish"
        window._crossword = create_blank_template(
            CrosswordSettings(7, 6),
            "swedish",
        )
        preview_frame = Mock()
        preview = Mock()

        with (
            patch(
                "krizovkar.gui.ttk.LabelFrame",
                return_value=preview_frame,
            ) as label_frame_type,
            patch("krizovkar.gui.ttk.Spinbox") as spinbox_type,
            patch(
                "krizovkar.gui.CrosswordPreview",
                return_value=preview,
            ) as preview_type,
        ):
            window._build_crossword_preview(parent)

        label_frame_type.assert_called_once_with(
            parent,
            text="Náhled křížovky (7 × 6)",
            padding=12,
        )
        self.assertIs(preview_frame, window.crossword_preview_frame)
        preview_type.assert_called_once_with(
            preview_frame,
            width=620,
            height=390,
        )
        self.assertIs(preview, window.crossword_preview)
        preview.set_cell_click_handler.assert_called_once_with(
            window._preview_cell_clicked
        )
        preview.set_grid_resize_handler.assert_called_once_with(
            window._preview_grid_resized,
            minimum_dimension=4,
            maximum_dimension=50,
        )
        spinbox_type.assert_not_called()

    def test_crossword_preview_heading_refreshes_current_dimensions(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._crossword = create_blank_template(
            CrosswordSettings(9, 8),
            "numbered",
        )
        window.crossword_preview_frame = Mock()
        window._refresh_crossword_preview = Mock()
        window._refresh_file_menu = Mock()

        window._refresh_crossword_view()

        window.crossword_preview_frame.configure.assert_called_once_with(
            text="Náhled křížovky (9 × 8)"
        )
        window._refresh_crossword_preview.assert_called_once_with()
        window._refresh_file_menu.assert_called_once_with()

    def test_slot_table_shows_crossing_pattern_as_gray_shadow(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        crossword = create_blank_template(
            CrosswordSettings(12, 9),
            "swedish",
        )
        window._crossword = fill_crossword_slot(
            crossword,
            "h1",
            "VAGÍNA",
            "Pohlavní orgán",
        )
        window._selected_slot_identifier = "v1"
        window._cancel_inline_slot_edit = Mock()
        window._slot_selection_changed = Mock()
        window.slots_tree = Mock()
        window.slots_tree._w = ".slots"
        window.slots_tree.get_children.return_value = ()

        window._rebuild_slot_tree()

        rows = {
            item.kwargs["iid"]: item.kwargs["values"]
            for item in window.slots_tree.insert.call_args_list
        }
        self.assertEqual("VAGÍNA", rows["h1"][2])
        self.assertEqual("—", rows["h2"][2])
        self.assertEqual("V•••", rows["v1"][2])
        window.slots_tree.tag_configure.assert_called_once_with(
            "shadow-answer",
            foreground="gray50",
        )
        window.slots_tree.tk.call.assert_any_call(
            ".slots",
            "tag",
            "cell",
            "add",
            "shadow-answer",
            (("v1", "answer"),),
        )

    def test_separate_slot_table_has_no_heading_and_fits_editors(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        parent = Mock()
        slots_frame = Mock()
        container = Mock()
        slots_tree = Mock()
        scrollbar = Mock()
        slot_style = Mock()

        with (
            patch(
                "krizovkar.gui.ttk.Frame",
                side_effect=(slots_frame, container),
            ) as frame_type,
            patch("krizovkar.gui.ttk.LabelFrame") as label_frame_type,
            patch(
                "krizovkar.gui.ttk.Treeview",
                return_value=slots_tree,
            ) as treeview_type,
            patch(
                "krizovkar.gui.ttk.Scrollbar",
                return_value=scrollbar,
            ),
            patch(
                "krizovkar.gui.ttk.Style",
                return_value=slot_style,
            ),
        ):
            window._build_slot_list(parent, standalone=True)

        label_frame_type.assert_not_called()
        self.assertEqual(
            call(parent, padding=12),
            frame_type.call_args_list[0],
        )
        slots_frame.grid.assert_called_once_with(
            row=0,
            column=0,
            sticky="nsew",
            pady=0,
        )
        slot_style.configure.assert_called_once_with(
            "KrizovkarSlots.Treeview",
            rowheight=30,
        )
        slot_style.map.assert_called_once_with(
            "KrizovkarSlot.TEntry",
            foreground=[("invalid", "#c62828")],
        )
        self.assertEqual(
            "KrizovkarSlots.Treeview",
            treeview_type.call_args.kwargs["style"],
        )

    def test_slot_table_moves_to_separate_window_and_back(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.root = Mock()
        window._path = Path("krizovka.yaml")
        window._dirty = False
        window._slot_list_placement = "main"
        window._slot_list_window = None
        window._slot_list_placement_variable = "slot_list_placement"
        window.slot_list_placement_menu = Mock()
        window._save_inline_slot_edit = Mock(return_value=True)
        window.slots_frame = Mock()
        window.crossword_workspace = Mock()
        window._selected_slot_identifier = "v1"
        window._build_slot_list = Mock()
        window._rebuild_slot_tree = Mock()
        slot_list_window = Mock()

        with patch(
            "krizovkar.gui.tk.Toplevel",
            return_value=slot_list_window,
        ) as toplevel:
            window._set_slot_list_placement("window")

        window.slots_frame.destroy.assert_called_once_with()
        toplevel.assert_called_once_with(window.root)
        slot_list_window.title.assert_called_once_with(
            "Místa pro hesla — krizovka.yaml"
        )
        slot_list_window.geometry.assert_called_once_with("780x340")
        slot_list_window.minsize.assert_called_once_with(520, 220)
        slot_list_window.columnconfigure.assert_called_once_with(0, weight=1)
        slot_list_window.rowconfigure.assert_called_once_with(0, weight=1)
        window._build_slot_list.assert_called_once_with(
            slot_list_window,
            standalone=True,
        )
        slot_list_window.lift.assert_called_once_with()
        slot_list_window.focus_force.assert_called_once_with()
        self.assertEqual("window", window._slot_list_placement)
        self.assertIs(slot_list_window, window._slot_list_window)
        self.assertEqual("v1", window._selected_slot_identifier)
        window.slot_list_placement_menu.setvar.assert_called_once_with(
            "slot_list_placement",
            "window",
        )
        window._rebuild_slot_tree.assert_called_once_with()

        detached_slots_frame = Mock()
        window.slots_frame = detached_slots_frame
        window._build_slot_list.reset_mock()
        window._rebuild_slot_tree.reset_mock()
        close_command = slot_list_window.protocol.call_args.args[1]
        close_command()

        detached_slots_frame.destroy.assert_called_once_with()
        slot_list_window.destroy.assert_called_once_with()
        window._build_slot_list.assert_called_once_with(
            window.crossword_workspace
        )
        self.assertEqual("main", window._slot_list_placement)
        self.assertIsNone(window._slot_list_window)
        self.assertEqual("v1", window._selected_slot_identifier)
        window.slot_list_placement_menu.setvar.assert_called_with(
            "slot_list_placement",
            "main",
        )
        window._rebuild_slot_tree.assert_called_once_with()
        self.assertEqual(2, window._save_inline_slot_edit.call_count)

    def test_invalid_inline_edit_prevents_moving_slot_table(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._slot_list_placement = "main"
        window._slot_list_window = None
        window._slot_list_placement_variable = "slot_list_placement"
        window.slot_list_placement_menu = Mock()
        window._save_inline_slot_edit = Mock(return_value=False)
        window.slots_frame = Mock()
        window._build_slot_list = Mock()
        window._rebuild_slot_tree = Mock()

        with patch("krizovkar.gui.tk.Toplevel") as toplevel:
            window._set_slot_list_placement("window")

        window.slots_frame.destroy.assert_not_called()
        toplevel.assert_not_called()
        window._build_slot_list.assert_not_called()
        window._rebuild_slot_tree.assert_not_called()
        window.slot_list_placement_menu.setvar.assert_called_once_with(
            "slot_list_placement",
            "main",
        )

    def test_crossword_preview_detects_every_edge_and_corner(self) -> None:
        preview, _resize_handler = _resizable_preview()
        positions = {
            (100, 110): (-1, 0),
            (240, 110): (1, 0),
            (170, 50): (0, -1),
            (170, 170): (0, 1),
            (100, 50): (-1, -1),
            (240, 50): (1, -1),
            (100, 170): (-1, 1),
            (240, 170): (1, 1),
            (170, 110): (0, 0),
        }

        for position, expected in positions.items():
            with self.subTest(position=position):
                self.assertEqual(expected, preview._resize_edges_at(*position))

    def test_crossword_preview_resizes_from_opposite_edges_and_corner(
        self,
    ) -> None:
        cases = (
            ("levý", (100, 110), (60, 110), (9, 6)),
            ("pravý", (240, 110), (200, 110), (5, 6)),
            ("horní", (170, 50), (170, 10), (7, 8)),
            ("dolní", (170, 170), (170, 130), (7, 4)),
            ("roh", (100, 50), (120, 70), (6, 5)),
        )

        for label, start, end, expected in cases:
            with self.subTest(edge=label):
                preview, resize_handler = _resizable_preview()

                pressed = preview._pointer_pressed(
                    Mock(x=start[0], y=start[1])
                )
                released = preview._resize_released(Mock(x=end[0], y=end[1]))

                self.assertEqual("break", pressed)
                self.assertEqual("break", released)
                resize_handler.assert_called_once_with(*expected)
                self.assertIsNone(preview._resize_drag)
                self.assertIsNone(preview._resize_target)

    def test_crossword_preview_limits_dragged_dimensions(self) -> None:
        preview, resize_handler = _resizable_preview()
        preview._maximum_dimension = 8

        preview._pointer_pressed(Mock(x=240, y=170))
        preview._resize_released(Mock(x=1_000, y=1_000))

        resize_handler.assert_called_once_with(8, 8)

        preview, resize_handler = _resizable_preview()
        preview._pointer_pressed(Mock(x=100, y=50))
        preview._resize_released(Mock(x=1_000, y=1_000))

        resize_handler.assert_called_once_with(3, 3)

    def test_crossword_preview_keeps_untouched_axis_below_minimum(self) -> None:
        preview, resize_handler = _resizable_preview()
        preview._minimum_dimension = 8

        preview._pointer_pressed(Mock(x=240, y=110))
        preview._resize_released(Mock(x=240, y=110))

        resize_handler.assert_not_called()

        preview._pointer_pressed(Mock(x=240, y=110))
        preview._resize_released(Mock(x=260, y=110))

        resize_handler.assert_called_once_with(8, 6)

    def test_crossword_preview_applies_resize_only_after_release(self) -> None:
        preview, resize_handler = _resizable_preview()

        preview._pointer_pressed(Mock(x=240, y=110))
        preview._resize_dragged(Mock(x=260, y=110))

        resize_handler.assert_not_called()
        self.assertEqual((8, 6), preview._resize_target)

        preview._resize_released(Mock(x=260, y=110))

        resize_handler.assert_called_once_with(8, 6)

    def test_crossword_preview_keeps_cell_clicks_away_from_border(self) -> None:
        preview, resize_handler = _resizable_preview()
        event = Mock(x=170, y=110)

        result = preview._pointer_pressed(event)

        self.assertIsNone(result)
        preview._cell_clicked.assert_called_once_with(event)
        resize_handler.assert_not_called()
        self.assertIsNone(preview._resize_drag)

    def test_crossword_document_uses_full_width_workspace(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.crossword_tab = Mock()
        window._build_crossword_preview = Mock()
        window._build_slot_list = Mock()
        workspace = Mock()

        with patch(
            "krizovkar.gui.ttk.Frame",
            return_value=workspace,
        ) as frame_type:
            window._build_crossword_document()

        frame_type.assert_called_once_with(window.crossword_tab)
        window.crossword_tab.columnconfigure.assert_called_once_with(
            0,
            weight=1,
        )
        workspace.grid.assert_called_once_with(
            row=0,
            column=0,
            sticky="nsew",
        )
        self.assertIs(workspace, window.crossword_workspace)
        window._build_crossword_preview.assert_called_once_with(workspace)
        window._build_slot_list.assert_called_once_with(workspace)

    def test_document_content_does_not_add_another_outer_margin(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._build_crossword_document = Mock()
        document_frame = Mock()

        with patch(
            "krizovkar.gui.ttk.Frame",
            return_value=document_frame,
        ) as frame_type:
            window._build_content()

        frame_type.assert_called_once_with(window)
        document_frame.grid.assert_called_once_with(
            row=0,
            column=0,
            sticky="nsew",
        )
        self.assertIs(document_frame, window.crossword_tab)
        window._build_crossword_document.assert_called_once_with()

    def test_inline_slot_edit_opens_answer_and_clue_cells(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window._selected_slot_identifier = None
        window._slot_edit_identifier = None
        window._slot_answer_editor = None
        window._slot_clue_editor = None
        window.slots_tree = Mock()
        window.slots_tree.bbox.side_effect = (
            (175, 24, 180, 22),
            (355, 24, 360, 22),
        )
        answer_editor = Mock()
        clue_editor = Mock()
        window._create_slot_cell_editor = Mock(
            side_effect=(answer_editor, clue_editor)
        )
        window._refresh_crossword_preview = Mock()

        opened = window._open_inline_slot_edit("h1", "#4")

        self.assertTrue(opened)
        self.assertEqual("h1", window._slot_edit_identifier)
        self.assertIs(answer_editor, window._slot_answer_editor)
        self.assertIs(clue_editor, window._slot_clue_editor)
        window._create_slot_cell_editor.assert_has_calls(
            [
                call(
                    (175, 24, 180, 22),
                    "",
                    check_crossings=True,
                ),
                call((355, 24, 360, 22), ""),
            ]
        )
        clue_editor.focus_set.assert_called_once_with()
        clue_editor.selection_range.assert_called_once_with(0, tk.END)

    def test_slot_answer_editor_checks_crossings_while_typing(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.slots_tree = Mock()
        window.after_idle = Mock()
        editor = Mock()

        with patch(
            "krizovkar.gui.ttk.Entry",
            return_value=editor,
        ) as entry_type:
            created = window._create_slot_cell_editor(
                (10, 20, 180, 30),
                "KOZY",
                check_crossings=True,
            )

        self.assertIs(editor, created)
        entry_type.assert_called_once_with(
            window.slots_tree,
            style="KrizovkarSlot.TEntry",
        )
        for event in ("<KeyPress>", "<<Paste>>", "<<Cut>>"):
            editor.bind.assert_any_call(event, window._slot_answer_changed)

        window._slot_answer_changed()

        window.after_idle.assert_called_once_with(
            window._update_slot_answer_error
        )

    def test_inline_slot_edit_saves_both_values(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        original = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window._crossword = original
        window._slot_edit_identifier = "h1"
        window._slot_answer_editor = Mock()
        window._slot_clue_editor = Mock()
        window._slot_answer_editor.get.return_value = "abc"
        window._slot_clue_editor.get.return_value = "První řádek"
        window._set_dirty = Mock()
        window._rebuild_slot_tree = Mock()
        window._refresh_crossword_view = Mock()
        window._show_action_error = Mock()

        saved = window._save_inline_slot_edit()

        self.assertTrue(saved)
        slot = next(
            slot for slot in window._crossword.slots if slot.identifier == "h1"
        )
        self.assertEqual("ABC", slot.answer)
        self.assertEqual("První řádek", slot.clue)
        window._set_dirty.assert_called_once_with(True)
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()
        window._show_action_error.assert_not_called()
        self.assertIsNone(window._slot_edit_identifier)

    def test_partial_inline_answer_changes_color_while_typing(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "ABC",
            "První řádek",
        )
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._crossword = crossword
        window._slot_edit_identifier = "v1"
        answer_editor = Mock()
        answer_editor.get.side_effect = ("Z", "A")
        window._slot_answer_editor = answer_editor

        window._update_slot_answer_error()
        window._update_slot_answer_error()

        answer_editor.state.assert_has_calls(
            [call(("invalid",)), call(("!invalid",))]
        )

    def test_conflicting_inline_slot_edit_marks_answer_red(self) -> None:
        original = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        original = fill_crossword_slot(
            original,
            "h1",
            "ABC",
            "První řádek",
        )
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._crossword = original
        window._slot_edit_identifier = "v1"
        answer_editor = Mock()
        clue_editor = Mock()
        answer_editor.get.return_value = "ZDE"
        clue_editor.get.return_value = "Na tomto místě"
        window._slot_answer_editor = answer_editor
        window._slot_clue_editor = clue_editor
        window._set_dirty = Mock()
        window._rebuild_slot_tree = Mock()
        window._refresh_crossword_view = Mock()
        window._show_action_error = Mock()

        saved = window._save_inline_slot_edit()

        self.assertFalse(saved)
        self.assertIs(original, window._crossword)
        answer_editor.state.assert_has_calls(
            [call(("!invalid",)), call(("invalid",))]
        )
        window._show_action_error.assert_called_once_with(
            "Heslo nelze uložit",
            "Na křížení s heslem 'ABC' musí být v 1. poli "
            "písmeno 'A', ne 'Z'.",
        )
        answer_editor.focus_set.assert_called_once_with()
        window._set_dirty.assert_not_called()

    def test_invalid_inline_slot_edit_stays_open(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        original = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window._crossword = original
        window._slot_edit_identifier = "h1"
        answer_editor = Mock()
        clue_editor = Mock()
        answer_editor.get.return_value = "AB"
        clue_editor.get.return_value = "Příliš krátké heslo"
        window._slot_answer_editor = answer_editor
        window._slot_clue_editor = clue_editor
        window._set_dirty = Mock()
        window._rebuild_slot_tree = Mock()
        window._refresh_crossword_view = Mock()
        window._show_action_error = Mock()

        saved = window._save_inline_slot_edit()

        self.assertFalse(saved)
        self.assertIs(original, window._crossword)
        self.assertEqual("h1", window._slot_edit_identifier)
        window._show_action_error.assert_called_once()
        answer_editor.state.assert_called_once_with(("!invalid",))
        answer_editor.focus_set.assert_called_once_with()
        answer_editor.destroy.assert_not_called()
        clue_editor.destroy.assert_not_called()
        window._set_dirty.assert_not_called()

    def test_empty_inline_slot_edit_clears_answer_and_clue(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        original = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window._crossword = fill_crossword_slot(
            original,
            "h1",
            "ABC",
            "První řádek",
        )
        window._slot_edit_identifier = "h1"
        window._slot_answer_editor = Mock()
        window._slot_clue_editor = Mock()
        window._slot_answer_editor.get.return_value = ""
        window._slot_clue_editor.get.return_value = ""
        window._set_dirty = Mock()
        window._rebuild_slot_tree = Mock()
        window._refresh_crossword_view = Mock()
        window._show_action_error = Mock()

        saved = window._save_inline_slot_edit()

        self.assertTrue(saved)
        slot = next(
            slot for slot in window._crossword.slots if slot.identifier == "h1"
        )
        self.assertIsNone(slot.answer)
        self.assertIsNone(slot.clue)
        window._set_dirty.assert_called_once_with(True)

    def test_preview_resize_stops_when_inline_edit_is_invalid(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = False

        CrosswordDocumentWindow._preview_grid_resized(window, 9, 8)

        window._save_inline_slot_edit.assert_called_once_with()
        window._set_dirty.assert_not_called()
        window._refresh_crossword_view.assert_not_called()

    def test_preview_resize_changes_only_its_document_window(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        window._crossword = create_blank_template(
            CrosswordSettings(4, 4),
            "numbered",
        )
        window._template_layout = "numbered"
        new_template = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )

        with patch(
            "krizovkar.gui.create_blank_template",
            return_value=new_template,
        ) as create_template:
            CrosswordDocumentWindow._preview_grid_resized(window, 3, 3)

        window._save_inline_slot_edit.assert_called_once_with()
        create_template.assert_called_once_with(
            CrosswordSettings(3, 3),
            "numbered",
        )
        self.assertIs(new_template, window._crossword)
        self.assertEqual("numbered", window._template_layout)
        window._set_dirty.assert_called_once_with(True)
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()

    def test_preview_resize_preserves_matching_document(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        template = create_blank_template(CrosswordSettings(3, 3), "numbered")
        window._crossword = template
        window._template_layout = "numbered"

        with patch("krizovkar.gui.create_blank_template") as create_template:
            CrosswordDocumentWindow._preview_grid_resized(window, 3, 3)

        create_template.assert_not_called()
        self.assertIs(template, window._crossword)
        window._set_dirty.assert_not_called()
        window._refresh_crossword_view.assert_not_called()

    def test_preview_resize_silently_rejects_unsupported_layout(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        template = create_blank_template(CrosswordSettings(3, 3), "numbered")
        window._crossword = template
        window._template_layout = "numbered"

        with patch(
            "krizovkar.gui.create_blank_template",
            side_effect=GuiInputError("rozměr nelze rozdělit"),
        ):
            CrosswordDocumentWindow._preview_grid_resized(window, 4, 4)

        self.assertIs(template, window._crossword)
        window._show_action_error.assert_not_called()
        window._set_dirty.assert_not_called()
        window._refresh_crossword_view.assert_not_called()

    def test_preview_resize_requires_confirmation_for_filled_crossword(
        self,
    ) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        crossword = create_blank_template(CrosswordSettings(3, 3), "numbered")
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "ABC",
            "První řádek",
        )
        window._crossword = crossword
        window._template_layout = "numbered"

        with (
            patch(
                "krizovkar.gui.messagebox.askyesno",
                return_value=False,
            ) as ask,
            patch("krizovkar.gui.create_blank_template") as create_template,
        ):
            CrosswordDocumentWindow._preview_grid_resized(window, 4, 4)

        ask.assert_called_once()
        create_template.assert_not_called()
        self.assertIs(crossword, window._crossword)
        window._set_dirty.assert_not_called()

    def test_application_creates_template_as_new_document(self) -> None:
        application = Mock()
        template = create_blank_template(CrosswordSettings(3, 3), "numbered")
        expected_window = Mock()
        application._open_window.return_value = expected_window

        with patch(
            "krizovkar.gui.create_blank_template",
            return_value=template,
        ) as create_template:
            result = CrosswordApplication.new_template_document(application)

        create_template.assert_called_once_with(
            CrosswordSettings(15, 10),
            "swedish",
        )
        application._open_window.assert_called_once_with(template, dirty=True)
        self.assertIs(expected_window, result)

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
        self.assertIsNone(application._active_window)
        self.assertEqual({}, application._source_windows)

    def test_application_creates_source_window_for_each_document(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        application.root = Mock()
        first = Mock()
        second = Mock()
        application._windows = [first, second]
        application._active_window = first
        application._source_windows = {}
        first_source_root = Mock()
        second_source_root = Mock()
        first_source_window = Mock()
        second_source_window = Mock()
        first_source_window.root = first_source_root
        second_source_window.root = second_source_root

        with (
            patch(
                "krizovkar.gui.tk.Toplevel",
                side_effect=(first_source_root, second_source_root),
            ) as toplevel,
            patch(
                "krizovkar.gui.CrosswordSourceWindow",
                side_effect=(first_source_window, second_source_window),
            ) as source_type,
        ):
            first_result = application.show_source_window(first)
            repeated_result = application.show_source_window(first)
            second_result = application.show_source_window(second)

        self.assertEqual(
            [call(application.root), call(application.root)],
            toplevel.call_args_list,
        )
        self.assertEqual(
            [
                call(first_source_root, first),
                call(second_source_root, second),
            ],
            source_type.call_args_list,
        )
        self.assertIs(first_source_window, first_result)
        self.assertIs(first_source_window, repeated_result)
        self.assertIs(second_source_window, second_result)
        self.assertIs(first, application._active_window)
        self.assertEqual(
            [call(reveal=True), call(reveal=True)],
            first_source_window.show.call_args_list,
        )
        second_source_window.show.assert_called_once_with(reveal=True)
        self.assertEqual(
            "WM_DELETE_WINDOW",
            first_source_root.protocol.call_args.args[0],
        )
        self.assertEqual(
            "WM_DELETE_WINDOW",
            second_source_root.protocol.call_args.args[0],
        )

        first_source_root.protocol.call_args.args[1]()

        first_source_root.destroy.assert_called_once_with()
        second_source_root.destroy.assert_not_called()
        first.root.destroy.assert_not_called()
        self.assertEqual(
            {second: second_source_window},
            application._source_windows,
        )

    def test_source_windows_stay_bound_to_their_documents(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        first = Mock()
        second = Mock()
        first_source_window = Mock()
        second_source_window = Mock()
        application._windows = [first, second]
        application._active_window = first
        application._source_windows = {
            first: first_source_window,
            second: second_source_window,
        }

        application.document_window_activated(second)

        first_source_window.show.assert_not_called()
        second_source_window.show.assert_not_called()

        application.document_window_changed(first)
        application.document_window_changed(second)

        self.assertIs(second, application._active_window)
        first_source_window.show.assert_called_once_with(reveal=False)
        second_source_window.show.assert_called_once_with(reveal=False)

    def test_document_focus_and_changes_refresh_source_window(self) -> None:
        window = Mock()

        CrosswordDocumentWindow._document_focus_in(window)
        CrosswordDocumentWindow._set_dirty(window, True)

        window.application.document_window_activated.assert_called_once_with(window)
        self.assertTrue(window._dirty)
        window._update_title.assert_called_once_with()
        window.application.document_window_changed.assert_called_once_with(window)

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

    def test_closing_document_closes_only_its_source_window(
        self,
    ) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        first = Mock()
        second = Mock()
        first_source_window = Mock()
        second_source_window = Mock()
        application._windows = [first, second]
        application._active_window = second
        application._source_windows = {
            first: first_source_window,
            second: second_source_window,
        }
        application.show_no_document_state = Mock()

        application.close_window(second)

        self.assertIs(first, application._active_window)
        second_source_window.root.destroy.assert_called_once_with()
        first_source_window.root.destroy.assert_not_called()
        self.assertEqual(
            {first: first_source_window},
            application._source_windows,
        )
        second.root.destroy.assert_called_once_with()

        application.close_window(first)

        self.assertIsNone(application._active_window)
        first_source_window.root.destroy.assert_called_once_with()
        self.assertEqual({}, application._source_windows)
        first.root.destroy.assert_called_once_with()
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

    def test_application_opens_crossword_used_as_template(self) -> None:
        application = Mock()
        parent = Mock()
        crossword = create_blank_template(CrosswordSettings(3, 3), "numbered")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sablona.yaml"
            write_crossword_document(crossword, source)

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

    def test_crossword_window_writes_template_as_crossword_document(self) -> None:
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

            self.assertEqual(crossword, load_crossword_document(output))

        self.assertTrue(saved)
        self.assertEqual(output, window._path)
        window._set_dirty.assert_called_once_with(False)
        window.application.remember_recent_document.assert_called_once_with(output)

    def test_window_title_identifies_file_and_unsaved_changes(self) -> None:
        window = Mock()
        path = Path("krizovka.yaml")
        window._path = path
        window._dirty = True
        window._slot_list_window = None

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
        window._slot_list_window = None
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
        window._slot_list_window = None

        with patch("krizovkar.gui.sys.platform", "linux"):
            CrosswordDocumentWindow._update_title(window)

        window.root.attributes.assert_not_called()

    def test_title_updates_separate_slot_list_window(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.root = Mock()
        window._path = Path("krizovka.yaml")
        window._dirty = True
        window._slot_list_window = Mock()

        with patch("krizovkar.gui.sys.platform", "linux"):
            window._update_title()

        window.root.title.assert_called_once_with(
            "*krizovka.yaml — Křížovkář"
        )
        window._slot_list_window.title.assert_called_once_with(
            "Místa pro hesla — *krizovka.yaml"
        )

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

    def test_invalid_inline_edit_prevents_closing_window(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = False

        with patch("krizovkar.gui.messagebox.askyesnocancel") as ask:
            CrosswordDocumentWindow.request_close(window)

        ask.assert_not_called()
        window.application.close_window.assert_not_called()

    def test_crossword_pdf_actions_choose_puzzle_and_solution(self) -> None:
        application = Mock()
        application._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        solution = Mock()
        application._complete_grid_or_error.return_value = solution

        with patch("krizovkar.gui.create_grid_from_crossword") as create_grid:
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
                call(4, label="Uložit křížovku"),
                call(5, label="Uložit křížovku jako…"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [call(0, state="normal"), call(1, state="disabled")],
            application.export_menu.entryconfigure.call_args_list,
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

    def test_main_rejects_tk_older_than_version_nine(self) -> None:
        error_output = StringIO()
        with (
            patch("krizovkar.gui.tk.TkVersion", 8.6),
            patch("krizovkar.gui.tk.Tk") as root_type,
            redirect_stderr(error_output),
        ):
            exit_code = main([])

        self.assertEqual(2, exit_code)
        self.assertIn("vyžaduje Tk 9.0 nebo novější", error_output.getvalue())
        self.assertIn("nalezena verze 8.6", error_output.getvalue())
        root_type.assert_not_called()

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
        application.new_template_document.assert_not_called()
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

"""Testy logiky grafického rozhraní bez otevírání okna."""

from __future__ import annotations

import os
import subprocess
import tempfile
import tkinter as tk
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, call, patch

from krizovkar.dictionary import (
    CrosswordDictionary,
    DictionaryEntry,
    DictionaryError,
)
from krizovkar.generator import (
    FillingError,
    GenerationError,
    SecretGenerationResult,
    SecretRequirement,
    create_grid_from_crossword,
)
from krizovkar.gui import (
    CrosswordApplication,
    CrosswordDocumentWindow,
    CrosswordFillDialog,
    CrosswordFillInput,
    CrosswordPreview,
    CrosswordSettings,
    CrosswordSourceWindow,
    GuiInputError,
    NewTemplateResult,
    SecretGenerationDialog,
    SecretGenerationInput,
    TemplateGenerationDialog,
    _answer_conflicts_with_crossing,
    _available_dictionary_paths,
    _bind_text_entry_context_menu,
    _browse_for_dictionary,
    _configure_tk_runtime,
    _create_dictionary_browse_button,
    _create_dictionary_editor,
    _create_generation_entry,
    _create_help_menu,
    _create_view_menu,
    _create_window_menu,
    _dictionary_directory,
    _inherit_macos_menu_bar,
    _keyboard_shortcut,
    _multiple_cell_selection_sequence,
    _NewCrosswordPreferences,
    _open_pdf_in_default_application,
    _PdfOpenError,
    _PrintError,
    _recent_document_label,
    _recent_documents_storage_path,
    _RecentDocuments,
    _send_pdf_to_printer,
    _template_cli_command,
    _template_creation_mode,
    _template_generation_layout,
    clear_crossword_slot,
    create_blank_template,
    create_empty_template,
    create_initial_crossword,
    create_new_template,
    crossword_slot_pattern,
    fill_crossword_slot,
    main,
    parse_slot_content,
    parse_template_secret,
    parse_template_seed,
    parse_template_settings,
    set_crossword_cell_role,
    set_crossword_cell_slot_start,
    set_crossword_cells_role,
    set_crossword_cells_slot_start,
    slot_coordinates,
)
from krizovkar.model import (
    Coordinate,
    CrosswordDocument,
    CrosswordGrid,
    CrosswordSecretCellsPart,
    CrosswordSecretSlotPart,
    EmptyCellRole,
    Grid,
    LegendCellRole,
    LetterCell,
    LetterCellRole,
    ModelError,
    SecretCell,
    dump_crossword_document,
    load_crossword_document,
    load_crossword_grid,
    write_crossword_document,
)
from krizovkar.renderer import RenderError

PDF_BYTES = b"%PDF-1.7\n%%EOF\n"
TEST_DICTIONARY = CrosswordDictionary(
    entries=(DictionaryEntry(answer="LES", clues=("Porost stromů",)),)
)


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
    preview._role_selected_coordinates = frozenset()
    preview._role_selection_anchor = None
    preview._role_selection_base = frozenset()
    preview._context_menu_coordinates = ()
    preview._draw_resize_feedback = Mock()
    preview._redraw = Mock()
    preview._set_resize_cursor = Mock()
    preview._cell_clicked = Mock()
    preview.delete = Mock()
    return preview, resize_handler


def _document_history_window(
    crossword: CrosswordDocument,
    *,
    dirty: bool = False,
) -> CrosswordDocumentWindow:
    window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
    window._dirty = dirty
    window._crossword = crossword
    window._grid = None
    window._yaml_source_buffer = None
    window._yaml_source_error = None
    window._template_layout = _template_generation_layout(crossword)
    window._selected_slot_identifier = None
    window._save_inline_slot_edit = Mock(return_value=True)
    window._update_title = Mock()
    window.application = Mock()
    window._rebuild_slot_tree = Mock()
    window._refresh_crossword_view = Mock()
    window._initialize_document_history()
    return window


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

    def test_dictionaries_use_platform_data_directory(self) -> None:
        with (
            patch("krizovkar.gui.sys.platform", "darwin"),
            patch(
                "krizovkar.gui.Path.home",
                return_value=Path("/Users/test"),
            ),
        ):
            macos_directory = _dictionary_directory()

        self.assertEqual(
            Path(
                "/Users/test/Library/Application Support/krizovkar/"
                "dictionaries"
            ),
            macos_directory,
        )

        with (
            patch("krizovkar.gui.sys.platform", "linux"),
            patch("krizovkar.gui.os.name", "posix"),
            patch.dict(
                "krizovkar.gui.os.environ",
                {"XDG_DATA_HOME": "/home/test/data"},
            ),
        ):
            linux_directory = _dictionary_directory()

        self.assertEqual(
            Path("/home/test/data/krizovkar/dictionaries"),
            linux_directory,
        )

        windows_os = Mock()
        windows_os.name = "nt"
        windows_os.environ = {"APPDATA": "C:/Users/test/AppData/Roaming"}
        with (
            patch("krizovkar.gui.sys.platform", "win32"),
            patch("krizovkar.gui.os", windows_os),
        ):
            windows_directory = _dictionary_directory()

        self.assertEqual(
            Path("C:/Users/test/AppData/Roaming/krizovkar/dictionaries"),
            windows_directory,
        )

    def test_finds_json_dictionaries_in_expected_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            later = root / "Žlutý.JSON"
            first = root / "abeceda.json"
            ignored = root / "poznámky.txt"
            nested = root / "vnořený.json"
            later.write_text("{}", encoding="utf-8")
            first.write_text("{}", encoding="utf-8")
            ignored.write_text("{}", encoding="utf-8")
            nested.mkdir()

            paths = _available_dictionary_paths(root)

        self.assertEqual((first, later), paths)

    def test_dictionary_editor_offers_found_paths_and_accepts_text(
        self,
    ) -> None:
        parent = Mock()
        variable = Mock()
        editor = Mock()
        paths = (Path("/slovniky/a.json"), Path("/slovniky/b.json"))

        with (
            patch(
                "krizovkar.gui._available_dictionary_paths",
                return_value=paths,
            ),
            patch(
                "krizovkar.gui.ttk.Combobox",
                return_value=editor,
            ) as combobox,
            patch("krizovkar.gui._bind_text_entry_context_menu") as bind,
        ):
            result = _create_dictionary_editor(parent, variable)

        self.assertIs(editor, result)
        combobox.assert_called_once_with(
            parent,
            state="normal",
            values=("/slovniky/a.json", "/slovniky/b.json"),
            textvariable=variable,
        )
        bind.assert_called_once_with(editor)

    def test_dictionary_browser_button_uses_cli_toolbutton_style(self) -> None:
        parent = Mock()
        command = Mock()
        button = Mock()

        with patch(
            "krizovkar.gui.ttk.Button",
            return_value=button,
        ) as button_type:
            result = _create_dictionary_browse_button(parent, command)

        self.assertIs(button, result)
        button_type.assert_called_once_with(
            parent,
            text="…",
            command=command,
            style="Toolbutton",
        )
        button.grid.assert_called_once_with(
            row=0,
            column=1,
            padx=(8, 0),
        )

    def test_dictionary_browser_starts_in_expected_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory) / "krizovkar" / "dictionaries"
            selected = expected / "český.json"
            parent = Mock()
            variable = Mock()
            with (
                patch(
                    "krizovkar.gui._dictionary_directory",
                    return_value=expected,
                ),
                patch(
                    "krizovkar.gui.filedialog.askopenfilename",
                    return_value=str(selected),
                ) as choose,
            ):
                _browse_for_dictionary(parent, variable)

            self.assertTrue(expected.is_dir())
            choose.assert_called_once_with(
                parent=parent,
                title="Vybrat slovník Křížovkáře",
                initialdir=str(expected),
                filetypes=(
                    ("JSON soubory", "*.json"),
                    ("Všechny soubory", "*"),
                ),
            )
            variable.set.assert_called_once_with(str(selected))

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

    def test_new_crossword_preferences_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "new-crossword.json"
            dictionary = Path(directory) / "slovník.json"
            preferences = _NewCrosswordPreferences(storage_path)

            self.assertEqual(
                CrosswordSettings(15, 10),
                preferences.settings,
            )
            self.assertEqual("swedish", preferences.layout)
            self.assertIsNone(preferences.dictionary)

            preferences.remember(
                CrosswordSettings(12, 8),
                "numbered",
                dictionary,
            )
            loaded = _NewCrosswordPreferences(storage_path)

        self.assertEqual(CrosswordSettings(12, 8), loaded.settings)
        self.assertEqual("numbered", loaded.layout)
        self.assertEqual(dictionary, loaded.dictionary)

    def test_new_crossword_preferences_ignore_invalid_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "new-crossword.json"
            storage_path.write_text(
                '{"width": true, "height": 99, '
                '"layout": "neznámé", "dictionary": 42}',
                encoding="utf-8",
            )

            preferences = _NewCrosswordPreferences(storage_path)

        self.assertEqual(CrosswordSettings(15, 10), preferences.settings)
        self.assertEqual("swedish", preferences.layout)
        self.assertIsNone(preferences.dictionary)

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

    def test_document_history_shortcuts_bind_undo_and_redo(self) -> None:
        window = Mock()
        widget = Mock()

        with patch("krizovkar.gui.sys.platform", "darwin"):
            CrosswordDocumentWindow._bind_history_shortcuts(window, widget)

        self.assertEqual(
            [
                call("<Command-z>", window._undo_event),
                call("<Command-Shift-Z>", window._redo_event),
            ],
            widget.bind.call_args_list,
        )

    def test_edit_menu_reflects_history_secret_and_fill_state(self) -> None:
        window = Mock()
        window._undo_menu_index = 0
        window._redo_menu_index = 1
        window._generate_secret_menu_index = 3
        window._fill_crossword_menu_index = 4
        window._history = [object(), object()]
        window._history_index = 0
        window._crossword = Mock(
            secrets=(),
            slots=(Mock(answer=None),),
        )

        CrosswordDocumentWindow._refresh_edit_menu(window)

        self.assertEqual(
            [
                call(0, state="disabled"),
                call(1, state="normal"),
                call(3, label="Přidat tajenku…", state="normal"),
                call(4, state="normal"),
            ],
            window.edit_menu.entryconfigure.call_args_list,
        )

        window.edit_menu.reset_mock()
        window._history_index = 1
        window._crossword = Mock(
            secrets=(object(),),
            slots=(Mock(answer=None),),
        )
        CrosswordDocumentWindow._refresh_edit_menu(window)

        self.assertEqual(
            [
                call(0, state="normal"),
                call(1, state="disabled"),
                call(3, label="Změnit tajenku…", state="normal"),
                call(4, state="normal"),
            ],
            window.edit_menu.entryconfigure.call_args_list,
        )

        window.edit_menu.reset_mock()
        window._crossword = None
        CrosswordDocumentWindow._refresh_edit_menu(window)

        self.assertEqual(
            [
                call(0, state="normal"),
                call(1, state="disabled"),
                call(3, label="Přidat tajenku…", state="disabled"),
                call(4, state="disabled"),
            ],
            window.edit_menu.entryconfigure.call_args_list,
        )

        window.edit_menu.reset_mock()
        window._crossword = Mock(
            secrets=(),
            slots=(Mock(answer="HOTOVO"),),
        )
        CrosswordDocumentWindow._refresh_edit_menu(window)

        self.assertEqual(
            [
                call(0, state="normal"),
                call(1, state="disabled"),
                call(3, label="Přidat tajenku…", state="normal"),
                call(4, state="disabled"),
            ],
            window.edit_menu.entryconfigure.call_args_list,
        )

    def test_multiple_cell_selection_uses_platform_modifier(self) -> None:
        with patch("krizovkar.gui.sys.platform", "darwin"):
            self.assertEqual(
                "<Command-Button-1>",
                _multiple_cell_selection_sequence(),
            )
        with patch("krizovkar.gui.sys.platform", "linux"):
            self.assertEqual(
                "<Control-Button-1>",
                _multiple_cell_selection_sequence(),
            )

    def test_menu_uses_macos_tk_command_accelerators(self) -> None:
        window = Mock()
        menu = Mock()
        file_menu = Mock()
        recent_documents_menu = Mock()
        export_menu = Mock()
        open_pdf_menu = Mock()
        print_menu = Mock()
        edit_menu = Mock()
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
                    open_pdf_menu,
                    print_menu,
                    edit_menu,
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
                "Nová křížovka…",
                "Otevřít…",
                "Uložit",
                "Uložit jako…",
                "Zavřít",
            ],
            [
                item.kwargs["label"]
                for item in file_menu.add_command.call_args_list
            ],
        )
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
        file_menu.add_cascade.assert_any_call(
            label="Exportovat",
            menu=export_menu,
        )
        file_menu.add_cascade.assert_any_call(
            label="Otevřít jako PDF",
            menu=open_pdf_menu,
        )
        file_menu.add_cascade.assert_any_call(
            label="Tisknout",
            menu=print_menu,
        )
        self.assertEqual(
            [
                "Zpět",
                "Vpřed",
                "Přidat tajenku…",
                "Vygenerovat křížovku…",
            ],
            [
                item.kwargs["label"]
                for item in edit_menu.add_command.call_args_list
            ],
        )
        self.assertEqual(
            ["Command-Z", "Command-Shift-Z"],
            [
                item.kwargs["accelerator"]
                for item in edit_menu.add_command.call_args_list[:2]
            ],
        )
        self.assertEqual(1, edit_menu.add_separator.call_count)
        self.assertIs(
            window.generate_crossword_secret,
            edit_menu.add_command.call_args_list[2].kwargs["command"],
        )
        self.assertIs(
            window.generate_complete_crossword,
            edit_menu.add_command.call_args_list[3].kwargs["command"],
        )
        window._bind_history_shortcuts.assert_called_once_with(window.root)
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
                call(label="Úpravy", menu=edit_menu),
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
        export_menu = Mock()
        open_pdf_menu = Mock()
        print_menu = Mock()
        edit_menu = Mock()
        view_menu = Mock()
        slot_list_placement_menu = Mock()
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
                    export_menu,
                    open_pdf_menu,
                    print_menu,
                    edit_menu,
                    view_menu,
                    slot_list_placement_menu,
                    window_menu,
                    help_menu,
                ),
            ) as menu_type,
        ):
            application._build_menu()

        commands = file_menu.add_command.call_args_list
        self.assertEqual(
            [
                "Nová křížovka…",
                "Otevřít…",
                "Uložit",
                "Uložit jako…",
                "Zavřít",
            ],
            [item.kwargs["label"] for item in commands],
        )
        self.assertEqual(
            [
                "Command-N",
                "Command-O",
                "Command-S",
                "Command-Shift-S",
                "Command-W",
            ],
            [item.kwargs["accelerator"] for item in commands],
        )
        self.assertTrue(
            all(
                item.kwargs["state"] == "disabled"
                for item in commands[2:]
            )
        )
        commands[1].kwargs["command"]()
        application.choose_document.assert_called_once_with(parent=None)
        self.assertEqual(3, file_menu.add_separator.call_count)
        self.assertEqual(
            [
                call(
                    label="Otevřít poslední",
                    menu=recent_documents_menu,
                ),
                call(
                    label="Exportovat",
                    menu=export_menu,
                    state="disabled",
                ),
                call(
                    label="Otevřít jako PDF",
                    menu=open_pdf_menu,
                    state="disabled",
                ),
                call(
                    label="Tisknout",
                    menu=print_menu,
                    state="disabled",
                ),
            ],
            file_menu.add_cascade.call_args_list,
        )
        for submenu, labels in (
            (
                export_menu,
                (
                    "Křížovku bez písmen (PDF)…",
                    "Řešení s písmeny (PDF)…",
                    "Křížovku bez písmen (LaTeX)…",
                    "Řešení s písmeny (LaTeX)…",
                    "Mřížku bez písmen (YAML)…",
                    "Mřížku s písmeny (YAML)…",
                ),
            ),
            (
                open_pdf_menu,
                ("Křížovku bez písmen…", "Řešení s písmeny…"),
            ),
            (
                print_menu,
                ("Křížovku bez písmen…", "Řešení s písmeny…"),
            ),
        ):
            self.assertEqual(
                list(labels),
                [
                    item.kwargs["label"]
                    for item in submenu.add_command.call_args_list
                ],
            )
            self.assertTrue(
                all(
                    item.kwargs["state"] == "disabled"
                    for item in submenu.add_command.call_args_list
                )
            )
        self.assertEqual(2, export_menu.add_separator.call_count)
        self.assertEqual(
            [
                "Zpět",
                "Vpřed",
                "Přidat tajenku…",
                "Vygenerovat křížovku…",
            ],
            [
                item.kwargs["label"]
                for item in edit_menu.add_command.call_args_list
            ],
        )
        self.assertEqual(
            ["Command-Z", "Command-Shift-Z"],
            [
                item.kwargs["accelerator"]
                for item in edit_menu.add_command.call_args_list[:2]
            ],
        )
        self.assertTrue(
            all(
                item.kwargs["state"] == "disabled"
                for item in edit_menu.add_command.call_args_list
            )
        )
        edit_menu.add_separator.assert_called_once_with()
        menu_type.assert_any_call(menu, name="window")
        menu_type.assert_any_call(menu, name="help")
        view_menu.add_command.assert_called_once_with(
            label="Zdroj YAML",
            state="disabled",
        )
        view_menu.add_separator.assert_called_once_with()
        view_menu.add_cascade.assert_called_once_with(
            label="Místa pro hesla",
            menu=slot_list_placement_menu,
            state="disabled",
        )
        slot_list_placement_menu.setvar.assert_called_once_with(
            "krizovkar_no_document_slot_list_placement",
            "main",
        )
        placement_items = (
            slot_list_placement_menu.add_radiobutton.call_args_list
        )
        self.assertEqual(
            ["V hlavním okně", "V samostatném okně"],
            [item.kwargs["label"] for item in placement_items],
        )
        self.assertTrue(
            all(
                item.kwargs["state"] == "disabled"
                for item in placement_items
            )
        )
        menu.add_cascade.assert_has_calls(
            [
                call(label="Soubor", menu=file_menu),
                call(label="Úpravy", menu=edit_menu),
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

    def test_modal_dialog_inherits_application_menu_on_macos(self) -> None:
        dialog = Mock()
        owner = dialog.master.winfo_toplevel.return_value
        owner.cget.return_value = ".application_menu"

        with patch("krizovkar.gui.sys.platform", "darwin"):
            _inherit_macos_menu_bar(dialog)

        dialog.configure.assert_called_once_with(menu=".application_menu")

    def test_modal_dialog_keeps_native_menu_handling_off_macos(self) -> None:
        dialog = Mock()

        with patch("krizovkar.gui.sys.platform", "linux"):
            _inherit_macos_menu_bar(dialog)

        dialog.master.winfo_toplevel.assert_not_called()
        dialog.configure.assert_not_called()

    def test_text_entry_context_menu_uses_standard_edit_events(self) -> None:
        editor = Mock()
        editor.selection_present.side_effect = (True, False)
        editor.clipboard_get.side_effect = ("text ve schránce", tk.TclError())
        editor.get.side_effect = ("HESLO", "")
        menu = Mock()

        with patch("krizovkar.gui.tk.Menu", return_value=menu) as menu_type:
            _bind_text_entry_context_menu(editor)

        menu_type.assert_called_once_with(editor, tearoff=False)
        commands = {
            item.kwargs["label"]: item.kwargs["command"]
            for item in menu.add_command.call_args_list
        }
        self.assertEqual(
            {"Vyjmout", "Kopírovat", "Vložit", "Vybrat vše"},
            commands.keys(),
        )
        menu.add_separator.assert_called_once_with()
        editor.bind.assert_called_once()
        event_name, show_context_menu = editor.bind.call_args.args
        self.assertEqual("<<ContextMenu>>", event_name)
        self.assertEqual("+", editor.bind.call_args.kwargs["add"])
        event = Mock(x_root=120, y_root=240)

        self.assertEqual("break", show_context_menu(event))
        self.assertEqual("break", show_context_menu(event))

        menu.entryconfigure.assert_has_calls(
            [
                call("Vyjmout", state=tk.NORMAL),
                call("Kopírovat", state=tk.NORMAL),
                call("Vložit", state=tk.NORMAL),
                call("Vybrat vše", state=tk.NORMAL),
                call("Vyjmout", state=tk.DISABLED),
                call("Kopírovat", state=tk.DISABLED),
                call("Vložit", state=tk.DISABLED),
                call("Vybrat vše", state=tk.DISABLED),
            ]
        )
        self.assertEqual(2, editor.focus_set.call_count)
        self.assertEqual(
            [call(120, 240), call(120, 240)],
            menu.tk_popup.call_args_list,
        )
        self.assertEqual(2, menu.grab_release.call_count)

        for label in (
            "Vyjmout",
            "Kopírovat",
            "Vložit",
            "Vybrat vše",
        ):
            commands[label]()
        self.assertEqual(
            [
                call("<<Cut>>"),
                call("<<Copy>>"),
                call("<<Paste>>"),
                call("<<SelectAll>>"),
            ],
            editor.event_generate.call_args_list,
        )

    def test_source_window_shows_editable_yaml_for_document(self) -> None:
        source_window = CrosswordSourceWindow.__new__(CrosswordSourceWindow)
        source_window.root = Mock()
        source_window.source_text = Mock()
        document_window = Mock()
        document_window._path = Path("krizovka.yaml")
        document_window._dirty = True
        document = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        output = StringIO()
        dump_crossword_document(document, output)
        document_window._yaml_source.return_value = output.getvalue()
        source_window._document_window = document_window
        source_window.source_text.yview.return_value = ()
        source_window.source_text.xview.return_value = ()
        source_window.source_text.get.return_value = ""

        source_window.show(reveal=True)

        source_window.root.transient.assert_not_called()
        source_window.root.title.assert_called_once_with(
            "Zdroj YAML — *krizovka.yaml"
        )
        yaml_source = source_window.source_text.insert.call_args.args[1]
        self.assertIn("format: krizovkar", yaml_source)
        self.assertIn("kind: crossword", yaml_source)
        source_window.source_text.delete.assert_called_once_with("1.0", tk.END)
        source_window.source_text.edit_reset.assert_called_once_with()
        source_window.source_text.edit_modified.assert_called_once_with(False)
        source_window.root.deiconify.assert_called_once_with()
        source_window.root.lift.assert_called_once_with()
        source_window.source_text.focus_set.assert_called_once_with()

    def test_source_window_uses_narrow_default_width(self) -> None:
        source_window = Mock()

        CrosswordSourceWindow._configure_window(source_window)

        source_window.root.geometry.assert_called_once_with("400x680")

    def test_source_window_applies_user_changes_immediately(self) -> None:
        source_window = CrosswordSourceWindow.__new__(CrosswordSourceWindow)
        source_window.source_text = Mock()
        source_window.source_text.edit_modified.return_value = True
        source_window.source_text.get.return_value = "format: krizovkar\n"
        source_window._document_window = Mock()

        source_window._source_changed()

        source_window.source_text.edit_modified.assert_has_calls(
            [call(), call(False)]
        )
        source_window._document_window._apply_yaml_source.assert_called_once_with(
            "format: krizovkar\n"
        )

    def test_source_window_ignores_programmatic_modified_event(self) -> None:
        source_window = CrosswordSourceWindow.__new__(CrosswordSourceWindow)
        source_window.source_text = Mock()
        source_window.source_text.edit_modified.return_value = False
        source_window._document_window = Mock()

        source_window._source_changed()

        source_window._document_window._apply_yaml_source.assert_not_called()

    def test_source_window_keeps_unchanged_editor_content(self) -> None:
        source_window = CrosswordSourceWindow.__new__(CrosswordSourceWindow)
        source_window.source_text = Mock()
        source_window.source_text.get.return_value = "format: krizovkar\n"

        source_window._replace_content("format: krizovkar\n")

        source_window.source_text.delete.assert_not_called()
        source_window.source_text.insert.assert_not_called()

    def test_valid_yaml_source_updates_document_immediately(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window._grid = Mock()
        window._yaml_source_buffer = None
        window._yaml_source_error = None
        window._template_layout = "numbered"
        window._selected_slot_identifier = "h1"
        window._set_dirty = Mock()
        window._rebuild_slot_tree = Mock()
        window._refresh_crossword_view = Mock()
        changed = create_blank_template(
            CrosswordSettings(4, 4),
            "numbered",
        )
        output = StringIO()
        dump_crossword_document(changed, output)

        window._apply_yaml_source(output.getvalue())

        self.assertEqual(changed, window._crossword)
        self.assertEqual(output.getvalue(), window._yaml_source_buffer)
        self.assertIsNone(window._yaml_source_error)
        self.assertEqual("numbered", window._template_layout)
        window._set_dirty.assert_called_once_with(True, source_changed=True)
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()

    def test_invalid_yaml_source_shows_error_only_in_preview(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window._grid = Mock()
        window._yaml_source_buffer = None
        window._yaml_source_error = None
        window._template_layout = "numbered"
        window._selected_slot_identifier = "h1"
        window._set_dirty = Mock()
        window._rebuild_slot_tree = Mock()
        window._refresh_crossword_view = Mock()

        with patch("krizovkar.gui.messagebox.showerror") as show_error:
            window._apply_yaml_source("format: [\n")

        self.assertIsNone(window._crossword)
        self.assertEqual("format: [\n", window._yaml_source_buffer)
        self.assertIn("neplatný YAML", window._yaml_source_error)
        self.assertIsNone(window._selected_slot_identifier)
        show_error.assert_not_called()
        window._set_dirty.assert_called_once_with(True, source_changed=True)

        window.crossword_preview = Mock()
        window._refresh_crossword_preview()

        self.assertIsNone(window._grid)
        window.crossword_preview.clear_preview.assert_called_once_with(
            window._yaml_source_error
        )

    def test_invalid_yaml_source_is_kept_after_source_window_closes(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._yaml_source_buffer = "format: [\n"

        self.assertEqual("format: [\n", window._yaml_source())

    def test_document_history_restores_invalid_yaml_source(self) -> None:
        original = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window = _document_history_window(original)

        window._apply_yaml_source("format: [\n")

        self.assertIsNone(window._crossword)
        self.assertTrue(window._dirty)

        self.assertTrue(window.undo_document())
        self.assertEqual(original, window._crossword)
        self.assertIsNone(window._yaml_source_error)
        self.assertFalse(window._dirty)

        self.assertTrue(window.redo_document())
        self.assertIsNone(window._crossword)
        self.assertIn("neplatný YAML", window._yaml_source_error)
        self.assertTrue(window._dirty)

    def test_document_history_discards_redo_after_a_new_change(self) -> None:
        original = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window = _document_history_window(original)
        window._crossword = fill_crossword_slot(
            original,
            "h1",
            "ABC",
            "První řádek",
        )
        window._set_dirty(True)
        self.assertTrue(window.undo_document())

        window._crossword = fill_crossword_slot(
            original,
            "h2",
            "DEF",
            "Druhý řádek",
        )
        window._set_dirty(True)

        self.assertFalse(window.redo_document())
        self.assertEqual(2, len(window._history))

    def test_document_history_tracks_the_saved_state(self) -> None:
        original = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        window = _document_history_window(original)
        changed = fill_crossword_slot(
            original,
            "h1",
            "ABC",
            "První řádek",
        )
        window._crossword = changed
        window._set_dirty(True)
        window._set_dirty(False)

        self.assertFalse(window._dirty)
        self.assertTrue(window.undo_document())
        self.assertEqual(original, window._crossword)
        self.assertTrue(window._dirty)

        self.assertTrue(window.redo_document())
        self.assertEqual(changed, window._crossword)
        self.assertFalse(window._dirty)

    def test_undo_restores_content_discarded_by_slot_change(self) -> None:
        original = fill_crossword_slot(
            create_blank_template(
                CrosswordSettings(3, 3),
                "numbered",
            ),
            "h2",
            "DEF",
            "Druhý řádek",
        )
        window = _document_history_window(original)

        with patch("krizovkar.gui.messagebox.askyesno") as ask:
            window._preview_cell_slot_changed(
                (Coordinate(2, 2),),
                "horizontal",
                True,
            )

        changed = window._crossword
        ask.assert_not_called()
        self.assertNotEqual(original, changed)
        self.assertTrue(window._dirty)

        self.assertTrue(window.undo_document())
        self.assertEqual(original, window._crossword)
        self.assertFalse(window._dirty)

        self.assertTrue(window.redo_document())
        self.assertEqual(changed, window._crossword)
        self.assertTrue(window._dirty)

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
            ["*Nová křížovka", "krizovka.yaml"],
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

    def test_uses_answer_as_missing_clue(self) -> None:
        self.assertEqual(
            ("CHATA", "CHATA"),
            parse_slot_content("CHATA", "  ", 4),
        )

    def test_template_generation_dialog_uses_crossword_title(self) -> None:
        parent = Mock()

        with patch(
            "krizovkar.gui.simpledialog.Dialog.__init__"
        ) as initialize:
            dialog = TemplateGenerationDialog(
                parent,
                initial_settings=CrosswordSettings(15, 10),
                initial_layout="swedish",
                initial_content_mode="empty",
            )

        initialize.assert_called_once_with(parent, "Nová křížovka")
        self.assertIsNone(dialog._new_template)

    def test_template_dialog_uses_short_layout_and_content_choices(
        self,
    ) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._initial_settings = CrosswordSettings(15, 10)
        dialog._initial_layout = "swedish"
        dialog._initial_content_mode = "empty"
        dialog._initial_dictionary = Path("/slovníky/český.json")
        dialog._initial_seed = 123
        dialog._fit_generation_controls_width = Mock()
        dialog._update_generation_controls = Mock()
        dialog._refresh_cli_command = Mock()
        master = Mock()
        dimensions = Mock()
        generation_controls = Mock()
        dictionary_row = Mock()
        variables = tuple(Mock() for _ in range(8))
        layout_value = variables[2]
        content_value = variables[3]
        width_editor = Mock()

        with (
            patch("krizovkar.gui._inherit_macos_menu_bar"),
            patch(
                "krizovkar.gui.ttk.Frame",
                side_effect=(
                    dimensions,
                    generation_controls,
                    dictionary_row,
                ),
            ),
            patch("krizovkar.gui.ttk.Label", return_value=Mock()),
            patch(
                "krizovkar.gui.tk.StringVar",
                side_effect=variables,
            ) as string_var,
            patch(
                "krizovkar.gui.ttk.Spinbox",
                side_effect=(width_editor, Mock()),
            ),
            patch(
                "krizovkar.gui.ttk.Radiobutton",
                return_value=Mock(),
            ) as radio_type,
            patch(
                "krizovkar.gui._create_generation_entry",
                side_effect=(Mock(), Mock()),
            ),
            patch("krizovkar.gui._bind_text_entry_context_menu"),
            patch(
                "krizovkar.gui._create_dictionary_editor",
                return_value=Mock(),
            ),
            patch("krizovkar.gui._create_dictionary_browse_button"),
        ):
            initial_focus = TemplateGenerationDialog.body(dialog, master)

        self.assertIs(width_editor, initial_focus)
        self.assertEqual(
            call(master=master, value="/slovníky/český.json"),
            string_var.call_args_list[6],
        )
        self.assertEqual(
            [
                call(
                    master,
                    text="Švédská",
                    variable=layout_value,
                    value="swedish",
                ),
                call(
                    master,
                    text="Číslovaná",
                    variable=layout_value,
                    value="numbered",
                ),
                call(
                    master,
                    text="Prázdná",
                    variable=content_value,
                    value="empty",
                ),
                call(
                    master,
                    text="Pouze tajenka",
                    variable=content_value,
                    value="secret",
                ),
                call(
                    master,
                    text="Vyplněná",
                    variable=content_value,
                    value="filled",
                ),
            ],
            radio_type.call_args_list,
        )

    def test_parses_template_settings(self) -> None:
        self.assertEqual(
            CrosswordSettings(width=15, height=10),
            parse_template_settings(" 15 ", "10"),
        )

    def test_rejects_invalid_template_dimensions(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "musí být celé číslo"):
            parse_template_settings("patnáct", "10")
        with self.assertRaisesRegex(GuiInputError, "větší než nula"):
            parse_template_settings("15", "0")
        with self.assertRaisesRegex(GuiInputError, "nejvýše 50"):
            parse_template_settings("51", "10")

    def test_parses_template_seed(self) -> None:
        self.assertEqual(-42, parse_template_seed(" -42 "))

    def test_rejects_invalid_template_seed(self) -> None:
        for value in ("", "1,5", "sémě"):
            with self.subTest(value=value), self.assertRaisesRegex(
                GuiInputError,
                "Sémě musí být celé číslo",
            ):
                parse_template_seed(value)

    def test_parses_optional_template_secret(self) -> None:
        self.assertIsNone(parse_template_secret("  "))
        self.assertEqual(
            SecretRequirement(words=("KOMU", "SE", "NELENÍ")),
            parse_template_secret(" Komu se nelení. "),
        )
        self.assertEqual(
            SecretRequirement(words=("DÁREKRADOST",)),
            parse_template_secret("Dárek\N{NO-BREAK SPACE}radost"),
        )

    def test_rejects_unsupported_template_secret_character(self) -> None:
        with self.assertRaisesRegex(
            GuiInputError,
            "nepodporovaný znak '1'",
        ):
            parse_template_secret("Tajenka 1")

    def test_secret_generation_dialog_uses_add_title(self) -> None:
        parent = Mock()

        with patch(
            "krizovkar.gui.simpledialog.Dialog.__init__"
        ) as initialize:
            dialog = SecretGenerationDialog(parent)

        initialize.assert_called_once_with(parent, "Přidat tajenku")
        self.assertIsNone(dialog._input)

    def test_secret_generation_dialog_starts_with_secret_field(self) -> None:
        dialog = SecretGenerationDialog.__new__(SecretGenerationDialog)
        master = Mock()
        label = Mock()
        secret_editor = Mock()
        dictionary_row = Mock()

        with (
            patch("krizovkar.gui._inherit_macos_menu_bar"),
            patch(
                "krizovkar.gui.ttk.Label",
                return_value=label,
            ) as label_type,
            patch(
                "krizovkar.gui.tk.StringVar",
                side_effect=(Mock(), Mock()),
            ),
            patch(
                "krizovkar.gui.ttk.Entry",
                return_value=secret_editor,
            ),
            patch(
                "krizovkar.gui.ttk.Frame",
                return_value=dictionary_row,
            ),
            patch("krizovkar.gui._bind_text_entry_context_menu"),
            patch(
                "krizovkar.gui._create_dictionary_editor",
                return_value=Mock(),
            ),
            patch("krizovkar.gui._create_dictionary_browse_button"),
        ):
            SecretGenerationDialog.body(dialog, master)

        self.assertEqual(
            [
                call(master, text="Tajenka"),
                call(master, text="Slovník"),
            ],
            label_type.call_args_list,
        )
        self.assertEqual(
            call(row=0, column=0, sticky="w"),
            label.grid.call_args_list[0],
        )

    def test_secret_generation_dialog_uses_add_button(self) -> None:
        dialog = SecretGenerationDialog.__new__(SecretGenerationDialog)
        dialog.ok = Mock()
        dialog.cancel = Mock()
        dialog.bind = Mock()
        buttons = Mock()

        with (
            patch("krizovkar.gui.ttk.Frame", return_value=buttons),
            patch(
                "krizovkar.gui.ttk.Button",
                return_value=Mock(),
            ) as button_type,
        ):
            SecretGenerationDialog.buttonbox(dialog)

        self.assertEqual(
            call(
                buttons,
                text="Přidat",
                command=dialog.ok,
                default="active",
            ),
            button_type.call_args_list[0],
        )

    def test_secret_generation_dialog_returns_normalized_requirement(
        self,
    ) -> None:
        dialog = SecretGenerationDialog.__new__(SecretGenerationDialog)
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = " Komu se nelení. "
        dialog._secret_editor = Mock()
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = "slovnik.json"
        dialog._dictionary_editor = Mock()
        dialog._input = None

        with patch(
            "krizovkar.gui.load_dictionary",
            return_value=TEST_DICTIONARY,
        ) as load:
            valid = SecretGenerationDialog.validate(dialog)
        SecretGenerationDialog.apply(dialog)

        self.assertTrue(valid)
        self.assertEqual(
            SecretGenerationInput(
                requirement=SecretRequirement(
                    words=("KOMU", "SE", "NELENÍ")
                ),
                dictionary=TEST_DICTIONARY,
            ),
            dialog.result,
        )
        load.assert_called_once_with(Path("slovnik.json"))
        dialog._secret_editor.focus_set.assert_not_called()
        dialog._dictionary_editor.focus_set.assert_not_called()

    def test_secret_generation_dialog_keeps_blank_secret_open(self) -> None:
        dialog = SecretGenerationDialog.__new__(SecretGenerationDialog)
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = "  "
        dialog._secret_editor = Mock()
        dialog._input = Mock()

        with patch("krizovkar.gui.messagebox.showerror") as show_error:
            valid = SecretGenerationDialog.validate(dialog)

        self.assertFalse(valid)
        self.assertIsNone(dialog._input)
        show_error.assert_called_once_with(
            "Tajenku nelze přidat",
            "Vyplňte tajenku.",
            parent=dialog,
        )
        dialog._secret_editor.focus_set.assert_called_once_with()

    def test_secret_generation_dialog_accepts_missing_dictionary(self) -> None:
        dialog = SecretGenerationDialog.__new__(SecretGenerationDialog)
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = "Tajenka"
        dialog._secret_editor = Mock()
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = "  "
        dialog._dictionary_editor = Mock()
        dialog._input = Mock()

        with (
            patch("krizovkar.gui.load_dictionary") as load,
            patch("krizovkar.gui.messagebox.showerror") as show_error,
        ):
            valid = SecretGenerationDialog.validate(dialog)
        SecretGenerationDialog.apply(dialog)

        self.assertTrue(valid)
        self.assertEqual(
            SecretGenerationInput(
                requirement=SecretRequirement(words=("TAJENKA",)),
                dictionary=None,
            ),
            dialog.result,
        )
        load.assert_not_called()
        show_error.assert_not_called()
        dialog._dictionary_editor.focus_set.assert_not_called()

    def test_secret_generation_dialog_rejects_invalid_dictionary(self) -> None:
        dialog = SecretGenerationDialog.__new__(SecretGenerationDialog)
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = "Tajenka"
        dialog._secret_editor = Mock()
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = "poškozený.json"
        dialog._dictionary_editor = Mock()
        dialog._input = Mock()

        with (
            patch(
                "krizovkar.gui.load_dictionary",
                side_effect=DictionaryError("slovník není platný"),
            ),
            patch("krizovkar.gui.messagebox.showerror") as show_error,
        ):
            valid = SecretGenerationDialog.validate(dialog)

        self.assertFalse(valid)
        self.assertIsNone(dialog._input)
        show_error.assert_called_once_with(
            "Tajenku nelze přidat",
            "slovník není platný",
            parent=dialog,
        )
        dialog._secret_editor.focus_set.assert_not_called()
        dialog._dictionary_editor.focus_set.assert_called_once_with()

    def test_crossword_fill_dialog_uses_generation_title_and_random_seed(
        self,
    ) -> None:
        parent = Mock()

        with (
            patch(
                "krizovkar.gui.random.randrange",
                return_value=123,
            ) as random_seed,
            patch(
                "krizovkar.gui.simpledialog.Dialog.__init__"
            ) as initialize,
        ):
            dialog = CrosswordFillDialog(parent)

        random_seed.assert_called_once_with(2**63)
        initialize.assert_called_once_with(parent, "Vygenerovat křížovku")
        self.assertEqual(123, dialog._initial_seed)
        self.assertIsNone(dialog._input)

    def test_crossword_fill_dialog_offers_dictionary_and_seed(self) -> None:
        dialog = CrosswordFillDialog.__new__(CrosswordFillDialog)
        dialog._initial_seed = 123
        master = Mock()
        label = Mock()
        dictionary_row = Mock()
        dictionary_value = Mock()
        dictionary_editor = Mock()
        seed_value = Mock()
        seed_editor = Mock()

        with (
            patch("krizovkar.gui._inherit_macos_menu_bar"),
            patch(
                "krizovkar.gui.ttk.Label",
                return_value=label,
            ) as label_type,
            patch(
                "krizovkar.gui.ttk.Frame",
                return_value=dictionary_row,
            ),
            patch(
                "krizovkar.gui.tk.StringVar",
                side_effect=(dictionary_value, seed_value),
            ) as variable_type,
            patch(
                "krizovkar.gui._create_dictionary_editor",
                return_value=dictionary_editor,
            ) as create_dictionary,
            patch(
                "krizovkar.gui._create_dictionary_browse_button"
            ) as create_browse_button,
            patch(
                "krizovkar.gui.ttk.Entry",
                return_value=seed_editor,
            ) as entry_type,
            patch("krizovkar.gui._bind_text_entry_context_menu") as bind,
        ):
            initial_focus = CrosswordFillDialog.body(dialog, master)

        self.assertIs(dictionary_editor, initial_focus)
        self.assertEqual(
            [call(master, text="Slovník"), call(master, text="Sémě")],
            label_type.call_args_list,
        )
        self.assertEqual(
            [
                call(master=master),
                call(master=master, value="123"),
            ],
            variable_type.call_args_list,
        )
        create_dictionary.assert_called_once_with(
            dictionary_row,
            dictionary_value,
        )
        create_browse_button.assert_called_once_with(
            dictionary_row,
            dialog._choose_dictionary,
        )
        entry_type.assert_called_once_with(
            master,
            width=36,
            textvariable=seed_value,
        )
        bind.assert_called_once_with(seed_editor)

    def test_crossword_fill_dialog_uses_generate_button(self) -> None:
        dialog = CrosswordFillDialog.__new__(CrosswordFillDialog)
        dialog.ok = Mock()
        dialog.cancel = Mock()
        dialog.bind = Mock()
        buttons = Mock()

        with (
            patch("krizovkar.gui.ttk.Frame", return_value=buttons),
            patch(
                "krizovkar.gui.ttk.Button",
                return_value=Mock(),
            ) as button_type,
        ):
            CrosswordFillDialog.buttonbox(dialog)

        self.assertEqual(
            call(
                buttons,
                text="Vygenerovat",
                command=dialog.ok,
                default="active",
            ),
            button_type.call_args_list[0],
        )

    def test_crossword_fill_dialog_returns_dictionary_and_seed(self) -> None:
        dialog = CrosswordFillDialog.__new__(CrosswordFillDialog)
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = "slovnik.json"
        dialog._dictionary_editor = Mock()
        dialog._seed_value = Mock()
        dialog._seed_value.get.return_value = "42"
        dialog._seed_editor = Mock()
        dialog._input = None

        with patch(
            "krizovkar.gui.load_dictionary",
            return_value=TEST_DICTIONARY,
        ) as load:
            valid = CrosswordFillDialog.validate(dialog)
        CrosswordFillDialog.apply(dialog)

        self.assertTrue(valid)
        self.assertEqual(
            CrosswordFillInput(dictionary=TEST_DICTIONARY, seed=42),
            dialog.result,
        )
        load.assert_called_once_with(Path("slovnik.json"))
        dialog._dictionary_editor.focus_set.assert_not_called()
        dialog._seed_editor.focus_set.assert_not_called()

    def test_crossword_fill_dialog_requires_dictionary(self) -> None:
        dialog = CrosswordFillDialog.__new__(CrosswordFillDialog)
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = "  "
        dialog._dictionary_editor = Mock()
        dialog._input = Mock()

        with patch("krizovkar.gui.messagebox.showerror") as show_error:
            valid = CrosswordFillDialog.validate(dialog)

        self.assertFalse(valid)
        self.assertIsNone(dialog._input)
        show_error.assert_called_once_with(
            "Křížovku nelze vygenerovat",
            "Vyberte slovník.",
            parent=dialog,
        )
        dialog._dictionary_editor.focus_set.assert_called_once_with()

    def test_crossword_fill_dialog_rejects_invalid_dictionary(self) -> None:
        dialog = CrosswordFillDialog.__new__(CrosswordFillDialog)
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = "poškozený.json"
        dialog._dictionary_editor = Mock()
        dialog._input = Mock()

        with (
            patch(
                "krizovkar.gui.load_dictionary",
                side_effect=DictionaryError("slovník není platný"),
            ),
            patch("krizovkar.gui.messagebox.showerror") as show_error,
        ):
            valid = CrosswordFillDialog.validate(dialog)

        self.assertFalse(valid)
        self.assertIsNone(dialog._input)
        show_error.assert_called_once_with(
            "Křížovku nelze vygenerovat",
            "slovník není platný",
            parent=dialog,
        )
        dialog._dictionary_editor.focus_set.assert_called_once_with()

    def test_crossword_fill_dialog_rejects_invalid_seed(self) -> None:
        dialog = CrosswordFillDialog.__new__(CrosswordFillDialog)
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = "slovnik.json"
        dialog._dictionary_editor = Mock()
        dialog._seed_value = Mock()
        dialog._seed_value.get.return_value = "neplatné"
        dialog._seed_editor = Mock()
        dialog._input = Mock()

        with (
            patch(
                "krizovkar.gui.load_dictionary",
                return_value=TEST_DICTIONARY,
            ),
            patch("krizovkar.gui.messagebox.showerror") as show_error,
        ):
            valid = CrosswordFillDialog.validate(dialog)

        self.assertFalse(valid)
        self.assertIsNone(dialog._input)
        show_error.assert_called_once_with(
            "Křížovku nelze vygenerovat",
            "Sémě musí být celé číslo.",
            parent=dialog,
        )
        dialog._dictionary_editor.focus_set.assert_not_called()
        dialog._seed_editor.focus_set.assert_called_once_with()

    def test_builds_cli_command_for_empty_template(self) -> None:
        self.assertEqual(
            "uv run krizovkar template --empty --layout swedish "
            "--width 15 --height 10",
            _template_cli_command(
                CrosswordSettings(width=15, height=10),
                "swedish",
                "empty",
                seed=None,
            ),
        )

    def test_builds_repeatable_cli_command_for_secret_only_template(
        self,
    ) -> None:
        self.assertEqual(
            "uv run krizovkar template --randomize --seed 123 "
            "--secret TAJENKA --layout numbered --width 7 --height 6",
            _template_cli_command(
                CrosswordSettings(width=7, height=6),
                "numbered",
                "secret",
                seed=123,
                secret=SecretRequirement(words=("TAJENKA",)),
            ),
        )

    def test_builds_cli_command_with_normalized_template_secret(self) -> None:
        self.assertEqual(
            "uv run krizovkar template --randomize --seed 123 "
            "--secret 'KOMU SE NELENÍ' --layout numbered --width 15 "
            "--height 15",
            _template_cli_command(
                CrosswordSettings(width=15, height=15),
                "numbered",
                "secret",
                seed=123,
                secret=SecretRequirement(words=("KOMU", "SE", "NELENÍ")),
            ),
        )

    def test_builds_cli_command_with_selected_dictionary(self) -> None:
        self.assertEqual(
            "uv run krizovkar template --randomize --seed 123 "
            "--secret TAJENKA --dictionary '/slovníky/český slovník.json' "
            "--layout numbered --width 15 --height 15",
            _template_cli_command(
                CrosswordSettings(width=15, height=15),
                "numbered",
                "secret",
                seed=123,
                secret=SecretRequirement(words=("TAJENKA",)),
                dictionary=Path("/slovníky/český slovník.json"),
            ),
        )

    def test_builds_cli_pipeline_for_filled_template(self) -> None:
        self.assertEqual(
            "uv run krizovkar template --randomize --seed 123 "
            "--dictionary '/slovníky/český slovník.json' "
            "--layout numbered --width 7 --height 6 | uv run krizovkar "
            "fill - '/slovníky/český slovník.json' --seed 123 "
            "--replace-blocking",
            _template_cli_command(
                CrosswordSettings(width=7, height=6),
                "numbered",
                "filled",
                seed=123,
                dictionary=Path("/slovníky/český slovník.json"),
            ),
        )

    def test_template_dialog_refreshes_cli_command_from_selection(self) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._width_value = Mock()
        dialog._width_value.get.return_value = "7"
        dialog._height_value = Mock()
        dialog._height_value.get.return_value = "6"
        dialog._layout_value = Mock()
        dialog._layout_value.get.return_value = "numbered"
        dialog._content_mode_value = Mock()
        dialog._content_mode_value.get.return_value = "secret"
        dialog._seed_value = Mock()
        dialog._seed_value.get.return_value = "123"
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = "Tajenka"
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = ""
        dialog._cli_command_value = Mock()

        TemplateGenerationDialog._refresh_cli_command(dialog)

        dialog._cli_command_value.set.assert_called_once_with(
            "uv run krizovkar template --randomize --seed 123 "
            "--secret TAJENKA --layout numbered --width 7 --height 6"
        )

    def test_template_dialog_explains_invalid_cli_selection(self) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._width_value = Mock()
        dialog._width_value.get.return_value = "sedm"
        dialog._height_value = Mock()
        dialog._height_value.get.return_value = "6"
        dialog._layout_value = Mock()
        dialog._layout_value.get.return_value = "numbered"
        dialog._content_mode_value = Mock()
        dialog._content_mode_value.get.return_value = "empty"
        dialog._cli_command_value = Mock()

        TemplateGenerationDialog._refresh_cli_command(dialog)

        dialog._cli_command_value.set.assert_called_once_with(
            "Příkaz bude dostupný po opravě nastavení."
        )

    def test_template_dialog_toggles_cli_command_frame(self) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._cli_visible_value = Mock()
        dialog._cli_visible_value.get.side_effect = (True, False)
        dialog._cli_command_frame = Mock()
        dialog._refresh_cli_command = Mock()

        TemplateGenerationDialog._toggle_cli_command(dialog)
        TemplateGenerationDialog._toggle_cli_command(dialog)

        dialog._refresh_cli_command.assert_called_once_with()
        dialog._cli_command_frame.pack.assert_called_once_with(
            fill="x",
            padx=16,
            pady=(0, 16),
        )
        dialog._cli_command_frame.pack_forget.assert_called_once_with()

    def test_template_dialog_builds_wrapped_cli_text_below_buttons(
        self,
    ) -> None:
        dialog = Mock()
        buttons = Mock()
        cli_frame = Mock()
        cli_text = Mock()
        cli_toggle = Mock()
        create_button = Mock()
        cancel_button = Mock()
        visible_value = Mock()

        with (
            patch("krizovkar.gui.ttk.Frame", return_value=buttons),
            patch("krizovkar.gui.ttk.LabelFrame", return_value=cli_frame),
            patch(
                "krizovkar.gui.tk.Text",
                return_value=cli_text,
            ) as text,
            patch(
                "krizovkar.gui.ttk.Checkbutton",
                return_value=cli_toggle,
            ) as checkbutton,
            patch(
                "krizovkar.gui.ttk.Button",
                side_effect=(create_button, cancel_button),
            ),
            patch(
                "krizovkar.gui.tk.BooleanVar",
                return_value=visible_value,
            ),
        ):
            TemplateGenerationDialog.buttonbox(dialog)

        checkbutton.assert_called_once_with(
            buttons,
            text="CLI",
            variable=visible_value,
            command=dialog._toggle_cli_command,
            style="Toolbutton",
        )
        cli_toggle.pack.assert_called_once_with(side="left")
        text.assert_called_once_with(
            cli_frame,
            height=3,
            width=1,
            wrap="word",
            font="TkFixedFont",
            state="disabled",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            background=dialog.cget.return_value,
        )
        cli_text.grid.assert_called_once_with(row=0, column=0, sticky="ew")
        cli_frame.columnconfigure.assert_called_once_with(0, weight=1)
        dialog._cli_command_value.trace_add.assert_called_once_with(
            "write",
            dialog._update_cli_command_text,
        )
        dialog._update_cli_command_text.assert_called_once_with()

    def test_template_dialog_updates_copyable_cli_text(self) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._cli_command_text = Mock()
        dialog._cli_command_value = Mock()
        dialog._cli_command_value.get.return_value = "uv run krizovkar template"

        TemplateGenerationDialog._update_cli_command_text(dialog)

        dialog._cli_command_text.configure.assert_has_calls(
            (call(state="normal"), call(state="disabled"))
        )
        dialog._cli_command_text.delete.assert_called_once_with("1.0", "end")
        dialog._cli_command_text.insert.assert_called_once_with(
            "1.0",
            "uv run krizovkar template",
        )

    def test_template_dialog_shows_generation_controls_for_nonempty_content(
        self,
    ) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._content_mode_value = Mock()
        dialog._content_mode_value.get.side_effect = ("empty", "secret")
        dialog._generation_controls = Mock()

        TemplateGenerationDialog._update_generation_controls(dialog)
        TemplateGenerationDialog._update_generation_controls(dialog)

        dialog._generation_controls.grid_remove.assert_called_once_with()
        dialog._generation_controls.grid.assert_called_once_with()

    def test_template_generation_entries_have_the_same_width(self) -> None:
        parent = Mock()
        seed_value = Mock()
        secret_value = Mock()
        seed_editor = Mock()
        secret_editor = Mock()

        with patch(
            "krizovkar.gui.ttk.Entry",
            side_effect=(seed_editor, secret_editor),
        ) as entry_type:
            first = _create_generation_entry(parent, seed_value, row=0)
            second = _create_generation_entry(parent, secret_value, row=1)

        self.assertIs(seed_editor, first)
        self.assertIs(secret_editor, second)
        self.assertEqual(
            [
                call(parent, width=22, textvariable=seed_value),
                call(parent, width=22, textvariable=secret_value),
            ],
            entry_type.call_args_list,
        )
        seed_editor.grid.assert_called_once_with(
            row=0,
            column=1,
            sticky="ew",
            padx=(8, 0),
        )
        secret_editor.grid.assert_called_once_with(
            row=1,
            column=1,
            sticky="ew",
            padx=(8, 0),
            pady=(8, 0),
        )

    def test_template_dialog_width_fits_generation_controls(
        self,
    ) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._generation_controls = Mock()
        dialog._generation_controls.winfo_reqwidth.return_value = 289
        dialog._generation_controls.winfo_reqheight.return_value = 96
        shorter_child = Mock()
        shorter_child.winfo_reqwidth.return_value = 239
        longest_child = Mock()
        longest_child.winfo_reqwidth.return_value = 263
        master = Mock()
        master.winfo_children.return_value = (
            shorter_child,
            dialog._generation_controls,
            longest_child,
        )

        dialog._fit_generation_controls_width(master)

        master.update_idletasks.assert_called_once_with()
        master.columnconfigure.assert_called_once_with(0, minsize=313)
        dialog._generation_controls.configure.assert_called_once_with(
            width=289,
            height=96,
        )
        dialog._generation_controls.grid_propagate.assert_called_once_with(
            False
        )

    def test_template_dialog_validates_secret_only_content(self) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._width_value = Mock()
        dialog._width_value.get.return_value = "7"
        dialog._height_value = Mock()
        dialog._height_value.get.return_value = "6"
        dialog._layout_value = Mock()
        dialog._layout_value.get.return_value = "numbered"
        dialog._content_mode_value = Mock()
        dialog._content_mode_value.get.return_value = "secret"
        dialog._seed_value = Mock()
        dialog._seed_value.get.return_value = "123"
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = "Komu se nelení"
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = ""
        dialog._width_editor = Mock()
        dialog._new_template = None
        template = create_blank_template(CrosswordSettings(3, 3), "numbered")

        with (
            patch("krizovkar.gui.load_dictionary") as load,
            patch(
                "krizovkar.gui.create_initial_crossword",
                return_value=template,
            ) as create_crossword,
        ):
            valid = TemplateGenerationDialog.validate(dialog)
            TemplateGenerationDialog.apply(dialog)

        self.assertTrue(valid)
        load.assert_not_called()
        create_crossword.assert_called_once_with(
            CrosswordSettings(width=7, height=6),
            "numbered",
            "secret",
            seed=123,
            secret=SecretRequirement(words=("KOMU", "SE", "NELENÍ")),
            dictionary=None,
        )
        self.assertEqual(
            NewTemplateResult(
                template,
                "numbered",
                "generated",
                CrosswordSettings(7, 6),
                None,
            ),
            dialog.result,
        )

    def test_template_dialog_ignores_hidden_generation_values_for_empty_template(
        self,
    ) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._width_value = Mock()
        dialog._width_value.get.return_value = "4"
        dialog._height_value = Mock()
        dialog._height_value.get.return_value = "3"
        dialog._layout_value = Mock()
        dialog._layout_value.get.return_value = "swedish"
        dialog._content_mode_value = Mock()
        dialog._content_mode_value.get.return_value = "empty"
        dialog._seed_value = Mock()
        dialog._seed_value.get.return_value = "neplatné"
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = "Tajenka 1"
        dialog._width_editor = Mock()
        dialog._new_template = None
        template = create_empty_template(CrosswordSettings(4, 3), "swedish")

        with patch(
            "krizovkar.gui.create_initial_crossword",
            return_value=template,
        ) as create_crossword:
            valid = TemplateGenerationDialog.validate(dialog)

        self.assertTrue(valid)
        create_crossword.assert_called_once_with(
            CrosswordSettings(width=4, height=3),
            "swedish",
            "empty",
            seed=None,
            secret=None,
            dictionary=None,
        )

    def test_template_dialog_requires_secret_for_secret_only_content(
        self,
    ) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._width_value = Mock()
        dialog._width_value.get.return_value = "7"
        dialog._height_value = Mock()
        dialog._height_value.get.return_value = "6"
        dialog._layout_value = Mock()
        dialog._layout_value.get.return_value = "numbered"
        dialog._content_mode_value = Mock()
        dialog._content_mode_value.get.return_value = "secret"
        dialog._seed_value = Mock()
        dialog._seed_value.get.return_value = "123"
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = "  "
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = ""
        dialog._dictionary_editor = Mock()
        dialog._secret_editor = Mock()
        dialog._width_editor = Mock()
        dialog._new_template = Mock()

        with (
            patch("krizovkar.gui.create_initial_crossword") as create,
            patch("krizovkar.gui.messagebox.showerror") as show_error,
        ):
            valid = TemplateGenerationDialog.validate(dialog)

        self.assertFalse(valid)
        self.assertIsNone(dialog._new_template)
        show_error.assert_called_once_with(
            "Křížovku nelze vytvořit",
            "Vyplňte tajenku.",
            parent=dialog,
        )
        create.assert_not_called()
        dialog._secret_editor.focus_set.assert_called_once_with()
        dialog._dictionary_editor.focus_set.assert_not_called()

    def test_template_dialog_requires_dictionary_for_filled_content(
        self,
    ) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._width_value = Mock()
        dialog._width_value.get.return_value = "7"
        dialog._height_value = Mock()
        dialog._height_value.get.return_value = "6"
        dialog._layout_value = Mock()
        dialog._layout_value.get.return_value = "numbered"
        dialog._content_mode_value = Mock()
        dialog._content_mode_value.get.return_value = "filled"
        dialog._seed_value = Mock()
        dialog._seed_value.get.return_value = "123"
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = ""
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = "  "
        dialog._dictionary_editor = Mock()
        dialog._secret_editor = Mock()
        dialog._width_editor = Mock()
        dialog._new_template = Mock()

        with (
            patch("krizovkar.gui.create_initial_crossword") as create,
            patch("krizovkar.gui.messagebox.showerror") as show_error,
        ):
            valid = TemplateGenerationDialog.validate(dialog)

        self.assertFalse(valid)
        self.assertIsNone(dialog._new_template)
        show_error.assert_called_once_with(
            "Křížovku nelze vytvořit",
            "Vyberte slovník.",
            parent=dialog,
        )
        create.assert_not_called()
        dialog._dictionary_editor.focus_set.assert_called_once_with()
        dialog._secret_editor.focus_set.assert_not_called()

    def test_template_dialog_loads_dictionary_for_filled_content(self) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._width_value = Mock()
        dialog._width_value.get.return_value = "7"
        dialog._height_value = Mock()
        dialog._height_value.get.return_value = "6"
        dialog._layout_value = Mock()
        dialog._layout_value.get.return_value = "numbered"
        dialog._content_mode_value = Mock()
        dialog._content_mode_value.get.return_value = "filled"
        dialog._seed_value = Mock()
        dialog._seed_value.get.return_value = "123"
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = "Tajenka"
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = "slovník.json"
        dialog._dictionary_editor = Mock()
        dialog._width_editor = Mock()
        dialog._new_template = None
        template = create_blank_template(CrosswordSettings(3, 3), "numbered")

        with (
            patch(
                "krizovkar.gui.load_dictionary",
                return_value=TEST_DICTIONARY,
            ) as load,
            patch(
                "krizovkar.gui.create_initial_crossword",
                return_value=template,
            ) as create_crossword,
        ):
            valid = TemplateGenerationDialog.validate(dialog)

        self.assertTrue(valid)
        load.assert_called_once_with(Path("slovník.json"))
        create_crossword.assert_called_once_with(
            CrosswordSettings(width=7, height=6),
            "numbered",
            "filled",
            seed=123,
            secret=SecretRequirement(words=("TAJENKA",)),
            dictionary=TEST_DICTIONARY,
        )
        dialog._dictionary_editor.focus_set.assert_not_called()

    def test_template_dialog_keeps_invalid_settings_open(self) -> None:
        dialog = TemplateGenerationDialog.__new__(TemplateGenerationDialog)
        dialog._width_value = Mock()
        dialog._width_value.get.return_value = "2"
        dialog._height_value = Mock()
        dialog._height_value.get.return_value = "2"
        dialog._layout_value = Mock()
        dialog._layout_value.get.return_value = "swedish"
        dialog._content_mode_value = Mock()
        dialog._content_mode_value.get.return_value = "secret"
        dialog._seed_value = Mock()
        dialog._seed_value.get.return_value = "123"
        dialog._secret_value = Mock()
        dialog._secret_value.get.return_value = "Tajenka"
        dialog._dictionary_value = Mock()
        dialog._dictionary_value.get.return_value = ""
        dialog._dictionary_editor = Mock()
        dialog._width_editor = Mock()
        dialog._new_template = Mock()

        with (
            patch(
                "krizovkar.gui.create_initial_crossword",
                side_effect=GuiInputError("rozměr nelze rozdělit"),
            ),
            patch("krizovkar.gui.messagebox.showerror") as show_error,
        ):
            valid = TemplateGenerationDialog.validate(dialog)

        self.assertFalse(valid)
        self.assertIsNone(dialog._new_template)
        show_error.assert_called_once_with(
            "Křížovku nelze vytvořit",
            "rozměr nelze rozdělit",
            parent=dialog,
        )
        dialog._width_editor.focus_set.assert_called_once_with()

    def test_creates_empty_swedish_template_without_internal_dividers(
        self,
    ) -> None:
        crossword = create_empty_template(
            CrosswordSettings(width=4, height=3),
            "swedish",
        )

        cells = tuple(cell for row in crossword.grid.cells for cell in row)
        self.assertEqual(
            6,
            sum(isinstance(cell, LetterCellRole) for cell in cells),
        )
        self.assertEqual(
            5,
            sum(isinstance(cell, LegendCellRole) for cell in cells),
        )
        self.assertEqual(
            1,
            sum(isinstance(cell, EmptyCellRole) for cell in cells),
        )
        self.assertEqual(5, len(crossword.slots))
        self.assertTrue(
            all(slot.clue_placement == "inline" for slot in crossword.slots)
        )
        dump_crossword_document(crossword, StringIO())

    def test_creates_empty_numbered_template_without_internal_dividers(
        self,
    ) -> None:
        crossword = create_empty_template(
            CrosswordSettings(width=4, height=3),
            "numbered",
        )

        self.assertTrue(
            all(
                isinstance(cell, LetterCellRole)
                for row in crossword.grid.cells
                for cell in row
            )
        )
        self.assertEqual(7, len(crossword.slots))
        self.assertEqual(
            (4, 4, 4, 3, 3, 3, 3),
            tuple(slot.length for slot in crossword.slots),
        )
        self.assertTrue(
            all(slot.clue_placement == "external" for slot in crossword.slots)
        )
        dump_crossword_document(crossword, StringIO())

    def test_rejects_one_cell_empty_swedish_template(self) -> None:
        with self.assertRaisesRegex(GuiInputError, "alespoň dva"):
            create_empty_template(CrosswordSettings(1, 1), "swedish")

    def test_generated_template_uses_repeatable_pseudorandom_layout(self) -> None:
        settings = CrosswordSettings(width=15, height=10)

        first = create_new_template(settings, "swedish", "generated", seed=1)
        repeated = create_new_template(
            settings,
            "swedish",
            "generated",
            seed=1,
        )
        second = create_new_template(settings, "swedish", "generated", seed=2)

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, second)

    def test_generated_template_places_multipart_secret_between_words(
        self,
    ) -> None:
        secret = parse_template_secret("Komu se nelení")
        assert secret is not None

        crossword = create_new_template(
            CrosswordSettings(width=15, height=15),
            "swedish",
            "generated",
            seed=123,
            secret=secret,
        )

        stored = crossword.secrets[0]
        word_counts = tuple(part.word_count for part in stored.parts)
        self.assertEqual(("KOMU", "SE", "NELENÍ"), stored.words)
        self.assertLessEqual(len(stored.parts), len(stored.words))
        self.assertTrue(all(count is not None for count in word_counts))
        self.assertEqual(
            len(stored.words),
            sum(count or 0 for count in word_counts),
        )
        self.assertIn(2, word_counts)

        slots = {slot.identifier: slot for slot in crossword.slots}
        expected_answers = []
        word_offset = 0
        for part_index, (part, word_count) in enumerate(
            zip(stored.parts, word_counts),
            start=1,
        ):
            self.assertIsInstance(part, CrosswordSecretSlotPart)
            assert isinstance(part, CrosswordSecretSlotPart)
            assert word_count is not None
            answer = "".join(
                stored.words[word_offset : word_offset + word_count]
            )
            word_offset += word_count
            expected_answers.append(answer)
            slot = slots[part.slot_identifier]
            self.assertEqual(answer, slot.answer)
            self.assertEqual(f"{part_index}. část tajenky", slot.clue)

        grid = create_grid_from_crossword(crossword)
        assert grid.grid.cells is not None
        for part, answer in zip(stored.parts, expected_answers):
            assert isinstance(part, CrosswordSecretSlotPart)
            slot = slots[part.slot_identifier]
            cells = tuple(
                grid.grid.cells[coordinate.row - 1][coordinate.column - 1]
                for coordinate in slot_coordinates(slot)
            )
            self.assertTrue(all(isinstance(cell, SecretCell) for cell in cells))
            self.assertEqual(answer, "".join(cell.value or "" for cell in cells))

    def test_initial_secret_content_creates_generated_template_only(
        self,
    ) -> None:
        settings = CrosswordSettings(width=7, height=6)
        secret = SecretRequirement(words=("TAJENKA",))
        template = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )

        with (
            patch(
                "krizovkar.gui.create_new_template",
                return_value=template,
            ) as create_template,
            patch("krizovkar.gui.generate_filled_crossword") as fill,
        ):
            result = create_initial_crossword(
                settings,
                "numbered",
                "secret",
                seed=123,
                secret=secret,
                dictionary=TEST_DICTIONARY,
            )

        self.assertIs(template, result)
        create_template.assert_called_once_with(
            settings,
            "numbered",
            "generated",
            seed=123,
            secret=secret,
            dictionary=TEST_DICTIONARY,
        )
        fill.assert_not_called()

    def test_initial_filled_content_generates_all_words(self) -> None:
        settings = CrosswordSettings(width=7, height=6)
        template = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        filled = _filled_numbered_crossword()

        with (
            patch(
                "krizovkar.gui.create_new_template",
                return_value=template,
            ) as create_template,
            patch(
                "krizovkar.gui.generate_filled_crossword",
                return_value=filled,
            ) as fill,
        ):
            result = create_initial_crossword(
                settings,
                "numbered",
                "filled",
                seed=123,
                dictionary=TEST_DICTIONARY,
            )

        self.assertIs(filled, result)
        create_template.assert_called_once_with(
            settings,
            "numbered",
            "generated",
            seed=123,
            secret=None,
            dictionary=TEST_DICTIONARY,
        )
        fill.assert_called_once_with(template, TEST_DICTIONARY, seed=123)

    def test_initial_filled_content_returns_complete_crossword(self) -> None:
        answers = ("ABC", "DEF", "GHI", "ADG", "BEH", "CFI")
        dictionary = CrosswordDictionary(
            entries=tuple(
                DictionaryEntry(answer=answer, clues=(answer,))
                for answer in answers
            )
        )

        crossword = create_initial_crossword(
            CrosswordSettings(width=3, height=3),
            "numbered",
            "filled",
            seed=123,
            dictionary=dictionary,
        )

        self.assertTrue(
            all(
                slot.answer is not None and slot.clue is not None
                for slot in crossword.slots
            )
        )
        self.assertEqual(set(answers), {slot.answer for slot in crossword.slots})

    def test_recognizes_unchanged_empty_template_after_opening(self) -> None:
        empty = create_empty_template(CrosswordSettings(4, 3), "swedish")
        generated = create_blank_template(CrosswordSettings(9, 9), "swedish")

        self.assertEqual("empty", _template_creation_mode(empty, "swedish"))
        self.assertEqual(
            "generated",
            _template_creation_mode(generated, "swedish"),
        )

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
            any(slot.clue_placement == "inline" for slot in crossword.slots)
        )

    def test_creates_numbered_template_before_words(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=7, height=6),
            "numbered",
        )

        self.assertTrue(crossword.slots)
        self.assertTrue(
            all(slot.clue_placement == "external" for slot in crossword.slots)
        )

    def test_changes_letter_to_legend_and_splits_crossing_slots(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        coordinate = Coordinate(row=2, column=2)

        changed = set_crossword_cell_role(crossword, coordinate, "legend")

        self.assertIsInstance(changed.grid.cells[1][1], LegendCellRole)
        following = tuple(
            slot
            for slot in changed.slots
            if slot.inline_clue_position == coordinate
        )
        self.assertEqual(
            {"horizontal", "vertical"},
            {slot.direction for slot in following},
        )
        self.assertTrue(
            all(
                coordinate not in slot_coordinates(slot)
                for slot in changed.slots
            )
        )

    def test_changing_created_legend_back_to_letter_rejoins_slots(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        coordinate = Coordinate(row=2, column=2)
        with_legend = set_crossword_cell_role(
            crossword,
            coordinate,
            "legend",
        )

        restored = set_crossword_cell_role(
            with_legend,
            coordinate,
            "letter",
        )

        self.assertEqual(crossword, restored)
        self.assertIsInstance(restored.grid.cells[1][1], LetterCellRole)

    def test_changes_letter_to_empty_and_back(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        coordinate = Coordinate(row=2, column=2)

        without_cell = set_crossword_cell_role(
            crossword,
            coordinate,
            "empty",
        )

        self.assertIsInstance(without_cell.grid.cells[1][1], EmptyCellRole)
        self.assertTrue(
            all(
                coordinate not in slot_coordinates(slot)
                for slot in without_cell.slots
            )
        )

        restored = set_crossword_cell_role(
            without_cell,
            coordinate,
            "letter",
        )

        self.assertEqual(crossword, restored)

    def test_changes_selected_letters_to_secret_cells_and_back(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        coordinates = (Coordinate(1, 1), Coordinate(2, 2))

        changed = set_crossword_cells_role(
            crossword,
            coordinates,
            "secret",
        )

        self.assertEqual(1, len(changed.secrets))
        part = changed.secrets[0].parts[0]
        self.assertIsInstance(part, CrosswordSecretCellsPart)
        assert isinstance(part, CrosswordSecretCellsPart)
        self.assertEqual(coordinates, part.cells)
        grid = create_grid_from_crossword(changed)
        self.assertIsInstance(grid.grid.cells[0][0], SecretCell)
        self.assertIsInstance(grid.grid.cells[1][1], SecretCell)
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview._crossword = grid
        self.assertEqual(
            "secret",
            preview._editable_cell_role_at(Coordinate(1, 1)),
        )

        one_removed = set_crossword_cell_role(
            changed,
            coordinates[0],
            "letter",
        )
        one_removed_grid = create_grid_from_crossword(one_removed)
        self.assertIsInstance(one_removed_grid.grid.cells[0][0], LetterCell)
        self.assertIsInstance(one_removed_grid.grid.cells[1][1], SecretCell)
        restored = set_crossword_cell_role(
            one_removed,
            coordinates[1],
            "letter",
        )
        self.assertEqual(crossword, restored)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "tajenkova-pole.yaml"
            write_crossword_document(changed, output)
            self.assertEqual(changed, load_crossword_document(output))

    def test_changes_empty_cell_to_secret_and_rejoins_slots(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        coordinate = Coordinate(2, 2)
        without_cell = set_crossword_cell_role(crossword, coordinate, "empty")

        changed = set_crossword_cell_role(
            without_cell,
            coordinate,
            "secret",
        )

        self.assertIsInstance(changed.grid.cells[1][1], LetterCellRole)
        self.assertEqual(crossword.slots, changed.slots)
        self.assertIsInstance(
            create_grid_from_crossword(changed).grid.cells[1][1],
            SecretCell,
        )

    def test_empty_cell_does_not_create_numbered_inline_slot_tails(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=12, height=10),
            "swedish",
        )

        changed = set_crossword_cell_role(
            crossword,
            Coordinate(2, 3),
            "empty",
        )
        grid = create_grid_from_crossword(changed)

        right = grid.grid.cells[1][3]
        below = grid.grid.cells[2][2]
        self.assertIsInstance(right, LetterCell)
        self.assertIsInstance(below, LetterCell)
        self.assertIsNone(right.number)
        self.assertIsNone(below.number)
        self.assertEqual((), right.bars)
        self.assertEqual((), below.bars)
        self.assertFalse(
            any(
                slot.start in {Coordinate(2, 4), Coordinate(3, 3)}
                and slot.clue_placement == "external"
                for slot in changed.slots
            )
        )

    def test_virtual_slot_start_splits_and_rejoins_inline_slot(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=7, height=6),
            "swedish",
        )
        original = next(
            slot
            for slot in crossword.slots
            if slot.direction == "horizontal" and slot.length >= 3
        )
        coordinate = slot_coordinates(original)[2]

        split = set_crossword_cell_slot_start(
            crossword,
            coordinate,
            "horizontal",
            True,
        )

        created = next(
            slot
            for slot in split.slots
            if slot.direction == "horizontal" and slot.start == coordinate
        )
        shortened = next(
            slot for slot in split.slots if slot.identifier == original.identifier
        )
        self.assertEqual("external", created.clue_placement)
        self.assertEqual(2, shortened.length)
        self.assertEqual(original.length - 2, created.length)
        grid = create_grid_from_crossword(split)
        start_cell = grid.grid.cells[coordinate.row - 1][coordinate.column - 1]
        preceding_cell = grid.grid.cells[
            coordinate.row - 1
        ][coordinate.column - 2]
        self.assertIsInstance(start_cell, LetterCell)
        self.assertIsInstance(preceding_cell, LetterCell)
        self.assertIsNotNone(start_cell.number)
        self.assertIn("right", preceding_cell.bars)

        restored = set_crossword_cell_slot_start(
            split,
            coordinate,
            "horizontal",
            False,
        )

        self.assertEqual(crossword, restored)

    def test_virtual_slot_starts_end_before_following_start(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=12, height=10),
            "swedish",
        )
        crossword = set_crossword_cell_role(
            crossword,
            Coordinate(2, 3),
            "empty",
        )

        changed = set_crossword_cells_slot_start(
            crossword,
            (Coordinate(2, 4), Coordinate(2, 6)),
            "horizontal",
            True,
        )

        starts = {
            slot.start: slot
            for slot in changed.slots
            if slot.direction == "horizontal"
            and slot.start in {Coordinate(2, 4), Coordinate(2, 6)}
        }
        self.assertEqual(2, starts[Coordinate(2, 4)].length)
        self.assertEqual(2, starts[Coordinate(2, 6)].length)

    def test_virtual_slot_starts_support_both_directions(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        coordinate = Coordinate(2, 2)

        changed = set_crossword_cell_slot_start(
            crossword,
            coordinate,
            "horizontal",
            True,
        )
        changed = set_crossword_cell_slot_start(
            changed,
            coordinate,
            "vertical",
            True,
        )

        self.assertEqual(
            {"horizontal", "vertical"},
            {
                slot.direction
                for slot in changed.slots
                if slot.start == coordinate
                and slot.clue_placement == "external"
            },
        )
        grid = create_grid_from_crossword(changed)
        assert grid.grid.cells is not None
        start_cell = grid.grid.cells[1][1]
        self.assertIsInstance(start_cell, LetterCell)
        assert isinstance(start_cell, LetterCell)
        self.assertIsNone(start_cell.number)
        self.assertEqual(2, len(start_cell.numbers))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "virtualni-zacatky.yaml"
            write_crossword_document(changed, output)
            self.assertEqual(changed, load_crossword_document(output))

    def test_changes_filled_legend_to_empty_and_back(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=7, height=6),
            "swedish",
        )
        slot = next(
            slot
            for slot in crossword.slots
            if slot.clue_placement == "inline"
        )
        crossword = fill_crossword_slot(
            crossword,
            slot.identifier,
            "A" * slot.length,
            "Nápověda",
        )
        coordinate = slot.inline_clue_position
        assert coordinate is not None

        without_legend = set_crossword_cell_role(
            crossword,
            coordinate,
            "empty",
        )

        preserved = next(
            item
            for item in without_legend.slots
            if item.identifier == slot.identifier
        )
        self.assertIsInstance(
            without_legend.grid.cells[coordinate.row - 1][coordinate.column - 1],
            EmptyCellRole,
        )
        self.assertEqual("external", preserved.clue_placement)
        self.assertIsNone(preserved.inline_clue_position)
        self.assertEqual("A" * slot.length, preserved.answer)
        self.assertEqual("Nápověda", preserved.clue)

        restored = set_crossword_cell_role(
            without_legend,
            coordinate,
            "legend",
        )

        self.assertEqual(crossword, restored)

    def test_changes_multiple_selected_cells_to_legends_at_once(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=4, height=4),
            "numbered",
        )
        coordinates = (Coordinate(2, 2), Coordinate(3, 3))

        changed = set_crossword_cells_role(
            crossword,
            coordinates,
            "legend",
        )

        for coordinate in coordinates:
            with self.subTest(coordinate=coordinate):
                self.assertIsInstance(
                    changed.grid.cells[coordinate.row - 1][coordinate.column - 1],
                    LegendCellRole,
                )
                self.assertTrue(
                    any(
                        slot.inline_clue_position == coordinate
                        for slot in changed.slots
                    )
                )

    def test_changes_multiple_selected_cells_to_empty_at_once(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=4, height=4),
            "numbered",
        )
        coordinates = (Coordinate(2, 2), Coordinate(3, 3))

        changed = set_crossword_cells_role(
            crossword,
            coordinates,
            "empty",
        )

        for coordinate in coordinates:
            with self.subTest(coordinate=coordinate):
                self.assertIsInstance(
                    changed.grid.cells[coordinate.row - 1][coordinate.column - 1],
                    EmptyCellRole,
                )
                self.assertTrue(
                    all(
                        coordinate not in slot_coordinates(slot)
                        for slot in changed.slots
                    )
                )

    def test_multiple_cell_role_change_empties_orphaned_legend(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=12, height=10),
            "swedish",
        )
        coordinates = (
            Coordinate(2, 3),
            Coordinate(3, 4),
            Coordinate(4, 3),
            Coordinate(5, 3),
        )

        changed = set_crossword_cells_role(
            crossword,
            coordinates,
            "legend",
        )

        self.assertIsInstance(changed.grid.cells[0][2], EmptyCellRole)
        for coordinate in coordinates:
            with self.subTest(coordinate=coordinate):
                self.assertIsInstance(
                    changed.grid.cells[coordinate.row - 1][coordinate.column - 1],
                    LegendCellRole,
                )

    def test_multiple_cell_role_change_is_atomic_on_error(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )

        with self.assertRaisesRegex(
            GuiInputError,
            "Pole v řádku 3, sloupci 3",
        ):
            set_crossword_cells_role(
                crossword,
                (Coordinate(2, 2), Coordinate(3, 3)),
                "legend",
            )

        self.assertTrue(
            all(
                isinstance(cell, LetterCellRole)
                for row in crossword.grid.cells
                for cell in row
            )
        )

    def test_cell_role_change_preserves_unaffected_filled_slot(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        crossword = fill_crossword_slot(
            crossword,
            "h1",
            "ABC",
            "První řádek",
        )
        crossword = fill_crossword_slot(
            crossword,
            "h2",
            "DEF",
            "Druhý řádek",
        )

        changed = set_crossword_cell_role(
            crossword,
            Coordinate(row=2, column=2),
            "legend",
        )

        slots = {slot.identifier: slot for slot in changed.slots}
        self.assertEqual("ABC", slots["h1"].answer)
        self.assertEqual("První řádek", slots["h1"].clue)
        self.assertIsNone(slots["h2"].answer)
        self.assertIsNone(slots["h2"].clue)

    def test_rejects_legend_without_following_slot(self) -> None:
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )

        with self.assertRaisesRegex(
            GuiInputError,
            "Legenda musí mít bezprostředně napravo nebo pod sebou",
        ):
            set_crossword_cell_role(
                crossword,
                Coordinate(row=3, column=3),
                "legend",
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
        window._preview_cell_role_changed = Mock()
        window._preview_cell_slot_changed = Mock()
        window._template_layout = "swedish"
        window._template_creation_mode = "generated"
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
        preview.set_cell_role_handler.assert_called_once_with(
            window._preview_cell_role_changed
        )
        preview.set_cell_slot_handler.assert_called_once_with(
            window._preview_cell_slot_changed
        )
        preview.set_grid_resize_handler.assert_called_once_with(
            window._preview_grid_resized,
            minimum_dimension=4,
            maximum_dimension=50,
        )
        spinbox_type.assert_not_called()

    def test_crossword_preview_binds_shift_click_and_drag_to_range_selection(
        self,
    ) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview.bind = Mock()
        preview._build_cell_role_menu = Mock()

        with patch("krizovkar.gui.tk.Canvas.__init__", return_value=None):
            CrosswordPreview.__init__(preview, Mock())

        preview.bind.assert_has_calls(
            [
                call("<Shift-Button-1>", preview._select_cell_role_range),
                call("<Shift-B1-Motion>", preview._select_cell_role_range),
            ],
            any_order=True,
        )

    def test_crossword_preview_cell_role_menu_offers_all_roles(self) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview._cell_role_variable = "cell_role"
        preview._cell_slot_variables = {
            "horizontal": "slot_horizontal",
            "vertical": "slot_vertical",
        }
        preview._choose_cell_role = Mock()
        preview._choose_cell_slot = Mock()
        menu = Mock()

        with patch("krizovkar.gui.tk.Menu", return_value=menu) as menu_type:
            created = preview._build_cell_role_menu()

        self.assertIs(menu, created)
        menu_type.assert_called_once_with(preview, tearoff=False)
        items = menu.add_radiobutton.call_args_list
        self.assertEqual(
            ["Písmeno", "Tajenka", "Legenda", "Prázdné"],
            [item.kwargs["label"] for item in items],
        )
        self.assertEqual(
            ["letter", "secret", "legend", "empty"],
            [item.kwargs["value"] for item in items],
        )
        self.assertTrue(
            all(item.kwargs["variable"] == "cell_role" for item in items)
        )
        items[1].kwargs["command"]()
        preview._choose_cell_role.assert_called_once_with("secret")
        slot_items = menu.add_checkbutton.call_args_list
        self.assertEqual(
            ["Heslo →", "Heslo ↓"],
            [item.kwargs["label"] for item in slot_items],
        )
        self.assertEqual(
            ["slot_horizontal", "slot_vertical"],
            [item.kwargs["variable"] for item in slot_items],
        )
        slot_items[0].kwargs["command"]()
        preview._choose_cell_slot.assert_called_once_with("horizontal")

    def test_crossword_preview_draws_both_directional_numbers(self) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview.create_text = Mock()

        preview._draw_cell_numbers(
            (1, 2),
            x1=10,
            y1=20,
            x2=40,
            cell_size=30,
        )

        preview.create_text.assert_has_calls(
            [
                call(
                    12,
                    21,
                    text="1→",
                    anchor="nw",
                    fill=preview._LETTER_COLOR,
                    font=("TkDefaultFont", 5),
                ),
                call(
                    38,
                    21,
                    text="2↓",
                    anchor="ne",
                    fill=preview._LETTER_COLOR,
                    font=("TkDefaultFont", 5),
                ),
            ]
        )

    def test_crossword_preview_slot_choice_calls_handler(self) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview._context_menu_coordinates = (Coordinate(2, 3),)
        preview._cell_slot_variables = {
            "horizontal": "slot_horizontal",
            "vertical": "slot_vertical",
        }
        preview._cell_role_menu = Mock()
        preview._cell_role_menu.getvar.return_value = 1
        preview._cell_slot_handler = Mock()

        preview._choose_cell_slot("horizontal")

        preview._cell_slot_handler.assert_called_once_with(
            (Coordinate(2, 3),),
            "horizontal",
            True,
        )

    def test_crossword_preview_context_menu_targets_empty_cell(self) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview._crossword = create_grid_from_crossword(
            create_blank_template(CrosswordSettings(7, 6), "swedish")
        )
        preview._grid_geometry = (100.0, 50.0, 20.0)
        preview._cell_role_variable = "cell_role"
        preview._cell_slot_variables = {
            "horizontal": "slot_horizontal",
            "vertical": "slot_vertical",
        }
        preview._cell_role_menu = Mock()
        preview._role_selected_coordinates = frozenset()
        preview._slot_starts = frozenset()
        preview._external_slot_starts = frozenset()
        preview._context_menu_coordinates = ()
        preview._redraw = Mock()
        event = Mock(x=110, y=60, x_root=210, y_root=160)

        result = preview._show_cell_role_menu(event)

        self.assertEqual("break", result)
        self.assertEqual(
            (Coordinate(1, 1),),
            preview._context_menu_coordinates,
        )
        preview._cell_role_menu.setvar.assert_any_call(
            "cell_role",
            "empty",
        )
        preview._cell_role_menu.tk_popup.assert_called_once_with(210, 160)
        preview._cell_role_menu.grab_release.assert_called_once_with()
        preview._cell_role_menu.entryconfigure.assert_has_calls(
            [
                call("Heslo →", state="disabled"),
                call("Heslo ↓", state="disabled"),
            ]
        )

    def test_crossword_preview_context_menu_targets_clicked_cell(self) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview._crossword = create_grid_from_crossword(
            create_blank_template(CrosswordSettings(3, 3), "numbered")
        )
        preview._grid_geometry = (100.0, 50.0, 20.0)
        preview._cell_role_variable = "cell_role"
        preview._cell_slot_variables = {
            "horizontal": "slot_horizontal",
            "vertical": "slot_vertical",
        }
        preview._cell_role_menu = Mock()
        preview._role_selected_coordinates = frozenset()
        slot_start = (Coordinate(2, 2), "horizontal")
        preview._slot_starts = frozenset({slot_start})
        preview._external_slot_starts = frozenset({slot_start})
        preview._context_menu_coordinates = ()
        preview._cell_role_handler = Mock()
        preview._redraw = Mock()
        event = Mock(x=130, y=80, x_root=230, y_root=180)

        result = preview._show_cell_role_menu(event)
        preview._choose_cell_role("legend")

        self.assertEqual("break", result)
        self.assertEqual(
            (Coordinate(2, 2),),
            preview._context_menu_coordinates,
        )
        preview._cell_role_menu.setvar.assert_any_call(
            "cell_role",
            "letter",
        )
        preview._cell_role_menu.setvar.assert_any_call("slot_horizontal", 1)
        preview._cell_role_menu.setvar.assert_any_call("slot_vertical", 0)
        preview._cell_role_menu.tk_popup.assert_called_once_with(230, 180)
        preview._cell_role_menu.grab_release.assert_called_once_with()
        preview._cell_role_handler.assert_called_once_with(
            (Coordinate(2, 2),),
            "legend",
        )

    def test_crossword_preview_context_menu_uses_multiple_selection(self) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview._crossword = create_grid_from_crossword(
            create_blank_template(CrosswordSettings(3, 3), "numbered")
        )
        preview._grid_geometry = (100.0, 50.0, 20.0)
        preview._cell_role_variable = "cell_role"
        preview._cell_slot_variables = {
            "horizontal": "slot_horizontal",
            "vertical": "slot_vertical",
        }
        preview._cell_role_menu = Mock()
        selected = frozenset({Coordinate(1, 1), Coordinate(2, 2)})
        preview._role_selected_coordinates = selected
        preview._slot_starts = frozenset()
        preview._external_slot_starts = frozenset()
        preview._context_menu_coordinates = ()
        preview._cell_role_handler = Mock()
        preview._redraw = Mock()
        event = Mock(x=130, y=80, x_root=230, y_root=180)

        result = preview._show_cell_role_menu(event)
        preview._choose_cell_role("legend")

        self.assertEqual("break", result)
        self.assertEqual(
            (Coordinate(1, 1), Coordinate(2, 2)),
            preview._context_menu_coordinates,
        )
        preview._cell_role_menu.setvar.assert_any_call(
            "cell_role",
            "letter",
        )
        preview._redraw.assert_not_called()
        preview._cell_role_handler.assert_called_once_with(
            (Coordinate(1, 1), Coordinate(2, 2)),
            "legend",
        )

    def test_crossword_preview_modifier_click_toggles_selected_cell(self) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview._crossword = create_grid_from_crossword(
            create_blank_template(CrosswordSettings(3, 3), "numbered")
        )
        preview._grid_geometry = (100.0, 50.0, 20.0)
        preview._role_selected_coordinates = frozenset()
        preview._context_menu_coordinates = ()
        preview._resize_edges_at = Mock(return_value=(0, 0))
        preview._redraw = Mock()
        event = Mock(x=130, y=80)

        first = preview._toggle_cell_role_selection(event)
        second = preview._toggle_cell_role_selection(event)

        self.assertEqual("break", first)
        self.assertEqual("break", second)
        self.assertEqual(frozenset(), preview._role_selected_coordinates)
        self.assertEqual(Coordinate(2, 2), preview._role_selection_anchor)
        self.assertEqual(frozenset(), preview._role_selection_base)
        self.assertEqual(2, preview._redraw.call_count)

    def test_crossword_preview_shift_click_selects_anchored_rectangle(
        self,
    ) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview._crossword = create_grid_from_crossword(
            create_blank_template(CrosswordSettings(4, 4), "numbered")
        )
        preview._grid_geometry = (100.0, 50.0, 20.0)
        retained = Coordinate(4, 4)
        anchor = Coordinate(2, 2)
        preview._role_selected_coordinates = frozenset({retained, anchor})
        preview._role_selection_anchor = anchor
        preview._role_selection_base = frozenset({retained})
        preview._context_menu_coordinates = (anchor,)
        preview._resize_edges_at = Mock(return_value=(0, 0))
        preview._redraw = Mock()

        first = preview._select_cell_role_range(Mock(x=150, y=100))
        second = preview._select_cell_role_range(Mock(x=150, y=60))

        self.assertEqual("break", first)
        self.assertEqual("break", second)
        self.assertEqual(
            frozenset(
                {
                    Coordinate(1, 2),
                    Coordinate(1, 3),
                    Coordinate(2, 2),
                    Coordinate(2, 3),
                    retained,
                }
            ),
            preview._role_selected_coordinates,
        )
        self.assertEqual(anchor, preview._role_selection_anchor)
        self.assertEqual(frozenset({retained}), preview._role_selection_base)
        self.assertEqual((), preview._context_menu_coordinates)
        self.assertEqual(2, preview._redraw.call_count)

    def test_crossword_preview_plain_click_sets_shift_selection_anchor(
        self,
    ) -> None:
        preview = CrosswordPreview.__new__(CrosswordPreview)
        preview._crossword = create_grid_from_crossword(
            create_blank_template(CrosswordSettings(3, 3), "numbered")
        )
        preview._grid_geometry = (100.0, 50.0, 20.0)
        preview._role_selection_anchor = None
        preview._role_selection_base = frozenset({Coordinate(1, 1)})
        preview._cell_click_handler = Mock()
        event = Mock(x=130, y=80)

        preview._cell_clicked(event)

        self.assertEqual(Coordinate(2, 2), preview._role_selection_anchor)
        self.assertEqual(frozenset(), preview._role_selection_base)
        preview._cell_click_handler.assert_called_once_with(Coordinate(2, 2))

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
        slots_tree.column.assert_any_call(
            "slot",
            width=60,
            minwidth=60,
            stretch=False,
            anchor="center",
        )
        slots_tree.column.assert_any_call(
            "length",
            width=60,
            minwidth=60,
            stretch=False,
            anchor="center",
        )
        slots_tree.column.assert_any_call(
            "answer",
            width=120,
            minwidth=1,
            stretch=False,
        )
        slots_tree.column.assert_any_call(
            "clue",
            width=240,
            minwidth=1,
            stretch=False,
        )
        slots_tree.bind.assert_has_calls(
            [
                call("<Configure>", window._fit_slot_table_columns),
                call("<Motion>", window._slot_table_pointer_moved),
                call("<Button-1>", window._slot_table_button_pressed),
            ]
        )

    def test_slot_table_columns_always_fit_available_width(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.slots_tree = Mock()

        window._fit_slot_table_columns(Mock(width=533))

        window.slots_tree.column.assert_has_calls(
            [
                call("answer", width=136),
                call("clue", width=273),
            ]
        )
        window.slots_tree.xview_moveto.assert_called_once_with(0)

    def test_slot_table_does_not_allow_column_resizing(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.slots_tree = Mock()
        event = Mock(x=120, y=10)
        window.slots_tree.identify_region.return_value = "separator"

        motion_result = window._slot_table_pointer_moved(event)
        button_result = window._slot_table_button_pressed(event)
        double_button_result = window._begin_slot_edit(event)

        self.assertEqual("break", motion_result)
        self.assertEqual("break", button_result)
        self.assertEqual("break", double_button_result)
        window.slots_tree.configure.assert_called_once_with(cursor="")

        window.slots_tree.identify_region.return_value = "cell"

        self.assertIsNone(window._slot_table_pointer_moved(event))
        self.assertIsNone(window._slot_table_button_pressed(event))

    def test_slot_labels_use_compact_direction_arrows(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        slots = {slot.identifier: slot for slot in window._crossword.slots}

        self.assertEqual("→ 1", window._slot_label(slots["h1"]))
        self.assertEqual("→ 5", window._slot_label(slots["h2"]))
        self.assertEqual("↓ 2", window._slot_label(slots["v1"]))

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
        window._crossword = fill_crossword_slot(
            create_blank_template(
                CrosswordSettings(3, 3),
                "numbered",
            ),
            "h1",
            "ABC",
            "",
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
                    "ABC",
                    check_crossings=True,
                ),
                call((355, 24, 360, 22), ""),
            ]
        )
        clue_editor.focus_set.assert_called_once_with()
        clue_editor.selection_range.assert_called_once_with(0, tk.END)

    def test_slot_answer_editor_validates_crossings_for_each_edit(self) -> None:
        window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        window.slots_tree = Mock()
        window._update_slot_answer_error = Mock(return_value=True)
        editor = Mock()
        editor.register.return_value = "crossing-validation"

        with (
            patch(
                "krizovkar.gui.ttk.Entry",
                return_value=editor,
            ) as entry_type,
            patch(
                "krizovkar.gui._bind_text_entry_context_menu"
            ) as bind_context_menu,
        ):
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
        editor.configure.assert_called_once_with(
            validate="key",
            validatecommand=("crossing-validation", "%P"),
        )

        validation_callback = editor.register.call_args.args[0]
        accepted = validation_callback("NOVÁ HODNOTA")

        self.assertTrue(accepted)
        window._update_slot_answer_error.assert_called_once_with(
            editor,
            "NOVÁ HODNOTA",
        )
        bind_context_menu.assert_called_once_with(editor)

    def test_inline_slot_edit_defaults_missing_clue_to_answer(self) -> None:
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
        self.assertEqual("ABC", slot.answer)
        self.assertEqual("ABC", slot.clue)
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
        window._slot_answer_editor = answer_editor

        conflicting_edit_accepted = window._update_slot_answer_error(
            answer_editor,
            "Z",
        )
        matching_edit_accepted = window._update_slot_answer_error(
            answer_editor,
            "A",
        )

        self.assertTrue(conflicting_edit_accepted)
        self.assertTrue(matching_edit_accepted)
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
        clue_editor.get.return_value = ""
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
        window._template_creation_mode = "generated"
        new_template = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )

        with patch(
            "krizovkar.gui.create_new_template",
            return_value=new_template,
        ) as create_template:
            CrosswordDocumentWindow._preview_grid_resized(window, 3, 3)

        window._save_inline_slot_edit.assert_called_once_with()
        create_template.assert_called_once_with(
            CrosswordSettings(3, 3),
            "numbered",
            "generated",
        )
        self.assertIs(new_template, window._crossword)
        self.assertEqual("numbered", window._template_layout)
        window._set_dirty.assert_called_once_with(True)
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()

    def test_preview_resize_keeps_empty_template_mode(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        window._crossword = create_empty_template(
            CrosswordSettings(4, 4),
            "swedish",
        )
        window._template_layout = "swedish"
        window._template_creation_mode = "empty"
        resized = create_empty_template(
            CrosswordSettings(5, 4),
            "swedish",
        )

        with patch(
            "krizovkar.gui.create_new_template",
            return_value=resized,
        ) as create_template:
            CrosswordDocumentWindow._preview_grid_resized(window, 5, 4)

        create_template.assert_called_once_with(
            CrosswordSettings(5, 4),
            "swedish",
            "empty",
        )
        self.assertIs(resized, window._crossword)

    def test_preview_resize_preserves_matching_document(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        template = create_blank_template(CrosswordSettings(3, 3), "numbered")
        window._crossword = template
        window._template_layout = "numbered"
        window._template_creation_mode = "generated"

        with patch("krizovkar.gui.create_new_template") as create_template:
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
        window._template_creation_mode = "generated"

        with patch(
            "krizovkar.gui.create_new_template",
            side_effect=GuiInputError("rozměr nelze rozdělit"),
        ):
            CrosswordDocumentWindow._preview_grid_resized(window, 4, 4)

        self.assertIs(template, window._crossword)
        window._show_action_error.assert_not_called()
        window._set_dirty.assert_not_called()
        window._refresh_crossword_view.assert_not_called()

    def test_preview_resize_replaces_filled_crossword_without_confirmation(
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
        window._template_creation_mode = "generated"
        new_template = create_blank_template(
            CrosswordSettings(4, 4),
            "numbered",
        )

        with (
            patch("krizovkar.gui.messagebox.askyesno") as ask,
            patch(
                "krizovkar.gui.create_new_template",
                return_value=new_template,
            ) as create_template,
        ):
            CrosswordDocumentWindow._preview_grid_resized(window, 4, 4)

        ask.assert_not_called()
        create_template.assert_called_once_with(
            CrosswordSettings(4, 4),
            "numbered",
            "generated",
        )
        self.assertIs(new_template, window._crossword)
        window._set_dirty.assert_called_once_with(True)

    def test_menu_action_generates_secret_as_one_undoable_change(self) -> None:
        original = create_empty_template(
            CrosswordSettings(4, 4),
            "numbered",
        )
        requirement = SecretRequirement(words=("ABC",))
        generated = create_new_template(
            CrosswordSettings(7, 7),
            "numbered",
            "generated",
            secret=requirement,
        )
        result = SecretGenerationResult(
            document=generated,
            strategy="changed_size",
        )
        window = _document_history_window(original)
        window.root = Mock()
        window._template_creation_mode = "empty"

        with (
            patch("krizovkar.gui.SecretGenerationDialog") as dialog_type,
            patch(
                "krizovkar.gui.generate_secret_in_crossword",
                return_value=result,
            ) as generate_secret,
            patch("krizovkar.gui.messagebox.askyesno") as ask,
            patch.object(
                window,
                "_set_dirty",
                wraps=window._set_dirty,
            ) as set_dirty,
        ):
            dialog_type.return_value.result = SecretGenerationInput(
                requirement=requirement,
                dictionary=TEST_DICTIONARY,
            )
            CrosswordDocumentWindow.generate_crossword_secret(window)

        dialog_type.assert_called_once_with(window.root)
        generate_secret.assert_called_once_with(
            original,
            requirement,
            layout="numbered",
            dictionary=TEST_DICTIONARY,
            maximum_width=50,
            maximum_height=50,
        )
        ask.assert_not_called()
        self.assertEqual(generated, window._crossword)
        self.assertEqual("generated", window._template_creation_mode)
        self.assertEqual(
            generated.secrets[-1].parts[0].slot_identifier,
            window._selected_slot_identifier,
        )
        set_dirty.assert_called_once_with(True)
        self.assertEqual(2, len(window._history))
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()
        window.root.configure.assert_has_calls(
            [call(cursor="watch"), call(cursor="")]
        )

        self.assertTrue(window.undo_document())
        self.assertEqual(original, window._crossword)
        self.assertEqual("empty", window._template_creation_mode)

    def test_menu_action_stops_after_cancelled_secret_dialog(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        window._crossword = create_empty_template(
            CrosswordSettings(4, 4),
            "numbered",
        )

        with (
            patch("krizovkar.gui.SecretGenerationDialog") as dialog_type,
            patch(
                "krizovkar.gui.generate_secret_in_crossword"
            ) as generate_secret,
        ):
            dialog_type.return_value.result = None
            CrosswordDocumentWindow.generate_crossword_secret(window)

        dialog_type.assert_called_once_with(window.root)
        generate_secret.assert_not_called()
        window._set_dirty.assert_not_called()

    def test_menu_action_reports_secret_generation_failure(self) -> None:
        original = create_empty_template(
            CrosswordSettings(4, 4),
            "numbered",
        )
        requirement = SecretRequirement(words=("ABC",))
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        window._crossword = original
        window._template_layout = "numbered"
        window._template_creation_mode = "empty"

        with (
            patch("krizovkar.gui.SecretGenerationDialog") as dialog_type,
            patch(
                "krizovkar.gui.generate_secret_in_crossword",
                side_effect=GenerationError("tajenku nelze umístit"),
            ),
        ):
            dialog_type.return_value.result = SecretGenerationInput(
                requirement=requirement,
                dictionary=TEST_DICTIONARY,
            )
            CrosswordDocumentWindow.generate_crossword_secret(window)

        self.assertIs(original, window._crossword)
        window._show_action_error.assert_called_once_with(
            "Tajenku nelze přidat",
            "tajenku nelze umístit",
        )
        window.root.configure.assert_has_calls(
            [call(cursor="watch"), call(cursor="")]
        )
        window._set_dirty.assert_not_called()
        window._rebuild_slot_tree.assert_not_called()
        window._refresh_crossword_view.assert_not_called()

    def test_menu_action_fills_crossword_as_one_undoable_change(self) -> None:
        original = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )
        filled = _filled_numbered_crossword()
        filling_input = CrosswordFillInput(
            dictionary=TEST_DICTIONARY,
            seed=42,
        )
        window = _document_history_window(original)
        window.root = Mock()

        with (
            patch("krizovkar.gui.CrosswordFillDialog") as dialog_type,
            patch(
                "krizovkar.gui.generate_filled_crossword",
                return_value=filled,
            ) as generate,
            patch.object(
                window,
                "_set_dirty",
                wraps=window._set_dirty,
            ) as set_dirty,
        ):
            dialog_type.return_value.result = filling_input
            CrosswordDocumentWindow.generate_complete_crossword(window)

        dialog_type.assert_called_once_with(window.root)
        generate.assert_called_once_with(
            original,
            TEST_DICTIONARY,
            seed=42,
        )
        self.assertEqual(filled, window._crossword)
        set_dirty.assert_called_once_with(True)
        self.assertEqual(2, len(window._history))
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()
        window.root.configure.assert_has_calls(
            [call(cursor="watch"), call(cursor="")]
        )

        self.assertTrue(window.undo_document())
        self.assertEqual(original, window._crossword)

    def test_menu_action_stops_after_cancelled_crossword_fill_dialog(
        self,
    ) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        window._crossword = create_empty_template(
            CrosswordSettings(4, 4),
            "numbered",
        )

        with (
            patch("krizovkar.gui.CrosswordFillDialog") as dialog_type,
            patch("krizovkar.gui.generate_filled_crossword") as generate,
        ):
            dialog_type.return_value.result = None
            CrosswordDocumentWindow.generate_complete_crossword(window)

        dialog_type.assert_called_once_with(window.root)
        generate.assert_not_called()
        window._set_dirty.assert_not_called()

    def test_menu_action_reports_crossword_filling_failure(self) -> None:
        original = create_empty_template(
            CrosswordSettings(4, 4),
            "numbered",
        )
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        window._crossword = original

        with (
            patch("krizovkar.gui.CrosswordFillDialog") as dialog_type,
            patch(
                "krizovkar.gui.generate_filled_crossword",
                side_effect=FillingError("křížovku nelze vyplnit"),
            ),
        ):
            dialog_type.return_value.result = CrosswordFillInput(
                dictionary=TEST_DICTIONARY,
                seed=42,
            )
            CrosswordDocumentWindow.generate_complete_crossword(window)

        self.assertIs(original, window._crossword)
        window._show_action_error.assert_called_once_with(
            "Křížovku nelze vygenerovat",
            "křížovku nelze vyplnit",
        )
        window.root.configure.assert_has_calls(
            [call(cursor="watch"), call(cursor="")]
        )
        window._set_dirty.assert_not_called()
        window._rebuild_slot_tree.assert_not_called()
        window._refresh_crossword_view.assert_not_called()

    def test_preview_cell_role_change_updates_selected_cells_in_its_document(
        self,
    ) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        crossword = create_blank_template(
            CrosswordSettings(width=4, height=4),
            "numbered",
        )
        window._crossword = crossword
        coordinates = (Coordinate(row=2, column=2), Coordinate(row=3, column=3))

        CrosswordDocumentWindow._preview_cell_role_changed(
            window,
            coordinates,
            "legend",
        )

        for coordinate in coordinates:
            self.assertIsInstance(
                window._crossword.grid.cells[
                    coordinate.row - 1
                ][coordinate.column - 1],
                LegendCellRole,
            )
        self.assertEqual("swedish", window._template_layout)
        window._set_dirty.assert_called_once_with(True)
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()

    def test_preview_cell_role_change_discards_content_without_confirmation(
        self,
    ) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        crossword = fill_crossword_slot(
            crossword,
            "h2",
            "DEF",
            "Druhý řádek",
        )
        window._crossword = crossword

        with patch("krizovkar.gui.messagebox.askyesno") as ask:
            CrosswordDocumentWindow._preview_cell_role_changed(
                window,
                (Coordinate(row=2, column=2),),
                "legend",
            )

        ask.assert_not_called()
        self.assertIsNot(crossword, window._crossword)
        window._set_dirty.assert_called_once_with(True)

    def test_preview_cell_role_change_adds_secret_without_confirmation(
        self,
    ) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        window._crossword = crossword

        with patch("krizovkar.gui.messagebox.askyesno") as ask:
            CrosswordDocumentWindow._preview_cell_role_changed(
                window,
                (Coordinate(row=2, column=2),),
                "secret",
            )

        ask.assert_not_called()
        self.assertIsInstance(
            create_grid_from_crossword(window._crossword).grid.cells[1][1],
            SecretCell,
        )
        window._set_dirty.assert_called_once_with(True)
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()

    def test_preview_cell_role_change_removes_secret_without_confirmation(
        self,
    ) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        crossword = set_crossword_cell_role(
            create_blank_template(
                CrosswordSettings(width=3, height=3),
                "numbered",
            ),
            Coordinate(row=2, column=2),
            "secret",
        )
        window._crossword = crossword

        with patch("krizovkar.gui.messagebox.askyesno") as ask:
            CrosswordDocumentWindow._preview_cell_role_changed(
                window,
                (Coordinate(row=2, column=2),),
                "letter",
            )

        ask.assert_not_called()
        self.assertIsNot(crossword, window._crossword)
        window._set_dirty.assert_called_once_with(True)

    def test_preview_cell_slot_change_adds_directional_start(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        crossword = create_blank_template(
            CrosswordSettings(width=4, height=4),
            "numbered",
        )
        window._crossword = crossword
        coordinate = Coordinate(row=2, column=2)

        CrosswordDocumentWindow._preview_cell_slot_changed(
            window,
            (coordinate,),
            "horizontal",
            True,
        )

        created = next(
            slot
            for slot in window._crossword.slots
            if slot.start == coordinate and slot.direction == "horizontal"
        )
        self.assertEqual("external", created.clue_placement)
        self.assertEqual("numbered", window._template_layout)
        window._set_dirty.assert_called_once_with(True)
        window._rebuild_slot_tree.assert_called_once_with()
        window._refresh_crossword_view.assert_called_once_with()

    def test_preview_cell_slot_change_discards_content_without_confirmation(
        self,
    ) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        crossword = fill_crossword_slot(
            crossword,
            "h2",
            "DEF",
            "Druhý řádek",
        )
        window._crossword = crossword

        with patch("krizovkar.gui.messagebox.askyesno") as ask:
            CrosswordDocumentWindow._preview_cell_slot_changed(
                window,
                (Coordinate(2, 2),),
                "horizontal",
                True,
            )

        ask.assert_not_called()
        self.assertIsNot(crossword, window._crossword)
        window._set_dirty.assert_called_once_with(True)

    def test_preview_receives_slot_start_states(self) -> None:
        window = Mock()
        crossword = create_blank_template(
            CrosswordSettings(width=3, height=3),
            "numbered",
        )
        window._crossword = crossword
        window._selected_slot.return_value = None

        CrosswordDocumentWindow._refresh_crossword_preview(window)

        window.crossword_preview.show_crossword.assert_called_once_with(
            window._grid,
            selected_coordinates=(),
            slot_starts=tuple(
                (slot.start, slot.direction) for slot in crossword.slots
            ),
            external_slot_starts=tuple(
                (slot.start, slot.direction) for slot in crossword.slots
            ),
            show_letters=True,
        )

    def test_application_creates_template_as_new_document(self) -> None:
        application = Mock()
        template = create_blank_template(CrosswordSettings(3, 3), "numbered")
        expected_window = Mock()
        application._open_window.return_value = expected_window
        parent = Mock()
        application._no_document_dialog_parent.return_value = parent
        preferences = Mock()
        preferences.settings = CrosswordSettings(12, 8)
        preferences.layout = "swedish"
        preferences.dictionary = Path("/slovníky/původní.json")
        application._new_crossword_preferences = preferences
        selected_settings = CrosswordSettings(7, 6)
        selected_dictionary = Path("/slovníky/nový.json")

        with patch("krizovkar.gui.TemplateGenerationDialog") as dialog_type:
            dialog_type.return_value.result = NewTemplateResult(
                template,
                "numbered",
                "generated",
                selected_settings,
                selected_dictionary,
            )
            result = CrosswordApplication.new_template_document(application)

        dialog_type.assert_called_once_with(
            parent,
            initial_settings=CrosswordSettings(12, 8),
            initial_layout="swedish",
            initial_content_mode="empty",
            initial_dictionary=Path("/slovníky/původní.json"),
        )
        application._no_document_dialog_parent.assert_called_once_with()
        application._open_window.assert_called_once_with(
            template,
            dirty=True,
            template_layout="numbered",
            template_creation_mode="generated",
        )
        preferences.remember.assert_called_once_with(
            selected_settings,
            "numbered",
            selected_dictionary,
        )
        self.assertIs(expected_window, result)

    def test_empty_template_keeps_last_selected_dictionary(self) -> None:
        application = Mock()
        template = create_empty_template(CrosswordSettings(4, 3), "swedish")
        application._open_window.return_value = Mock()
        preferences = Mock()
        preferences.settings = CrosswordSettings(12, 8)
        preferences.layout = "numbered"
        preferences.dictionary = Path("/slovníky/český.json")
        application._new_crossword_preferences = preferences

        with patch("krizovkar.gui.TemplateGenerationDialog") as dialog_type:
            dialog_type.return_value.result = NewTemplateResult(
                template,
                "swedish",
                "empty",
                CrosswordSettings(4, 3),
                None,
            )

            CrosswordApplication.new_template_document(
                application,
                parent=Mock(),
            )

        preferences.remember.assert_called_once_with(
            CrosswordSettings(4, 3),
            "swedish",
            Path("/slovníky/český.json"),
        )

    def test_application_does_not_open_document_after_cancelled_generation(
        self,
    ) -> None:
        application = Mock()
        parent = Mock()
        preferences = Mock()
        application._new_crossword_preferences = preferences

        with patch("krizovkar.gui.TemplateGenerationDialog") as dialog_type:
            dialog_type.return_value.result = None
            result = CrosswordApplication.new_template_document(
                application,
                parent=parent,
            )

        self.assertIsNone(result)
        application._open_window.assert_not_called()
        preferences.remember.assert_not_called()

    def test_application_owner_stays_hidden_behind_document_windows(self) -> None:
        root = Mock()
        preferences = Mock()

        with (
            patch.object(
                CrosswordApplication,
                "_configure_no_document_window",
            ),
            patch.object(CrosswordApplication, "_build_menu"),
        ):
            application = CrosswordApplication(
                root,
                new_crossword_preferences=preferences,
            )

        root.withdraw.assert_called_once_with()
        self.assertEqual([], application._windows)
        self.assertIsNone(application._active_window)
        self.assertEqual({}, application._source_windows)
        self.assertIs(preferences, application._new_crossword_preferences)

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

    def test_application_shows_owner_window_without_document_off_macos(
        self,
    ) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        application.root = Mock()

        with patch("krizovkar.gui.sys.platform", "linux"):
            application.show_no_document_state()

        application.root.deiconify.assert_called_once_with()
        application.root.lift.assert_called_once_with()
        application.root.event_generate.assert_not_called()

    def test_application_activates_menu_without_window_on_macos(self) -> None:
        application = CrosswordApplication.__new__(CrosswordApplication)
        application.root = Mock()

        with patch("krizovkar.gui.sys.platform", "darwin"):
            application.show_no_document_state()

        application.root.event_generate.assert_called_once_with("<Activate>")
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

    def test_new_crossword_save_as_uses_short_title_and_filename(self) -> None:
        window = Mock()
        window._save_inline_slot_edit.return_value = True
        window._crossword = Mock()
        window._path = None
        window._choose_output.return_value = None

        saved = CrosswordDocumentWindow.save_document_as(window)

        self.assertFalse(saved)
        window._choose_output.assert_called_once_with(
            title="Uložit jako",
            initialfile="krizovka.yaml",
            extension=".yaml",
            filetypes=(
                ("YAML soubory", "*.yaml *.yml"),
                ("Všechny soubory", "*"),
            ),
            overwrite_title="Přepsat datový soubor?",
        )

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

        window.root.title.assert_called_once_with(
            "*Nová křížovka — Křížovkář"
        )
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

    def test_crossword_pdf_actions_export_empty_puzzle_and_solution(self) -> None:
        application = Mock()
        application._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )

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
                    create_grid.return_value,
                    filled=True,
                    title="Exportovat řešení s písmeny",
                    initialfile="reseni.pdf",
                ),
            ],
            application._save_pdf.call_args_list,
        )
        self.assertEqual(
            [call(application._crossword), call(application._crossword)],
            create_grid.call_args_list,
        )

    def test_grid_yaml_and_latex_actions_export_both_empty_versions(self) -> None:
        application = Mock()
        application._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )

        with patch("krizovkar.gui.create_grid_from_crossword") as create_grid:
            CrosswordDocumentWindow.save_crossword_grid_yaml(application)
            CrosswordDocumentWindow.save_solution_grid_yaml(application)
            CrosswordDocumentWindow.save_crossword_latex(application)
            CrosswordDocumentWindow.save_solution_latex(application)

        self.assertEqual(
            [
                call(
                    create_grid.return_value,
                    filled=False,
                    title="Exportovat mřížkový YAML bez písmen",
                    initialfile="mrizka-bez-pismen.yaml",
                ),
                call(
                    create_grid.return_value,
                    filled=True,
                    title="Exportovat mřížkový YAML s písmeny",
                    initialfile="mrizka-s-pismeny.yaml",
                ),
            ],
            application._save_grid_yaml.call_args_list,
        )
        self.assertEqual(
            [
                call(
                    create_grid.return_value,
                    filled=False,
                    title="Exportovat křížovku bez písmen jako LaTeX",
                    initialfile="krizovka.tex",
                ),
                call(
                    create_grid.return_value,
                    filled=True,
                    title="Exportovat řešení s písmeny jako LaTeX",
                    initialfile="reseni.tex",
                ),
            ],
            application._save_latex.call_args_list,
        )
        self.assertEqual(
            [call(application._crossword)] * 4,
            create_grid.call_args_list,
        )

    def test_print_actions_choose_empty_puzzle_and_partial_solution(self) -> None:
        application = Mock()
        application._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )

        with patch("krizovkar.gui.create_grid_from_crossword") as create_grid:
            CrosswordDocumentWindow.print_crossword(application)
            CrosswordDocumentWindow.print_solution(application)

        self.assertEqual(
            [
                call(
                    create_grid.return_value,
                    filled=False,
                    title="Tisknout křížovku bez písmen",
                    filename="krizovka.pdf",
                    job_name="Křížovkář – křížovka",
                ),
                call(
                    create_grid.return_value,
                    filled=True,
                    title="Tisknout řešení s písmeny",
                    filename="reseni.pdf",
                    job_name="Křížovkář – řešení",
                ),
            ],
            application._print_pdf.call_args_list,
        )
        self.assertEqual(
            [call(application._crossword), call(application._crossword)],
            create_grid.call_args_list,
        )

    def test_open_pdf_actions_choose_empty_puzzle_and_partial_solution(
        self,
    ) -> None:
        application = Mock()
        application._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )

        with patch("krizovkar.gui.create_grid_from_crossword") as create_grid:
            CrosswordDocumentWindow.open_crossword_pdf(application)
            CrosswordDocumentWindow.open_solution_pdf(application)

        self.assertEqual(
            [
                call(
                    create_grid.return_value,
                    filled=False,
                    title="Otevřít jako PDF – křížovka bez písmen",
                    filename="krizovka.pdf",
                ),
                call(
                    create_grid.return_value,
                    filled=True,
                    title="Otevřít jako PDF – řešení s písmeny",
                    filename="reseni.pdf",
                ),
            ],
            application._open_temporary_pdf.call_args_list,
        )
        self.assertEqual(
            [call(application._crossword), call(application._crossword)],
            create_grid.call_args_list,
        )

    def test_export_actions_offer_both_variants_in_all_formats(self) -> None:
        crossword_window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        crossword_window.export_menu = Mock()

        CrosswordDocumentWindow._add_export_actions(crossword_window)

        self.assertEqual(
            [
                call.add_command(
                    label="Křížovku bez písmen (PDF)…",
                    command=crossword_window.save_crossword_pdf,
                ),
                call.add_command(
                    label="Řešení s písmeny (PDF)…",
                    command=crossword_window.save_solution_pdf,
                ),
                call.add_separator(),
                call.add_command(
                    label="Křížovku bez písmen (LaTeX)…",
                    command=crossword_window.save_crossword_latex,
                ),
                call.add_command(
                    label="Řešení s písmeny (LaTeX)…",
                    command=crossword_window.save_solution_latex,
                ),
                call.add_separator(),
                call.add_command(
                    label="Mřížku bez písmen (YAML)…",
                    command=crossword_window.save_crossword_grid_yaml,
                ),
                call.add_command(
                    label="Mřížku s písmeny (YAML)…",
                    command=crossword_window.save_solution_grid_yaml,
                ),
            ],
            crossword_window.export_menu.method_calls,
        )

    def test_print_actions_offer_crossword_and_solution(self) -> None:
        crossword_window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        crossword_window.print_menu = Mock()

        CrosswordDocumentWindow._add_print_actions(crossword_window)

        self.assertEqual(
            [
                call(
                    label="Křížovku bez písmen…",
                    command=crossword_window.print_crossword,
                ),
                call(
                    label="Řešení s písmeny…",
                    command=crossword_window.print_solution,
                ),
            ],
            crossword_window.print_menu.add_command.call_args_list,
        )

    def test_open_pdf_actions_offer_crossword_and_solution(self) -> None:
        crossword_window = CrosswordDocumentWindow.__new__(CrosswordDocumentWindow)
        crossword_window.open_pdf_menu = Mock()

        CrosswordDocumentWindow._add_open_pdf_actions(crossword_window)

        self.assertEqual(
            [
                call(
                    label="Křížovku bez písmen…",
                    command=crossword_window.open_crossword_pdf,
                ),
                call(
                    label="Řešení s písmeny…",
                    command=crossword_window.open_solution_pdf,
                ),
            ],
            crossword_window.open_pdf_menu.add_command.call_args_list,
        )

    def test_file_menu_enables_complete_crossword_outputs(self) -> None:
        application = Mock()
        application._save_menu_index = 4
        application._save_as_menu_index = 5
        application.open_pdf_menu = Mock()
        application._crossword = _filled_numbered_crossword()

        CrosswordDocumentWindow._refresh_file_menu(application)

        self.assertEqual(
            [
                call(4, label="Uložit", state="normal"),
                call(5, label="Uložit jako…", state="normal"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [
                call(0, state="normal"),
                call(1, state="normal"),
                call(3, state="normal"),
                call(4, state="normal"),
                call(6, state="normal"),
                call(7, state="normal"),
            ],
            application.export_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [
                call(0, state="normal"),
                call(1, state="normal"),
            ],
            application.print_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [
                call(0, state="normal"),
                call(1, state="normal"),
            ],
            application.open_pdf_menu.entryconfigure.call_args_list,
        )

    def test_file_menu_allows_all_outputs_for_incomplete_crossword(self) -> None:
        application = Mock()
        application._save_menu_index = 4
        application._save_as_menu_index = 5
        application.open_pdf_menu = Mock()
        application._crossword = create_blank_template(
            CrosswordSettings(3, 3),
            "numbered",
        )

        CrosswordDocumentWindow._refresh_file_menu(application)

        self.assertEqual(
            [
                call(4, label="Uložit", state="normal"),
                call(5, label="Uložit jako…", state="normal"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [
                call(0, state="normal"),
                call(1, state="normal"),
                call(3, state="normal"),
                call(4, state="normal"),
                call(6, state="normal"),
                call(7, state="normal"),
            ],
            application.export_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [call(0, state="normal"), call(1, state="normal")],
            application.print_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [call(0, state="normal"), call(1, state="normal")],
            application.open_pdf_menu.entryconfigure.call_args_list,
        )

    def test_file_menu_disables_actions_for_invalid_yaml_source(self) -> None:
        application = Mock()
        application._save_menu_index = 4
        application._save_as_menu_index = 5
        application.open_pdf_menu = Mock()
        application._crossword = None

        CrosswordDocumentWindow._refresh_file_menu(application)

        self.assertEqual(
            [
                call(4, label="Uložit", state="disabled"),
                call(5, label="Uložit jako…", state="disabled"),
            ],
            application.file_menu.entryconfigure.call_args_list,
        )
        self.assertEqual(
            [
                call(0, state="disabled"),
                call(1, state="disabled"),
                call(3, state="disabled"),
                call(4, state="disabled"),
                call(6, state="disabled"),
                call(7, state="disabled"),
            ],
            application.export_menu.entryconfigure.call_args_list,
        )
        for menu in (application.print_menu, application.open_pdf_menu):
            self.assertEqual(
                [call(0, state="disabled"), call(1, state="disabled")],
                menu.entryconfigure.call_args_list,
            )

    def test_page_format_is_chosen_in_export_dialog_and_remembered(self) -> None:
        window = Mock()
        window._page_format = "A4"

        with patch("krizovkar.gui.PdfExportDialog") as dialog_type:
            dialog_type.return_value.result = "A5"
            page_format = CrosswordDocumentWindow._choose_page_format(
                window,
                title="Exportovat křížovku bez písmen",
                confirm_label="Vybrat umístění…",
            )

        self.assertEqual("A5", page_format)
        dialog_type.assert_called_once_with(
            window.root,
            title="Exportovat křížovku bez písmen",
            initial_page_format="A4",
            confirm_label="Vybrat umístění…",
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
                confirm_label="Vybrat umístění…",
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
            confirm_label="Vybrat umístění…",
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

    def test_saves_grid_yaml_with_and_without_letters(self) -> None:
        grid = CrosswordGrid(
            format_name="krizovkar",
            kind="grid",
            version=1,
            grid=Grid(
                width=2,
                height=1,
                cells=(
                    (
                        LetterCell(value="A", number=1),
                        SecretCell(value="B", arrow="right"),
                    ),
                ),
            ),
        )
        blank_grid = CrosswordGrid(
            format_name="krizovkar",
            kind="grid",
            version=1,
            grid=Grid(
                width=2,
                height=1,
                cells=(
                    (
                        LetterCell(number=1),
                        SecretCell(arrow="right"),
                    ),
                ),
            ),
        )
        application = Mock()
        with tempfile.TemporaryDirectory() as directory:
            blank_output = Path(directory) / "mrizka-bez-pismen.yaml"
            filled_output = Path(directory) / "mrizka-s-pismeny.yaml"
            application._choose_output.side_effect = (
                (blank_output, False),
                (filled_output, False),
            )

            CrosswordDocumentWindow._save_grid_yaml(
                application,
                grid,
                filled=False,
                title="Exportovat mřížkový YAML bez písmen",
                initialfile="mrizka-bez-pismen.yaml",
            )
            CrosswordDocumentWindow._save_grid_yaml(
                application,
                grid,
                filled=True,
                title="Exportovat mřížkový YAML s písmeny",
                initialfile="mrizka-s-pismeny.yaml",
            )

            self.assertEqual(blank_grid, load_crossword_grid(blank_output))
            self.assertEqual(grid, load_crossword_grid(filled_output))
            self.assertEqual("A", grid.grid.cells[0][0].value)
            self.assertEqual("B", grid.grid.cells[0][1].value)

        self.assertEqual(
            [
                call(
                    title="Exportovat mřížkový YAML bez písmen",
                    initialfile="mrizka-bez-pismen.yaml",
                    extension=".yaml",
                    filetypes=(
                        ("YAML soubory", "*.yaml *.yml"),
                        ("Všechny soubory", "*"),
                    ),
                    overwrite_title="Přepsat mřížkový YAML?",
                ),
                call(
                    title="Exportovat mřížkový YAML s písmeny",
                    initialfile="mrizka-s-pismeny.yaml",
                    extension=".yaml",
                    filetypes=(
                        ("YAML soubory", "*.yaml *.yml"),
                        ("Všechny soubory", "*"),
                    ),
                    overwrite_title="Přepsat mřížkový YAML?",
                ),
            ],
            application._choose_output.call_args_list,
        )
        application._show_action_error.assert_not_called()

    def test_saves_latex_with_and_without_letters(self) -> None:
        grid = create_grid_from_crossword(_filled_numbered_crossword())
        application = Mock()
        application._choose_page_format.side_effect = ("A5", "A4")
        blank_output = Path("krizovka.tex")
        filled_output = Path("reseni.tex")
        application._choose_output.side_effect = (
            (blank_output, False),
            (filled_output, True),
        )

        with patch("krizovkar.gui.render_latex") as render:
            CrosswordDocumentWindow._save_latex(
                application,
                grid,
                filled=False,
                title="Exportovat křížovku bez písmen jako LaTeX",
                initialfile="krizovka.tex",
            )
            CrosswordDocumentWindow._save_latex(
                application,
                grid,
                filled=True,
                title="Exportovat řešení s písmeny jako LaTeX",
                initialfile="reseni.tex",
            )

        self.assertEqual(
            [
                call(
                    title="Exportovat křížovku bez písmen jako LaTeX",
                    confirm_label="Vybrat umístění…",
                ),
                call(
                    title="Exportovat řešení s písmeny jako LaTeX",
                    confirm_label="Vybrat umístění…",
                ),
            ],
            application._choose_page_format.call_args_list,
        )
        self.assertEqual(
            [
                call(
                    title="Exportovat křížovku bez písmen jako LaTeX",
                    initialfile="krizovka.tex",
                    extension=".tex",
                    filetypes=(
                        ("LaTeXové soubory", "*.tex"),
                        ("Všechny soubory", "*"),
                    ),
                    overwrite_title="Přepsat LaTeX?",
                ),
                call(
                    title="Exportovat řešení s písmeny jako LaTeX",
                    initialfile="reseni.tex",
                    extension=".tex",
                    filetypes=(
                        ("LaTeXové soubory", "*.tex"),
                        ("Všechny soubory", "*"),
                    ),
                    overwrite_title="Přepsat LaTeX?",
                ),
            ],
            application._choose_output.call_args_list,
        )
        self.assertEqual(
            [
                call(
                    grid,
                    blank_output,
                    overwrite=False,
                    page_format="A5",
                    filled=False,
                ),
                call(
                    grid,
                    filled_output,
                    overwrite=True,
                    page_format="A4",
                    filled=True,
                ),
            ],
            render.call_args_list,
        )
        application._show_action_error.assert_not_called()

    def test_grid_yaml_export_error_is_shown(self) -> None:
        application = Mock()
        application._choose_output.return_value = (Path("mrizka.yaml"), False)

        with patch(
            "krizovkar.gui.write_crossword_grid",
            side_effect=ModelError("nelze zapsat"),
        ):
            CrosswordDocumentWindow._save_grid_yaml(
                application,
                Mock(),
                filled=True,
                title="Exportovat mřížkový YAML s písmeny",
                initialfile="mrizka-s-pismeny.yaml",
            )

        application._show_action_error.assert_called_once_with(
            "Mřížkový YAML nelze vytvořit",
            "nelze zapsat",
        )

    def test_prints_pdf_with_chosen_page_format(self) -> None:
        crossword = _filled_numbered_crossword()
        grid = create_grid_from_crossword(crossword)
        application = Mock()
        application._choose_page_format.return_value = "A5"

        with (
            patch(
                "krizovkar.renderer._run_lualatex",
                side_effect=_fake_lualatex,
            ),
            patch("krizovkar.gui._send_pdf_to_printer") as send_to_printer,
        ):
            CrosswordDocumentWindow._print_pdf(
                application,
                grid,
                filled=False,
                title="Tisknout křížovku bez písmen",
                filename="krizovka.pdf",
                job_name="Křížovkář – křížovka",
            )

        application._choose_page_format.assert_called_once_with(
            title="Tisknout křížovku bez písmen",
            confirm_label="Pokračovat k tisku…",
        )
        printed_pdf = send_to_printer.call_args.args[1]
        self.assertEqual(PDF_BYTES, printed_pdf.read_bytes())
        send_to_printer.assert_called_once_with(
            application.root,
            printed_pdf,
            job_name="Křížovkář – křížovka",
        )
        self.assertEqual(
            [call(cursor="watch"), call(cursor="")],
            application.root.configure.call_args_list,
        )
        application.root.update_idletasks.assert_called_once_with()
        application.root.after.assert_called_once()
        delay, cleanup = application.root.after.call_args.args
        self.assertEqual(5 * 60 * 1000, delay)
        cleanup()
        self.assertFalse(printed_pdf.exists())

    def test_cancelled_print_dialog_does_not_create_pdf(self) -> None:
        application = Mock()
        application._choose_page_format.return_value = None

        with patch("krizovkar.gui.render_pdf") as render:
            CrosswordDocumentWindow._print_pdf(
                application,
                Mock(),
                filled=False,
                title="Tisknout křížovku bez písmen",
                filename="krizovka.pdf",
                job_name="Křížovkář – křížovka",
            )

        render.assert_not_called()
        application.root.after.assert_not_called()

    def test_print_render_error_removes_temporary_pdf(self) -> None:
        application = Mock()
        application._choose_page_format.return_value = "A4"
        rendered_path: Path | None = None

        def fail_render(
            crossword,
            output,
            *,
            page_format,
            filled,
        ) -> None:
            nonlocal rendered_path
            rendered_path = output
            raise RenderError("nainstalujte TeX Live")

        with patch("krizovkar.gui.render_pdf", side_effect=fail_render):
            CrosswordDocumentWindow._print_pdf(
                application,
                Mock(),
                filled=False,
                title="Tisknout křížovku bez písmen",
                filename="krizovka.pdf",
                job_name="Křížovkář – křížovka",
            )

        self.assertIsNotNone(rendered_path)
        assert rendered_path is not None
        self.assertFalse(rendered_path.parent.exists())
        application._show_action_error.assert_called_once_with(
            "PDF nelze vytvořit",
            "nainstalujte TeX Live",
        )
        application.root.after.assert_not_called()

    def test_print_system_error_removes_temporary_pdf(self) -> None:
        crossword = _filled_numbered_crossword()
        grid = create_grid_from_crossword(crossword)
        application = Mock()
        application._choose_page_format.return_value = "A4"

        with (
            patch(
                "krizovkar.renderer._run_lualatex",
                side_effect=_fake_lualatex,
            ),
            patch(
                "krizovkar.gui._send_pdf_to_printer",
                side_effect=_PrintError("není nastavena tiskárna"),
            ) as send_to_printer,
        ):
            CrosswordDocumentWindow._print_pdf(
                application,
                grid,
                filled=False,
                title="Tisknout křížovku bez písmen",
                filename="krizovka.pdf",
                job_name="Křížovkář – křížovka",
            )

        printed_pdf = send_to_printer.call_args.args[1]
        self.assertFalse(printed_pdf.parent.exists())
        application._show_action_error.assert_called_once_with(
            "PDF nelze vytisknout",
            "není nastavena tiskárna",
        )
        application.root.after.assert_not_called()

    def test_temporary_print_file_error_is_shown(self) -> None:
        application = Mock()
        application._choose_page_format.return_value = "A4"

        with patch(
            "krizovkar.gui.TemporaryDirectory",
            side_effect=PermissionError,
        ):
            CrosswordDocumentWindow._print_pdf(
                application,
                Mock(),
                filled=False,
                title="Tisknout křížovku bez písmen",
                filename="krizovka.pdf",
                job_name="Křížovkář – křížovka",
            )

        application._show_action_error.assert_called_once_with(
            "PDF nelze vytvořit",
            "Dočasný soubor nelze vytvořit: přístup byl odepřen",
        )
        application.root.configure.assert_not_called()
        application.root.after.assert_not_called()

    def test_opens_pdf_in_default_application_with_chosen_page_format(self) -> None:
        crossword = _filled_numbered_crossword()
        grid = create_grid_from_crossword(crossword)
        application = Mock()
        application._choose_page_format.return_value = "A5"

        with (
            patch(
                "krizovkar.renderer._run_lualatex",
                side_effect=_fake_lualatex,
            ),
            patch(
                "krizovkar.gui._open_pdf_in_default_application"
            ) as open_pdf,
        ):
            CrosswordDocumentWindow._open_temporary_pdf(
                application,
                grid,
                filled=False,
                title="Otevřít jako PDF – křížovka bez písmen",
                filename="krizovka.pdf",
            )

        application._choose_page_format.assert_called_once_with(
            title="Otevřít jako PDF – křížovka bez písmen",
            confirm_label="Otevřít jako PDF",
        )
        opened_pdf = open_pdf.call_args.args[1]
        self.assertEqual(PDF_BYTES, opened_pdf.read_bytes())
        open_pdf.assert_called_once_with(
            application.root,
            opened_pdf,
        )
        application.root.after.assert_called_once()
        delay, cleanup = application.root.after.call_args.args
        self.assertEqual(5 * 60 * 1000, delay)
        cleanup()
        self.assertFalse(opened_pdf.exists())

    def test_pdf_open_error_removes_temporary_pdf(self) -> None:
        crossword = _filled_numbered_crossword()
        grid = create_grid_from_crossword(crossword)
        application = Mock()
        application._choose_page_format.return_value = "A4"

        with (
            patch(
                "krizovkar.renderer._run_lualatex",
                side_effect=_fake_lualatex,
            ),
            patch(
                "krizovkar.gui._open_pdf_in_default_application",
                side_effect=_PdfOpenError("výchozí aplikace není dostupná"),
            ) as open_pdf,
        ):
            CrosswordDocumentWindow._open_temporary_pdf(
                application,
                grid,
                filled=False,
                title="Otevřít jako PDF – křížovka bez písmen",
                filename="krizovka.pdf",
            )

        opened_pdf = open_pdf.call_args.args[1]
        self.assertFalse(opened_pdf.parent.exists())
        application._show_action_error.assert_called_once_with(
            "PDF nelze otevřít",
            "výchozí aplikace není dostupná",
        )
        application.root.after.assert_not_called()

    def test_macos_pdf_opening_uses_default_application(self) -> None:
        root = Mock()
        root.tk.call.return_value = "aqua"
        source = Path("krizovka.pdf")
        result = Mock(returncode=0, stdout="")

        with patch("krizovkar.gui.subprocess.run", return_value=result) as run:
            _open_pdf_in_default_application(root, source)

        run.assert_called_once_with(
            ("/usr/bin/open", str(source)),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_windows_pdf_opening_uses_file_association(self) -> None:
        root = Mock()
        root.tk.call.return_value = "win32"
        source = Path("krizovka.pdf")

        with patch("krizovkar.gui.os.startfile", create=True) as startfile:
            _open_pdf_in_default_application(root, source)

        startfile.assert_called_once_with(str(source))

    def test_x11_pdf_opening_uses_xdg_open(self) -> None:
        root = Mock()
        root.tk.call.return_value = "x11"
        source = Path("krizovka.pdf")
        result = Mock(returncode=0, stdout="")

        with patch("krizovkar.gui.subprocess.run", return_value=result) as run:
            _open_pdf_in_default_application(root, source)

        run.assert_called_once_with(
            ("xdg-open", str(source)),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_macos_pdf_opening_reports_command_failure(self) -> None:
        root = Mock()
        root.tk.call.return_value = "aqua"
        result = Mock(returncode=1, stdout="application not found")

        with (
            patch("krizovkar.gui.subprocess.run", return_value=result),
            self.assertRaisesRegex(
                _PdfOpenError,
                "PDF nelze otevřít ve výchozí aplikaci: application not found",
            ),
        ):
            _open_pdf_in_default_application(root, Path("krizovka.pdf"))

    def test_macos_printing_uses_native_pdf_dialog(self) -> None:
        root = Mock()
        root.tk.call.side_effect = ("aqua", "")
        source = Path("krizovka.pdf")

        _send_pdf_to_printer(
            root,
            source,
            job_name="Křížovkář – křížovka",
        )

        self.assertEqual(
            [
                call("tk", "windowingsystem"),
                call("::tk::print::_print", str(source)),
            ],
            root.tk.call.call_args_list,
        )

    def test_windows_printing_uses_associated_pdf_application(self) -> None:
        root = Mock()
        root.tk.call.return_value = "win32"
        source = Path("krizovka.pdf")

        with patch("krizovkar.gui.os.startfile", create=True) as startfile:
            _send_pdf_to_printer(
                root,
                source,
                job_name="Křížovkář – křížovka",
            )

        startfile.assert_called_once_with(str(source), "print")

    def test_x11_printing_submits_pdf_to_cups(self) -> None:
        root = Mock()
        root.tk.call.return_value = "x11"
        source = Path("krizovka.pdf")
        result = Mock(returncode=0, stdout="request id is tiskarna-1")

        with patch("krizovkar.gui.subprocess.run", return_value=result) as run:
            _send_pdf_to_printer(
                root,
                source,
                job_name="Křížovkář – křížovka",
            )

        run.assert_called_once_with(
            (
                "lp",
                "-t",
                "Křížovkář – křížovka",
                "--",
                str(source),
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_x11_printing_reports_missing_cups_command(self) -> None:
        root = Mock()
        root.tk.call.return_value = "x11"

        with (
            patch(
                "krizovkar.gui.subprocess.run",
                side_effect=FileNotFoundError,
            ),
            self.assertRaisesRegex(
                _PrintError,
                "Tiskový příkaz lp nebyl nalezen",
            ),
        ):
            _send_pdf_to_printer(
                root,
                Path("krizovka.pdf"),
                job_name="Křížovkář – křížovka",
            )

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

    def test_main_opens_new_template_dialog(self) -> None:
        root = Mock()
        application = Mock()
        application.new_template_document.return_value = Mock()
        with (
            patch("krizovkar.gui.tk.Tk", return_value=root),
            patch(
                "krizovkar.gui.CrosswordApplication",
                return_value=application,
            ),
        ):
            exit_code = main([])

        self.assertEqual(0, exit_code)
        application.new_template_document.assert_called_once_with(parent=None)
        application.show_no_document_state.assert_not_called()
        application.choose_document.assert_not_called()
        application.open_document.assert_not_called()
        root.mainloop.assert_called_once_with()

    def test_main_stays_open_when_new_template_dialog_is_cancelled(self) -> None:
        root = Mock()
        application = Mock()
        application.new_template_document.return_value = None
        with (
            patch("krizovkar.gui.tk.Tk", return_value=root),
            patch(
                "krizovkar.gui.CrosswordApplication",
                return_value=application,
            ),
        ):
            exit_code = main([])

        self.assertEqual(0, exit_code)
        application.new_template_document.assert_called_once_with(parent=None)
        application.show_no_document_state.assert_called_once_with()
        application.choose_document.assert_not_called()
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

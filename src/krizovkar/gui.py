"""Grafické rozhraní Křížovkáře postavené na Tk."""

from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import cast

from krizovkar.alphabet import split_answer_letters
from krizovkar.generator import (
    DEFAULT_GRID_HEIGHT,
    DEFAULT_GRID_WIDTH,
    GenerationError,
    SpecificationLayout,
    create_template_from_specification,
)
from krizovkar.localization import ngettext
from krizovkar.model import (
    Coordinate,
    CrosswordSpecification,
    CrosswordTemplate,
    GridDimensions,
    ModelError,
    WordDirection,
    WordPlacement,
    dump_crossword_specification,
    write_crossword_specification,
    write_crossword_template,
)

_DIRECTIONS = frozenset(("horizontal", "vertical"))
_DIRECTION_LABELS = {
    "horizontal": "Vodorovně",
    "vertical": "Svisle",
}


class GuiInputError(ValueError):
    """Nastavení zadané v grafickém rozhraní není platné."""


@dataclass(frozen=True, slots=True)
class SpecificationSettings:
    """Rozměr vstupního zadání křížovky."""

    width: int
    height: int


def _positive_integer(value: str, label: str) -> int:
    try:
        number = int(value.strip())
    except ValueError as error:
        raise GuiInputError(f"{label} musí být celé číslo.") from error
    if number < 1:
        raise GuiInputError(f"{label} musí být kladný.")
    return number


def parse_specification_settings(
    width: str,
    height: str,
) -> SpecificationSettings:
    """Převede rozměry z formuláře na nastavení zadání."""

    return SpecificationSettings(
        width=_positive_integer(width, "Počet sloupců"),
        height=_positive_integer(height, "Počet řádků"),
    )


def parse_word_placement(
    answer: str,
    legend: str,
    row: str,
    column: str,
    direction: str,
    in_help: bool,
) -> WordPlacement:
    """Převede formulář jednoho hesla na položku zadání."""

    normalized_answer = answer.strip().upper()
    if not normalized_answer:
        raise GuiInputError("Vyplňte heslo.")
    try:
        split_answer_letters(normalized_answer)
    except ValueError as error:
        raise GuiInputError(str(error)) from error

    normalized_legend = legend.strip()
    if not normalized_legend:
        raise GuiInputError("Vyplňte legendu hesla.")
    if direction not in _DIRECTIONS:
        raise GuiInputError("Vyberte směr hesla.")

    return WordPlacement(
        answer=normalized_answer,
        start=Coordinate(
            row=_positive_integer(row, "Počáteční řádek"),
            column=_positive_integer(column, "Počáteční sloupec"),
        ),
        direction=cast(WordDirection, direction),
        legend=normalized_legend,
        in_help=in_help,
    )


def create_specification(
    settings: SpecificationSettings,
    words: tuple[WordPlacement, ...],
) -> CrosswordSpecification:
    """Vytvoří a ověří zadání z rozměru a umístěných hesel."""

    if not words:
        raise GuiInputError("Přidejte alespoň jedno heslo.")
    specification = CrosswordSpecification(
        format_name="krizovkar",
        kind="specification",
        version=1,
        grid=GridDimensions(width=settings.width, height=settings.height),
        words=words,
    )
    try:
        dump_crossword_specification(specification, StringIO())
    except ModelError as error:
        raise GuiInputError(str(error)) from error
    return specification


def create_template(
    specification: CrosswordSpecification,
    layout: SpecificationLayout,
) -> CrosswordTemplate:
    """Převede platné zadání z editoru na zvolenou šablonu."""

    try:
        return create_template_from_specification(
            specification,
            layout=layout,
        )
    except GenerationError as error:
        raise GuiInputError(str(error)) from error


def _word_count_text(count: int) -> str:
    return f"{count} {ngettext('heslo', 'hesel', count)}"


def _configure_tk_runtime() -> None:
    """Doplní cesty k Tcl/Tk přibalenému k některým distribucím Pythonu."""

    library_root = Path(sys.base_prefix) / "lib"
    versions = (
        ("TCL_LIBRARY", f"tcl{tk.TclVersion:.1f}"),
        ("TK_LIBRARY", f"tk{tk.TkVersion:.1f}"),
    )
    for variable, directory_name in versions:
        directory = library_root / directory_name
        if variable not in os.environ and directory.is_dir():
            os.environ[variable] = str(directory)


class SpecificationPreview(tk.Canvas):
    """Náhled rozměru, písmen a křížení vstupního zadání."""

    _GRID_COLOR = "#667085"
    _LETTER_FILL = "#eff6ff"
    _SELECTED_FILL = "#bfdbfe"
    _LETTER_COLOR = "#101828"
    _COORDINATE_COLOR = "#667085"

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        super().__init__(
            master,
            background="#f8fafc",
            highlightbackground="#cbd5e1",
            highlightthickness=1,
            **kwargs,
        )
        self._dimensions: GridDimensions | None = None
        self._words: tuple[WordPlacement, ...] = ()
        self._selected_index: int | None = None
        self._empty_message = "Zadejte platný rozměr mřížky."
        self.bind("<Configure>", self._redraw)

    def show_draft(
        self,
        dimensions: GridDimensions,
        words: tuple[WordPlacement, ...],
        selected_index: int | None = None,
    ) -> None:
        self._dimensions = dimensions
        self._words = words
        self._selected_index = selected_index
        self._redraw()

    def clear_preview(self, message: str) -> None:
        self._dimensions = None
        self._words = ()
        self._selected_index = None
        self._empty_message = message
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.delete("all")
        dimensions = self._dimensions
        if dimensions is None:
            self.create_text(
                max(self.winfo_width(), 2) / 2,
                max(self.winfo_height(), 2) / 2,
                text=self._empty_message,
                fill=self._COORDINATE_COLOR,
                width=max(self.winfo_width() - 48, 120),
                justify="center",
            )
            return

        canvas_width = max(self.winfo_width(), 2)
        canvas_height = max(self.winfo_height(), 2)
        coordinate_gutter = 24
        available_width = max(canvas_width - coordinate_gutter - 32, 1)
        available_height = max(canvas_height - coordinate_gutter - 32, 1)
        cell_size = min(
            available_width / dimensions.width,
            available_height / dimensions.height,
            36,
        )
        grid_width = cell_size * dimensions.width
        grid_height = cell_size * dimensions.height
        left = (canvas_width - grid_width + coordinate_gutter) / 2
        top = (canvas_height - grid_height + coordinate_gutter) / 2
        letters, selected_coordinates = self._placed_letters()

        for row in range(1, dimensions.height + 1):
            for column in range(1, dimensions.width + 1):
                x1 = left + (column - 1) * cell_size
                y1 = top + (row - 1) * cell_size
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                coordinate = (row, column)
                letter = letters.get(coordinate)
                fill = "#ffffff"
                if coordinate in selected_coordinates:
                    fill = self._SELECTED_FILL
                elif letter is not None:
                    fill = self._LETTER_FILL
                self.create_rectangle(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=fill,
                    outline=self._GRID_COLOR,
                    width=1,
                )
                if letter is not None and cell_size >= 11:
                    self.create_text(
                        (x1 + x2) / 2,
                        (y1 + y2) / 2,
                        text=letter,
                        fill=self._LETTER_COLOR,
                        font=(
                            "TkDefaultFont",
                            max(7, int(cell_size * 0.42)),
                            "bold",
                        ),
                    )

        self.create_rectangle(
            left,
            top,
            left + grid_width,
            top + grid_height,
            outline="#101828",
            width=2,
        )
        if cell_size >= 18:
            self._draw_coordinates(left, top, cell_size, dimensions)

    def _placed_letters(
        self,
    ) -> tuple[dict[tuple[int, int], str], set[tuple[int, int]]]:
        letters: dict[tuple[int, int], str] = {}
        selected_coordinates: set[tuple[int, int]] = set()
        for word_index, word in enumerate(self._words):
            row_step = 1 if word.direction == "vertical" else 0
            column_step = 1 if word.direction == "horizontal" else 0
            for offset, letter in enumerate(split_answer_letters(word.answer)):
                coordinate = (
                    word.start.row + offset * row_step,
                    word.start.column + offset * column_step,
                )
                letters[coordinate] = letter
                if word_index == self._selected_index:
                    selected_coordinates.add(coordinate)
        return letters, selected_coordinates

    def _draw_coordinates(
        self,
        left: float,
        top: float,
        cell_size: float,
        dimensions: GridDimensions,
    ) -> None:
        for column in range(1, dimensions.width + 1):
            self.create_text(
                left + (column - 0.5) * cell_size,
                top - 7,
                text=str(column),
                anchor="s",
                fill=self._COORDINATE_COLOR,
            )
        for row in range(1, dimensions.height + 1):
            self.create_text(
                left - 7,
                top + (row - 0.5) * cell_size,
                text=str(row),
                anchor="e",
                fill=self._COORDINATE_COLOR,
            )


class CrosswordApplication(ttk.Frame):
    """Hlavní okno s editorem zadání a vytvořením šablony."""

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, padding=(24, 20))
        self.root = root
        self._words: list[WordPlacement] = []
        self._specification: CrosswordSpecification | None = None
        self._editing_index: int | None = None

        self.width_value = tk.StringVar(value=str(DEFAULT_GRID_WIDTH))
        self.height_value = tk.StringVar(value=str(DEFAULT_GRID_HEIGHT))
        self.answer_value = tk.StringVar()
        self.legend_value = tk.StringVar()
        self.row_value = tk.StringVar(value="1")
        self.column_value = tk.StringVar(value="1")
        self.direction_value = tk.StringVar(value="horizontal")
        self.in_help_value = tk.BooleanVar(value=False)
        self.layout_value = tk.StringVar(value="swedish")
        self.status_value = tk.StringVar(value="Připravuji prázdné zadání…")

        self._configure_window()
        self._configure_styles()
        self._build_menu()
        self._build_content()
        self._watch_dimensions()
        self.root.after_idle(self.refresh_specification)

    def _configure_window(self) -> None:
        self.root.title("Křížovkář")
        self.root.geometry("1100x760")
        self.root.minsize(860, 640)
        self.root.option_add("*tearOff", False)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("TkDefaultFont", 22, "bold"))
        style.configure(
            "Step.TLabel",
            foreground="#175cd3",
            font=("TkDefaultFont", 10, "bold"),
        )
        style.configure("Section.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Muted.TLabel", foreground="#667085")
        style.configure("Error.TLabel", foreground="#b42318")
        style.configure("Success.TLabel", foreground="#067647")

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu)
        file_menu.add_command(
            label="Uložit zadání…",
            accelerator="Ctrl+S",
            command=self.save_specification,
        )
        file_menu.add_command(
            label="Vytvořit šablonu…",
            command=self.save_template,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Konec", command=self.root.destroy)
        menu.add_cascade(label="Soubor", menu=file_menu)
        self.root.configure(menu=menu)
        self.root.bind("<Control-s>", self._save_event)
        self.root.bind("<Command-s>", self._save_event)

    def _build_content(self) -> None:
        ttk.Label(
            self,
            text="PRVNÍ KROK  ·  ZADÁNÍ",
            style="Step.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(self, text="Křížovkář", style="Title.TLabel").grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(4, 0),
        )
        ttk.Label(
            self,
            text=(
                "Určete obsah křížovky nezávisle na navazujícím švédském "
                "nebo číslovaném rozvržení."
            ),
            style="Muted.TLabel",
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(2, 18),
        )

        editor = ttk.LabelFrame(self, text="Zadání křížovky", padding=16)
        editor.grid(row=3, column=0, sticky="nsew", padx=(0, 16))
        editor.columnconfigure(0, weight=1)

        ttk.Label(editor, text="Rozměr mřížky", style="Section.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        dimensions = ttk.Frame(editor)
        dimensions.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(dimensions, text="Sloupce").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            dimensions,
            from_=1,
            to=100,
            width=7,
            textvariable=self.width_value,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(dimensions, text="×").grid(row=1, column=1, padx=10)
        ttk.Label(dimensions, text="Řádky").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(
            dimensions,
            from_=1,
            to=100,
            width=7,
            textvariable=self.height_value,
        ).grid(row=1, column=2, sticky="w", pady=(3, 0))

        ttk.Separator(editor).grid(row=2, column=0, sticky="ew", pady=16)
        ttk.Label(editor, text="Umístěné heslo", style="Section.TLabel").grid(
            row=3,
            column=0,
            sticky="w",
        )
        form = ttk.Frame(editor)
        form.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        form.columnconfigure(0, weight=1)

        ttk.Label(form, text="Heslo").grid(row=0, column=0, sticky="w")
        self.answer_entry = ttk.Entry(form, textvariable=self.answer_value)
        self.answer_entry.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(3, 9))

        ttk.Label(form, text="Legenda").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.legend_value).grid(
            row=3,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(3, 9),
        )

        ttk.Label(form, text="Řádek").grid(row=4, column=0, sticky="w")
        ttk.Label(form, text="Sloupec").grid(row=4, column=1, sticky="w", padx=(8, 0))
        ttk.Spinbox(
            form,
            from_=1,
            to=100,
            width=7,
            textvariable=self.row_value,
        ).grid(row=5, column=0, sticky="w", pady=(3, 9))
        ttk.Spinbox(
            form,
            from_=1,
            to=100,
            width=7,
            textvariable=self.column_value,
        ).grid(row=5, column=1, sticky="w", padx=(8, 0), pady=(3, 9))

        ttk.Label(form, text="Směr").grid(row=6, column=0, sticky="w")
        directions = ttk.Frame(form)
        directions.grid(row=7, column=0, columnspan=3, sticky="w", pady=(3, 7))
        ttk.Radiobutton(
            directions,
            text="Vodorovně",
            variable=self.direction_value,
            value="horizontal",
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            directions,
            text="Svisle",
            variable=self.direction_value,
            value="vertical",
        ).grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Checkbutton(
            form,
            text="Zařadit odpověď do pomůcky",
            variable=self.in_help_value,
        ).grid(row=8, column=0, columnspan=3, sticky="w")

        form_actions = ttk.Frame(editor)
        form_actions.grid(row=5, column=0, sticky="ew", pady=(16, 0))
        form_actions.columnconfigure(0, weight=1)
        self.word_button = ttk.Button(
            form_actions,
            text="Přidat heslo",
            command=self.add_or_update_word,
        )
        self.word_button.grid(row=0, column=0, sticky="ew")
        self.cancel_edit_button = ttk.Button(
            form_actions,
            text="Zrušit úpravu",
            command=self.clear_word_form,
            state="disabled",
        )
        self.cancel_edit_button.grid(row=1, column=0, sticky="ew", pady=(7, 0))

        ttk.Label(
            editor,
            text="Tajenky doplní další rozšíření editoru zadání.",
            style="Muted.TLabel",
            wraplength=280,
        ).grid(row=6, column=0, sticky="w", pady=(18, 0))

        template_options = ttk.LabelFrame(
            editor,
            text="Navazující šablona",
            padding=(10, 8),
        )
        template_options.grid(row=7, column=0, sticky="ew", pady=(14, 0))
        ttk.Radiobutton(
            template_options,
            text="Švédská s vepsanými legendami",
            variable=self.layout_value,
            value="swedish",
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            template_options,
            text="Číslovaná s vnějšími legendami",
            variable=self.layout_value,
            value="numbered",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.save_button = ttk.Button(
            editor,
            text="Uložit zadání…",
            command=self.save_specification,
            state="disabled",
        )
        self.save_button.grid(row=8, column=0, sticky="ew", pady=(14, 0))
        self.template_button = ttk.Button(
            editor,
            text="Vytvořit šablonu…",
            command=self.save_template,
            state="disabled",
        )
        self.template_button.grid(row=9, column=0, sticky="ew", pady=(7, 0))

        workspace = ttk.Frame(self)
        workspace.grid(row=3, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)

        preview_frame = ttk.LabelFrame(workspace, text="Náhled zadání", padding=12)
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.preview = SpecificationPreview(preview_frame, width=650, height=390)
        self.preview.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            preview_frame,
            text="Modrá pole obsahují písmena; vybrané heslo je zvýrazněné.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(9, 0))

        words_frame = ttk.LabelFrame(workspace, text="Hesla v zadání", padding=12)
        words_frame.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        words_frame.columnconfigure(0, weight=1)
        tree_container = ttk.Frame(words_frame)
        tree_container.grid(row=0, column=0, sticky="ew")
        tree_container.columnconfigure(0, weight=1)
        self.words_tree = ttk.Treeview(
            tree_container,
            columns=("answer", "legend", "start", "direction", "help"),
            show="headings",
            height=7,
            selectmode="browse",
        )
        self.words_tree.heading("answer", text="Heslo")
        self.words_tree.heading("legend", text="Legenda")
        self.words_tree.heading("start", text="Začátek")
        self.words_tree.heading("direction", text="Směr")
        self.words_tree.heading("help", text="Pomůcka")
        self.words_tree.column("answer", width=100, stretch=False)
        self.words_tree.column("legend", width=230)
        self.words_tree.column("start", width=80, stretch=False, anchor="center")
        self.words_tree.column("direction", width=90, stretch=False)
        self.words_tree.column("help", width=65, stretch=False, anchor="center")
        self.words_tree.grid(row=0, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(
            tree_container,
            orient="vertical",
            command=self.words_tree.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.words_tree.configure(yscrollcommand=scrollbar.set)
        self.words_tree.bind("<<TreeviewSelect>>", self._word_selection_changed)
        self.words_tree.bind("<Double-1>", self._edit_event)

        list_actions = ttk.Frame(words_frame)
        list_actions.grid(row=1, column=0, sticky="e", pady=(8, 0))
        self.edit_button = ttk.Button(
            list_actions,
            text="Upravit",
            command=self.edit_selected_word,
            state="disabled",
        )
        self.edit_button.grid(row=0, column=0)
        self.remove_button = ttk.Button(
            list_actions,
            text="Odebrat",
            command=self.remove_selected_word,
            state="disabled",
        )
        self.remove_button.grid(row=0, column=1, padx=(8, 0))

        ttk.Separator(self).grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(18, 10),
        )
        self.status_label = ttk.Label(
            self,
            textvariable=self.status_value,
            style="Muted.TLabel",
            wraplength=1040,
        )
        self.status_label.grid(row=5, column=0, columnspan=2, sticky="w")

    def _watch_dimensions(self) -> None:
        self.width_value.trace_add("write", self._dimensions_changed)
        self.height_value.trace_add("write", self._dimensions_changed)

    def _dimensions_changed(self, *_args: str) -> None:
        self.refresh_specification()

    def _current_settings(self) -> SpecificationSettings:
        return parse_specification_settings(
            self.width_value.get(),
            self.height_value.get(),
        )

    def _selected_word_index(self) -> int | None:
        selection = self.words_tree.selection()
        return int(selection[0]) if selection else None

    def refresh_specification(self) -> bool:
        try:
            settings = self._current_settings()
        except GuiInputError as error:
            self._specification = None
            self.save_button.configure(state="disabled")
            self.template_button.configure(state="disabled")
            self.preview.clear_preview("Zadejte platný rozměr mřížky.")
            self._set_status(str(error), error=True)
            return False

        words = tuple(self._words)
        self.preview.show_draft(
            GridDimensions(width=settings.width, height=settings.height),
            words,
            self._selected_word_index(),
        )
        if not words:
            self._specification = None
            self.save_button.configure(state="disabled")
            self.template_button.configure(state="disabled")
            self._set_status(
                f"Mřížka {settings.width} × {settings.height} je připravena. "
                "Přidejte první heslo."
            )
            return False

        try:
            specification = create_specification(settings, words)
        except GuiInputError as error:
            self._specification = None
            self.save_button.configure(state="disabled")
            self.template_button.configure(state="disabled")
            self._set_status(f"Zadání není platné: {error}", error=True)
            return False

        self._specification = specification
        self.save_button.configure(state="normal")
        self.template_button.configure(state="normal")
        self._set_status(
            f"Zadání je připravené: {settings.width} × {settings.height}, "
            f"{_word_count_text(len(words))}."
        )
        return True

    def add_or_update_word(self) -> None:
        try:
            settings = self._current_settings()
            word = parse_word_placement(
                self.answer_value.get(),
                self.legend_value.get(),
                self.row_value.get(),
                self.column_value.get(),
                self.direction_value.get(),
                self.in_help_value.get(),
            )
            candidate_words = list(self._words)
            if self._editing_index is None:
                candidate_words.append(word)
            else:
                candidate_words[self._editing_index] = word
            create_specification(settings, tuple(candidate_words))
        except GuiInputError as error:
            self._show_action_error("Heslo nelze uložit", str(error))
            return

        self._words = candidate_words
        self._rebuild_word_tree()
        self.clear_word_form()
        self.refresh_specification()

    def _rebuild_word_tree(self) -> None:
        for item in self.words_tree.get_children():
            self.words_tree.delete(item)
        for word_index, word in enumerate(self._words):
            self.words_tree.insert(
                "",
                "end",
                iid=str(word_index),
                values=(
                    word.answer,
                    word.legend,
                    f"{word.start.row}, {word.start.column}",
                    _DIRECTION_LABELS[word.direction],
                    "Ano" if word.in_help else "Ne",
                ),
            )
        self._word_selection_changed()

    def _word_selection_changed(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> None:
        state = "normal" if self._selected_word_index() is not None else "disabled"
        self.edit_button.configure(state=state)
        self.remove_button.configure(state=state)
        self.refresh_specification()

    def edit_selected_word(self) -> None:
        word_index = self._selected_word_index()
        if word_index is None:
            return
        word = self._words[word_index]
        self._editing_index = word_index
        self.answer_value.set(word.answer)
        self.legend_value.set(word.legend)
        self.row_value.set(str(word.start.row))
        self.column_value.set(str(word.start.column))
        self.direction_value.set(word.direction)
        self.in_help_value.set(word.in_help)
        self.word_button.configure(text="Uložit změny hesla")
        self.cancel_edit_button.configure(state="normal")
        self.answer_entry.focus_set()
        self.answer_entry.selection_range(0, "end")

    def remove_selected_word(self) -> None:
        word_index = self._selected_word_index()
        if word_index is None:
            return
        del self._words[word_index]
        self._rebuild_word_tree()
        self.clear_word_form()
        self.refresh_specification()

    def clear_word_form(self) -> None:
        self._editing_index = None
        self.answer_value.set("")
        self.legend_value.set("")
        self.row_value.set("1")
        self.column_value.set("1")
        self.direction_value.set("horizontal")
        self.in_help_value.set(False)
        self.word_button.configure(text="Přidat heslo")
        self.cancel_edit_button.configure(state="disabled")
        for selected in self.words_tree.selection():
            self.words_tree.selection_remove(selected)
        self._word_selection_changed()
        self.answer_entry.focus_set()

    def save_specification(self) -> None:
        if not self.refresh_specification():
            message = (
                "Přidejte alespoň jedno heslo."
                if not self._words
                else self.status_value.get()
            )
            self._show_action_error("Zadání nelze uložit", message)
            return
        assert self._specification is not None
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Uložit zadání křížovky",
            initialfile="zadani.yaml",
            defaultextension=".yaml",
            filetypes=(
                ("YAML soubory", "*.yaml *.yml"),
                ("Všechny soubory", "*"),
            ),
            confirmoverwrite=False,
        )
        if not filename:
            return

        output = Path(filename)
        overwrite = output.exists()
        if overwrite and not messagebox.askyesno(
            "Přepsat zadání?",
            f"Soubor {output.name} už existuje. Chcete jej přepsat?",
            parent=self.root,
        ):
            return
        try:
            write_crossword_specification(
                self._specification,
                output,
                overwrite=overwrite,
            )
        except ModelError as error:
            self._show_action_error("Zadání nelze uložit", str(error))
            return

        self._set_status(f"Zadání uloženo: {output}", success=True)

    def save_template(self) -> None:
        if not self.refresh_specification():
            message = (
                "Přidejte alespoň jedno heslo."
                if not self._words
                else self.status_value.get()
            )
            self._show_action_error("Šablonu nelze vytvořit", message)
            return
        assert self._specification is not None
        layout = cast(SpecificationLayout, self.layout_value.get())
        try:
            template = create_template(self._specification, layout)
        except GuiInputError as error:
            self._show_action_error("Šablonu nelze vytvořit", str(error))
            return

        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Uložit šablonu křížovky",
            initialfile="sablona.yaml",
            defaultextension=".yaml",
            filetypes=(
                ("YAML soubory", "*.yaml *.yml"),
                ("Všechny soubory", "*"),
            ),
            confirmoverwrite=False,
        )
        if not filename:
            return

        output = Path(filename)
        overwrite = output.exists()
        if overwrite and not messagebox.askyesno(
            "Přepsat šablonu?",
            f"Soubor {output.name} už existuje. Chcete jej přepsat?",
            parent=self.root,
        ):
            return
        try:
            write_crossword_template(
                template,
                output,
                overwrite=overwrite,
            )
        except ModelError as error:
            self._show_action_error("Šablonu nelze uložit", str(error))
            return

        self._set_status(f"Šablona uložena: {output}", success=True)

    def _show_action_error(self, title: str, message: str) -> None:
        self._set_status(message, error=True)
        messagebox.showerror(title, message, parent=self.root)

    def _set_status(
        self,
        message: str,
        *,
        error: bool = False,
        success: bool = False,
    ) -> None:
        style = "Muted.TLabel"
        if error:
            style = "Error.TLabel"
        elif success:
            style = "Success.TLabel"
        self.status_value.set(message)
        self.status_label.configure(style=style)

    def _edit_event(self, _event: tk.Event[tk.Misc]) -> None:
        self.edit_selected_word()

    def _save_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.save_specification()
        return "break"


def main() -> int:
    """Spustí grafické rozhraní a vrátí návratový kód procesu."""

    _configure_tk_runtime()
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"chyba: grafické rozhraní nelze spustit: {error}", file=sys.stderr)
        return 2
    CrosswordApplication(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

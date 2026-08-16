"""Grafické rozhraní Křížovkáře postavené na Tk."""

from __future__ import annotations

import os
import sys
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import cast

from krizovkar.alphabet import split_answer_letters
from krizovkar.generator import (
    DEFAULT_GRID_HEIGHT,
    DEFAULT_GRID_WIDTH,
    GenerationError,
    SpecificationLayout,
    create_grid_from_template,
    generate_numbered_template,
    generate_swedish_template,
)
from krizovkar.localization import ngettext
from krizovkar.model import (
    Coordinate,
    CrosswordDocument,
    CrosswordGrid,
    CrosswordTemplate,
    EmptyCell,
    HelpCell,
    LegendCell,
    LetterCell,
    ModelError,
    SecretCell,
    WordSlot,
    create_crossword_document as make_crossword_document,
    dump_crossword_document,
    dump_crossword_template,
    load_crossword_document,
    load_crossword_document_kind,
    load_crossword_template,
    write_crossword_document,
    write_crossword_template,
)
from krizovkar.renderer import (
    DEFAULT_PAGE_FORMAT,
    SUPPORTED_PAGE_FORMATS,
    RenderError,
    render_pdf,
)

_MAX_TEMPLATE_DIMENSION = 50
_DIRECTION_LABELS = {
    "horizontal": "Vodorovně",
    "vertical": "Svisle",
}


class GuiInputError(ValueError):
    """Nastavení zadané v grafickém rozhraní není platné."""


@dataclass(frozen=True, slots=True)
class TemplateSettings:
    """Rozměr automaticky rozvrhované šablony."""

    width: int
    height: int


class PdfExportDialog(simpledialog.Dialog):
    """Vybere formát PDF před systémovým dialogem pro uložení."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        initial_page_format: str,
    ) -> None:
        self._initial_page_format = initial_page_format
        self._page_format_value: tk.StringVar
        super().__init__(parent, title)

    def body(self, master: tk.Frame) -> tk.Widget:
        master.configure(padx=16, pady=12)
        master.columnconfigure(0, weight=1)
        ttk.Label(
            master,
            text="Zvolte formát stránky pro tiskové PDF.",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(master, text="Formát stránky").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(12, 0),
        )
        self._page_format_value = tk.StringVar(
            master=master,
            value=self._initial_page_format,
        )
        page_format = ttk.Combobox(
            master,
            state="readonly",
            width=12,
            values=SUPPORTED_PAGE_FORMATS,
            textvariable=self._page_format_value,
        )
        page_format.grid(row=2, column=0, sticky="ew", pady=(3, 0))
        return page_format

    def buttonbox(self) -> None:
        buttons = ttk.Frame(self, padding=(16, 0, 16, 16))
        ttk.Button(
            buttons,
            text="Vybrat umístění…",
            command=self.ok,
            default="active",
            style="Primary.TButton",
        ).pack(side="right")
        ttk.Button(
            buttons,
            text="Zrušit",
            command=self.cancel,
        ).pack(side="right", padx=(0, 8))
        buttons.pack(fill="x")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def apply(self) -> None:
        self.result = self._page_format_value.get()


def _positive_integer(value: str, label: str) -> int:
    try:
        number = int(value.strip())
    except ValueError as error:
        raise GuiInputError(f"{label} musí být celé číslo.") from error
    if number < 1:
        raise GuiInputError(f"{label} musí být kladný.")
    return number


def parse_template_settings(width: str, height: str) -> TemplateSettings:
    """Převede a omezí rozměr automaticky rozvrhované šablony."""

    settings = TemplateSettings(
        width=_positive_integer(width, "Počet sloupců"),
        height=_positive_integer(height, "Počet řádků"),
    )
    if (
        settings.width > _MAX_TEMPLATE_DIMENSION
        or settings.height > _MAX_TEMPLATE_DIMENSION
    ):
        raise GuiInputError(
            f"Šablona může mít nejvýše {_MAX_TEMPLATE_DIMENSION} sloupců a řádků."
        )
    return settings


def create_blank_template(
    settings: TemplateSettings,
    layout: SpecificationLayout,
) -> CrosswordTemplate:
    """Vytvoří hustou prázdnou šablonu z rozvržení a rozměru."""

    if layout not in {"swedish", "numbered"}:
        raise GuiInputError(f"Nepodporovaná podoba šablony {layout!r}.")
    generator = (
        generate_numbered_template
        if layout == "numbered"
        else generate_swedish_template
    )
    try:
        return generator(width=settings.width, height=settings.height)
    except GenerationError as error:
        raise GuiInputError(str(error)) from error


def parse_slot_content(
    answer: str,
    clue: str,
    expected_length: int,
) -> tuple[str, str]:
    """Ověří odpověď a nápovědu zadávanou do jednoho slotu."""

    normalized_answer = answer.strip().upper()
    if not normalized_answer:
        raise GuiInputError("Vyplňte heslo.")
    try:
        letters = split_answer_letters(normalized_answer)
    except ValueError as error:
        raise GuiInputError(str(error)) from error
    if len(letters) != expected_length:
        raise GuiInputError(
            f"Vybrané místo má {_cell_count_text(expected_length)}, ale heslo "
            f"má {_cell_count_text(len(letters))}."
        )

    normalized_clue = clue.strip()
    if not normalized_clue:
        raise GuiInputError("Vyplňte nápovědu hesla.")
    return normalized_answer, normalized_clue


def slot_coordinates(slot: WordSlot) -> tuple[Coordinate, ...]:
    """Vrátí písmenná pole slotu v pořadí odpovědi."""

    row_step = 1 if slot.direction == "vertical" else 0
    column_step = 1 if slot.direction == "horizontal" else 0
    return tuple(
        Coordinate(
            row=slot.start.row + offset * row_step,
            column=slot.start.column + offset * column_step,
        )
        for offset in range(slot.length)
    )


def _template_slot(
    template: CrosswordTemplate,
    identifier: str,
) -> tuple[int, WordSlot]:
    for index, slot in enumerate(template.slots):
        if slot.identifier == identifier:
            return index, slot
    raise GuiInputError(f"Šablona neobsahuje místo {identifier!r}.")


def fill_template_slot(
    template: CrosswordTemplate,
    identifier: str,
    answer: str,
    clue: str,
) -> CrosswordTemplate:
    """Zapíše ručně zadané heslo do vybraného slotu dokumentu."""

    slot_index, slot = _template_slot(template, identifier)
    normalized_answer, normalized_clue = parse_slot_content(
        answer,
        clue,
        slot.length,
    )
    for other in template.slots:
        if other.identifier != identifier and other.answer == normalized_answer:
            raise GuiInputError(
                f"Heslo {normalized_answer!r} už je použité v jiném místě."
            )

    fixed_letters: dict[Coordinate, tuple[str, str]] = {}
    for other in template.slots:
        if other.identifier == identifier or other.answer is None:
            continue
        for coordinate, letter in zip(
            slot_coordinates(other),
            split_answer_letters(other.answer),
        ):
            fixed_letters[coordinate] = (letter, other.answer)

    for position, (coordinate, letter) in enumerate(
        zip(slot_coordinates(slot), split_answer_letters(normalized_answer)),
        start=1,
    ):
        fixed = fixed_letters.get(coordinate)
        if fixed is None or fixed[0] == letter:
            continue
        expected, crossing_answer = fixed
        raise GuiInputError(
            f"Na křížení s heslem {crossing_answer!r} musí být v "
            f"{position}. poli písmeno {expected!r}, ne {letter!r}."
        )

    slots = list(template.slots)
    slots[slot_index] = replace(
        slot,
        answer=normalized_answer,
        clue=normalized_clue,
    )
    result = replace(template, slots=tuple(slots))
    try:
        if isinstance(result, CrosswordDocument):
            dump_crossword_document(result, StringIO())
        else:
            dump_crossword_template(result, StringIO())
    except ModelError as error:
        raise GuiInputError(str(error)) from error
    return result


def clear_template_slot(
    template: CrosswordTemplate,
    identifier: str,
) -> CrosswordTemplate:
    """Odstraní ručně zadaný obsah jednoho slotu dokumentu."""

    slot_index, slot = _template_slot(template, identifier)
    slots = list(template.slots)
    slots[slot_index] = replace(
        slot,
        answer=None,
        clue=None,
        in_help=False,
    )
    return replace(template, slots=tuple(slots))


def template_slot_pattern(
    template: CrosswordTemplate,
    identifier: str,
) -> tuple[str | None, ...]:
    """Vrátí písmena známá z ostatních hesel křížících vybraný slot."""

    _, selected = _template_slot(template, identifier)
    fixed_letters: dict[Coordinate, str] = {}
    for slot in template.slots:
        if slot.identifier == identifier or slot.answer is None:
            continue
        for coordinate, letter in zip(
            slot_coordinates(slot),
            split_answer_letters(slot.answer),
        ):
            fixed_letters[coordinate] = letter
    return tuple(
        fixed_letters.get(coordinate) for coordinate in slot_coordinates(selected)
    )


def template_is_complete(template: CrosswordTemplate) -> bool:
    """Určí, zda mají všechny sloty odpověď i nápovědu."""

    return all(
        slot.answer is not None and slot.clue is not None for slot in template.slots
    )


def template_layout(template: CrosswordTemplate) -> SpecificationLayout:
    """Odvodí podobu dokumentu z umístění jeho legend."""

    if any(slot.legend_position is not None for slot in template.slots):
        return "swedish"
    return "numbered"


def _word_count_text(count: int) -> str:
    return f"{count} {ngettext('heslo', 'hesel', count)}"


def _cell_count_text(count: int) -> str:
    if count == 1:
        return "1 pole"
    if 2 <= count <= 4:
        return f"{count} pole"
    return f"{count} polí"


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


class CrosswordPreview(tk.Canvas):
    """Náhled šablony a jejího postupně doplňovaného obsahu."""

    _GRID_COLOR = "#667085"
    _SELECTED_FILL = "#bfdbfe"
    _LEGEND_FILL = "#fef3c7"
    _EMPTY_FILL = "#e2e8f0"
    _HELP_FILL = "#dcfce7"
    _LETTER_COLOR = "#101828"
    _MUTED_COLOR = "#667085"

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        super().__init__(
            master,
            background="#f8fafc",
            highlightbackground="#cbd5e1",
            highlightthickness=1,
            **kwargs,
        )
        self._crossword: CrosswordGrid | None = None
        self._show_letters = True
        self._selected_coordinates: frozenset[Coordinate] = frozenset()
        self._empty_message = "Vytvořte rozvržení mřížky."
        self._grid_geometry: tuple[float, float, float] | None = None
        self._cell_click_handler: Callable[[Coordinate], None] | None = None
        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._cell_clicked)

    def set_cell_click_handler(
        self,
        handler: Callable[[Coordinate], None],
    ) -> None:
        self._cell_click_handler = handler

    def show_crossword(
        self,
        crossword: CrosswordGrid,
        *,
        selected_coordinates: tuple[Coordinate, ...] = (),
        show_letters: bool = True,
    ) -> None:
        """Zobrazí role buněk, čísla, výběr a volitelně písmena."""

        self._crossword = crossword
        self._selected_coordinates = frozenset(selected_coordinates)
        self._show_letters = show_letters
        self._redraw()

    def clear_preview(self, message: str) -> None:
        self._crossword = None
        self._selected_coordinates = frozenset()
        self._empty_message = message
        self._grid_geometry = None
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.delete("all")
        crossword = self._crossword
        if crossword is None:
            self._grid_geometry = None
            self.create_text(
                max(self.winfo_width(), 2) / 2,
                max(self.winfo_height(), 2) / 2,
                text=self._empty_message,
                fill=self._MUTED_COLOR,
                width=max(self.winfo_width() - 48, 120),
                justify="center",
            )
            return

        canvas_width = max(self.winfo_width(), 2)
        canvas_height = max(self.winfo_height(), 2)
        available_width = max(canvas_width - 32, 1)
        available_height = max(canvas_height - 32, 1)
        cell_size = min(
            available_width / crossword.grid.width,
            available_height / crossword.grid.height,
            38,
        )
        grid_width = cell_size * crossword.grid.width
        grid_height = cell_size * crossword.grid.height
        left = (canvas_width - grid_width) / 2
        top = (canvas_height - grid_height) / 2
        self._grid_geometry = (left, top, cell_size)
        grid_cells = crossword.grid.cells

        for row in range(1, crossword.grid.height + 1):
            for column in range(1, crossword.grid.width + 1):
                x1 = left + (column - 1) * cell_size
                y1 = top + (row - 1) * cell_size
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                coordinate = Coordinate(row=row, column=column)
                cell = grid_cells[row - 1][column - 1]
                fill = "#ffffff"
                marker: str | None = None
                letter: str | None = None
                number: int | None = None
                bars: tuple[str, ...] = ()
                if isinstance(cell, LegendCell):
                    fill = self._LEGEND_FILL
                    marker = "N" if any(cell.texts) else "?"
                elif isinstance(cell, EmptyCell):
                    fill = self._EMPTY_FILL
                elif isinstance(cell, HelpCell):
                    fill = self._HELP_FILL
                    marker = "P"
                elif isinstance(cell, (LetterCell, SecretCell)):
                    letter = cell.value if self._show_letters else None
                    number = cell.number
                    bars = cell.bars
                    if coordinate in self._selected_coordinates:
                        fill = self._SELECTED_FILL

                self.create_rectangle(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=fill,
                    outline=self._GRID_COLOR,
                    width=1,
                )
                if isinstance(cell, EmptyCell) and cell_size >= 10:
                    self.create_line(
                        x1 + 2,
                        y1 + 2,
                        x2 - 2,
                        y2 - 2,
                        fill="#94a3b8",
                    )
                    self.create_line(
                        x2 - 2,
                        y1 + 2,
                        x1 + 2,
                        y2 - 2,
                        fill="#94a3b8",
                    )
                if marker is not None and cell_size >= 14:
                    self.create_text(
                        (x1 + x2) / 2,
                        (y1 + y2) / 2,
                        text=marker,
                        fill=self._MUTED_COLOR,
                        font=(
                            "TkDefaultFont",
                            max(7, int(cell_size * 0.3)),
                            "bold",
                        ),
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
                if number is not None and cell_size >= 18:
                    self.create_text(
                        x1 + 2,
                        y1 + 1,
                        text=str(number),
                        anchor="nw",
                        fill=self._LETTER_COLOR,
                        font=(
                            "TkDefaultFont",
                            max(5, int(cell_size * 0.2)),
                        ),
                    )
                if "right" in bars:
                    self.create_line(
                        x2,
                        y1,
                        x2,
                        y2,
                        fill=self._LETTER_COLOR,
                        width=3,
                    )
                if "bottom" in bars:
                    self.create_line(
                        x1,
                        y2,
                        x2,
                        y2,
                        fill=self._LETTER_COLOR,
                        width=3,
                    )

        self.create_rectangle(
            left,
            top,
            left + grid_width,
            top + grid_height,
            outline="#101828",
            width=2,
        )

    def _cell_clicked(self, event: tk.Event[tk.Misc]) -> None:
        if self._crossword is None or self._grid_geometry is None:
            return
        left, top, cell_size = self._grid_geometry
        column = int((event.x - left) // cell_size) + 1
        row = int((event.y - top) // cell_size) + 1
        if (
            event.x < left
            or event.y < top
            or row < 1
            or column < 1
            or row > self._crossword.grid.height
            or column > self._crossword.grid.width
        ):
            return
        handler = self._cell_click_handler
        if handler is not None:
            handler(Coordinate(row=row, column=column))


class ScrollablePanel(ttk.Frame):
    """Svisle posuvný panel pro delší krokový formulář."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        width: int,
        height: int,
    ) -> None:
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        background = ttk.Style(master).lookup("TFrame", "background")
        self.canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            background=background,
            borderwidth=0,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.content = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window(
            (0, 0),
            window=self.content,
            anchor="nw",
        )
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.content.bind("<Configure>", self._content_changed)
        self.content.bind("<MouseWheel>", self._scroll_mousewheel)
        self.canvas.bind("<Configure>", self._canvas_changed)
        self.canvas.bind("<MouseWheel>", self._scroll_mousewheel)

    def _content_changed(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_changed(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _scroll_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        direction = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(direction, "units")


def load_editable_document(
    source: str | Path,
) -> CrosswordTemplate | CrosswordDocument:
    """Načte druh editovatelného dokumentu určený jeho klíčem ``kind``."""

    kind = load_crossword_document_kind(source)
    if kind == "template":
        return load_crossword_template(source)
    if kind == "crossword":
        return load_crossword_document(source)
    raise ModelError(
        "grafické rozhraní otevírá pouze šablonu kind: template nebo "
        f"křížovku kind: crossword; soubor má kind: {kind!r}"
    )


class CrosswordApplication:
    """Spravuje životní cyklus samostatných dokumentových oken."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._windows: list[CrosswordDocumentWindow] = []
        self.root.withdraw()

    def new_template_document(self) -> CrosswordDocumentWindow:
        template = create_blank_template(
            TemplateSettings(DEFAULT_GRID_WIDTH, DEFAULT_GRID_HEIGHT),
            "swedish",
        )
        return self._open_window(template, dirty=True)

    def new_crossword_document(
        self,
        template: CrosswordTemplate,
    ) -> CrosswordDocumentWindow:
        return self._open_window(
            make_crossword_document(template),
            dirty=True,
        )

    def choose_document(
        self,
        *,
        parent: tk.Misc,
    ) -> CrosswordDocumentWindow | None:
        filename = filedialog.askopenfilename(
            parent=parent,
            title="Otevřít dokument Křížovkáře",
            filetypes=(
                ("YAML soubory", "*.yaml *.yml"),
                ("Všechny soubory", "*"),
            ),
        )
        if not filename:
            return None
        return self.open_document(Path(filename), parent=parent)

    def open_document(
        self,
        source: Path,
        *,
        parent: tk.Misc,
    ) -> CrosswordDocumentWindow | None:
        try:
            document = load_editable_document(source)
        except ModelError as error:
            messagebox.showerror(
                "Dokument nelze otevřít",
                str(error),
                parent=parent,
            )
            return None
        return self._open_window(document, path=source, dirty=False)

    def _open_window(
        self,
        document: CrosswordTemplate | CrosswordDocument,
        *,
        path: Path | None = None,
        dirty: bool,
    ) -> CrosswordDocumentWindow:
        window_root = tk.Toplevel(self.root)
        window = CrosswordDocumentWindow(
            window_root,
            application=self,
            document=document,
            path=path,
            dirty=dirty,
        )
        self._windows.append(window)
        return window

    def close_window(self, window: CrosswordDocumentWindow) -> None:
        if window in self._windows:
            self._windows.remove(window)
        window.root.destroy()
        if not self._windows:
            self.root.destroy()


class CrosswordDocumentWindow(ttk.Frame):
    """Jedno viditelné okno svázané s jedním YAML dokumentem."""

    def __init__(
        self,
        root: tk.Toplevel,
        *,
        application: CrosswordApplication,
        document: CrosswordTemplate | CrosswordDocument,
        path: Path | None,
        dirty: bool,
    ) -> None:
        super().__init__(root, padding=(24, 18))
        self.root = root
        self.application = application
        self._document_kind = document.kind
        self._path = path
        self._dirty = dirty
        self._base_template = document if document.kind == "template" else None
        self._template = document if document.kind == "crossword" else None
        self._grid: CrosswordGrid | None = None
        layout = template_layout(document)
        self._layout = layout if document.kind == "template" else None
        self._crossword_layout = (
            layout if document.kind == "crossword" else None
        )
        self._selected_slot_identifier: str | None = None

        self.width_value = tk.StringVar(value=str(document.grid.width))
        self.height_value = tk.StringVar(value=str(document.grid.height))
        self.layout_value = tk.StringVar(value=layout)
        self.layout_help_value = tk.StringVar()
        self.answer_value = tk.StringVar()
        self.clue_value = tk.StringVar()
        self.slot_title_value = tk.StringVar(value="Vyberte heslo.")
        self.slot_pattern_value = tk.StringVar(value="Vzor z křížení: —")
        self.progress_value = tk.StringVar()
        self._page_format = DEFAULT_PAGE_FORMAT
        self.template_status_value = tk.StringVar(value="Šablona je otevřená.")
        self.crossword_status_value = tk.StringVar(
            value="Křížovka je otevřená."
        )

        self._configure_window()
        self._configure_styles()
        self._build_menu()
        self._build_content()
        if self._document_kind == "template":
            self._watch_inputs()
            self._refresh_template_view()
        else:
            self._rebuild_slot_tree()
            self._refresh_crossword_view()
        self._update_title()

    def _configure_window(self) -> None:
        self.root.geometry("1220x850")
        self.root.minsize(980, 700)
        self.root.option_add("*tearOff", False)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Primary.TButton", font=("TkDefaultFont", 10, "bold"))
        style.configure("Muted.TLabel", foreground="#667085")
        style.configure("Error.TLabel", foreground="#b42318")
        style.configure("Success.TLabel", foreground="#067647")

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        self.file_menu = tk.Menu(menu)
        self.file_menu.add_command(
            label="Nová šablona",
            accelerator="Ctrl+N",
            command=self.application.new_template_document,
        )
        self.file_menu.add_command(
            label="Otevřít…",
            accelerator="Ctrl+O",
            command=lambda: self.application.choose_document(parent=self.root),
        )
        self.file_menu.add_separator()
        self.file_menu.add_command(
            label="Uložit",
            accelerator="Ctrl+S",
            command=self.save_current_document_data,
        )
        self.file_menu.add_command(
            label="Uložit jako…",
            accelerator="Ctrl+Shift+S",
            command=self.save_document_as,
        )
        self.file_menu.add_separator()
        self.export_menu = tk.Menu(self.file_menu)
        self._add_export_actions()
        self.file_menu.add_cascade(label="Exportovat", menu=self.export_menu)
        self.file_menu.add_separator()
        self.file_menu.add_command(
            label="Zavřít okno",
            accelerator="Ctrl+W",
            command=self.request_close,
        )
        menu.add_cascade(label="Soubor", menu=self.file_menu)
        self.root.configure(menu=menu)
        self.root.bind("<Control-n>", self._new_event)
        self.root.bind("<Command-n>", self._new_event)
        self.root.bind("<Control-o>", self._open_event)
        self.root.bind("<Command-o>", self._open_event)
        self.root.bind("<Control-s>", self._save_event)
        self.root.bind("<Command-s>", self._save_event)
        self.root.bind("<Control-Shift-S>", self._save_as_event)
        self.root.bind("<Command-Shift-S>", self._save_as_event)
        self.root.bind("<Control-w>", self._close_event)
        self.root.bind("<Command-w>", self._close_event)

    def _add_export_actions(self) -> None:
        if self._document_kind == "template":
            self.export_menu.add_command(
                label="Šablonu k tisku (PDF)…",
                command=self.save_blank_template_pdf,
            )
            return
        self.export_menu.add_command(
            label="Křížovku bez písmen (PDF)…",
            command=self.save_crossword_pdf,
            state="disabled",
        )
        self.export_menu.add_command(
            label="Řešení s písmeny (PDF)…",
            command=self.save_solution_pdf,
            state="disabled",
        )

    def _build_content(self) -> None:
        document_frame = ttk.Frame(self, padding=14)
        document_frame.grid(row=0, column=0, sticky="nsew")
        if self._document_kind == "template":
            self.template_tab = document_frame
            self._build_template_document()
        else:
            self.crossword_tab = document_frame
            self._build_crossword_document()

    def _build_template_document(self) -> None:
        tab = self.template_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(tab, width=350)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        sidebar.columnconfigure(0, weight=1)

        properties = ttk.LabelFrame(
            sidebar,
            text="Vlastnosti šablony",
            padding=14,
        )
        properties.grid(row=0, column=0, sticky="ew")
        properties.columnconfigure(0, weight=1)

        dimensions = ttk.Frame(properties)
        dimensions.grid(row=0, column=0, sticky="w")
        ttk.Label(dimensions, text="Sloupce").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            dimensions,
            from_=1,
            to=_MAX_TEMPLATE_DIMENSION,
            width=7,
            textvariable=self.width_value,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(dimensions, text="×").grid(row=1, column=1, padx=10)
        ttk.Label(dimensions, text="Řádky").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(
            dimensions,
            from_=1,
            to=_MAX_TEMPLATE_DIMENSION,
            width=7,
            textvariable=self.height_value,
        ).grid(row=1, column=2, sticky="w", pady=(3, 0))

        ttk.Radiobutton(
            properties,
            text="Švédská – nápovědy přímo v mřížce",
            variable=self.layout_value,
            value="swedish",
        ).grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Radiobutton(
            properties,
            text="Číslovaná – nápovědy pod mřížkou",
            variable=self.layout_value,
            value="numbered",
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(
            properties,
            textvariable=self.layout_help_value,
            style="Muted.TLabel",
            wraplength=310,
            justify="left",
        ).grid(row=3, column=0, sticky="w", pady=(6, 0))

        self.create_template_button = ttk.Button(
            properties,
            text="Aktualizovat šablonu",
            command=self.create_new_template,
            style="Primary.TButton",
        )
        self.create_template_button.grid(
            row=4,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        self.create_crossword_button = ttk.Button(
            sidebar,
            text="Vytvořit křížovku podle této šablony",
            command=self.create_crossword_from_template,
            state="disabled",
            style="Primary.TButton",
        )
        self.create_crossword_button.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(12, 0),
        )

        preview_frame = ttk.LabelFrame(tab, text="Náhled šablony", padding=12)
        preview_frame.grid(row=0, column=1, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.template_preview = CrosswordPreview(
            preview_frame,
            width=680,
            height=570,
        )
        self.template_preview.grid(row=0, column=0, sticky="nsew")
        self.template_status_label = ttk.Label(
            preview_frame,
            textvariable=self.template_status_value,
            style="Muted.TLabel",
            wraplength=680,
        )
        self.template_status_label.grid(
            row=1,
            column=0,
            sticky="w",
            pady=(10, 0),
        )

    def _build_crossword_document(self) -> None:
        tab = self.crossword_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        controls_panel = ScrollablePanel(tab, width=360, height=650)
        controls_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        controls = controls_panel.content

        document = ttk.LabelFrame(
            controls,
            text="Dokument křížovky",
            padding=14,
        )
        document.pack(fill="x")
        document.columnconfigure(0, weight=1)
        ttk.Label(
            document,
            textvariable=self.progress_value,
            style="Muted.TLabel",
            wraplength=310,
        ).grid(row=0, column=0, sticky="w")

        editor = ttk.LabelFrame(
            controls,
            text="Vybrané heslo",
            padding=14,
        )
        editor.pack(fill="x", pady=(12, 0))
        editor.columnconfigure(0, weight=1)
        self._build_crossword_editor(editor)

        workspace = ttk.Frame(tab)
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)
        self._build_crossword_preview(workspace)
        self._build_slot_list(workspace)
        self.crossword_status_label = ttk.Label(
            workspace,
            textvariable=self.crossword_status_value,
            style="Muted.TLabel",
            wraplength=660,
        )
        self.crossword_status_label.grid(
            row=2,
            column=0,
            sticky="w",
            pady=(10, 0),
        )

    def _build_crossword_editor(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            textvariable=self.slot_title_value,
            wraplength=310,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            parent,
            textvariable=self.slot_pattern_value,
            style="Muted.TLabel",
            wraplength=310,
        ).grid(row=1, column=0, sticky="w", pady=(3, 7))

        ttk.Label(parent, text="Heslo (odpověď)").grid(
            row=2,
            column=0,
            sticky="w",
        )
        self.answer_entry = ttk.Entry(
            parent,
            textvariable=self.answer_value,
            state="disabled",
        )
        self.answer_entry.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(3, 7),
        )
        ttk.Label(parent, text="Nápověda (legenda)").grid(
            row=4,
            column=0,
            sticky="w",
        )
        self.clue_entry = ttk.Entry(
            parent,
            textvariable=self.clue_value,
            state="disabled",
        )
        self.clue_entry.grid(
            row=5,
            column=0,
            sticky="ew",
            pady=(3, 8),
        )

        actions = ttk.Frame(parent)
        actions.grid(row=6, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.save_slot_button = ttk.Button(
            actions,
            text="Uložit heslo",
            command=self.save_selected_slot,
            state="disabled",
            style="Primary.TButton",
        )
        self.save_slot_button.grid(row=0, column=0, sticky="ew")
        self.clear_slot_button = ttk.Button(
            actions,
            text="Vymazat heslo",
            command=self.clear_selected_slot,
            state="disabled",
        )
        self.clear_slot_button.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(6, 0),
        )

    def _build_crossword_preview(self, parent: ttk.Frame) -> None:
        preview_frame = ttk.LabelFrame(
            parent,
            text="Náhled mřížky",
            padding=12,
        )
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.crossword_preview = CrosswordPreview(
            preview_frame,
            width=620,
            height=390,
        )
        self.crossword_preview.grid(row=0, column=0, sticky="nsew")
        self.crossword_preview.set_cell_click_handler(self._preview_cell_clicked)
        ttk.Label(
            preview_frame,
            text=(
                "Kliknutím na písmenné pole vyberete jeho vodorovné nebo "
                "svislé heslo; opakovaný klik mezi nimi přepne."
            ),
            style="Muted.TLabel",
            wraplength=640,
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

    def _build_slot_list(self, parent: ttk.Frame) -> None:
        slots_frame = ttk.LabelFrame(
            parent,
            text="Místa pro hesla",
            padding=12,
        )
        slots_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        slots_frame.columnconfigure(0, weight=1)
        container = ttk.Frame(slots_frame)
        container.grid(row=0, column=0, sticky="ew")
        container.columnconfigure(0, weight=1)
        self.slots_tree = ttk.Treeview(
            container,
            columns=("slot", "length", "answer", "clue"),
            show="headings",
            height=7,
            selectmode="browse",
        )
        self.slots_tree.heading("slot", text="Místo")
        self.slots_tree.heading("length", text="Délka")
        self.slots_tree.heading("answer", text="Heslo")
        self.slots_tree.heading("clue", text="Nápověda")
        self.slots_tree.column("slot", width=115, stretch=False)
        self.slots_tree.column("length", width=60, stretch=False, anchor="center")
        self.slots_tree.column("answer", width=120, stretch=False)
        self.slots_tree.column("clue", width=250)
        self.slots_tree.grid(row=0, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.slots_tree.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.slots_tree.configure(yscrollcommand=scrollbar.set)
        self.slots_tree.bind("<<TreeviewSelect>>", self._slot_selection_changed)

    def _watch_inputs(self) -> None:
        self.width_value.trace_add("write", self._template_input_changed)
        self.height_value.trace_add("write", self._template_input_changed)
        self.layout_value.trace_add("write", self._template_input_changed)
        self._template_input_changed()

    @staticmethod
    def _layout_description(layout: str) -> str:
        if layout == "numbered":
            return (
                "Všechna pole zůstávají pro písmena; nápovědy budou "
                "očíslované a vysázené pod mřížkou."
            )
        return (
            "Místa pro nápovědy jsou součástí mřížky a určují začátky "
            "vodorovných i svislých hesel."
        )

    def _template_input_changed(self, *_args: str) -> None:
        layout = self.layout_value.get()
        self.layout_help_value.set(self._layout_description(layout))
        if self._base_template is None:
            return
        try:
            settings = parse_template_settings(
                self.width_value.get(),
                self.height_value.get(),
            )
            changed = (
                settings.width != self._base_template.grid.width
                or settings.height != self._base_template.grid.height
                or layout != self._layout
            )
        except GuiInputError:
            changed = True
        if changed:
            self._set_template_status(
                "Hodnoty ve formuláři se liší od zobrazené šablony."
            )

    def create_new_template(self) -> None:
        try:
            settings = parse_template_settings(
                self.width_value.get(),
                self.height_value.get(),
            )
            layout = cast(SpecificationLayout, self.layout_value.get())
            template = create_blank_template(settings, layout)
        except GuiInputError as error:
            self._show_action_error(
                "Šablonu nelze vytvořit",
                str(error),
                document="template",
            )
            return

        self._base_template = template
        self._layout = layout
        self._set_dirty(True)
        self._refresh_template_view()
        self._set_template_status(
            f"Šablona {settings.width} × {settings.height} · "
            f"{_word_count_text(len(template.slots))}.",
            success=True,
        )

    def create_crossword_from_template(self) -> None:
        if self._base_template is None:
            self._show_action_error(
                "Křížovku nelze vytvořit",
                "Dokument šablony zatím není připravený.",
                document="template",
            )
            return
        self.application.new_crossword_document(self._base_template)
        self._set_template_status(
            "Křížovka podle této šablony byla otevřena v novém okně.",
            success=True,
        )

    def _refresh_file_menu(self) -> None:
        if self._document_kind == "template":
            self.file_menu.entryconfigure(
                3,
                label="Uložit šablonu",
            )
            self.file_menu.entryconfigure(
                4,
                label="Uložit šablonu jako…",
            )
            template_state = (
                "normal" if self._base_template is not None else "disabled"
            )
            self.export_menu.entryconfigure(
                0,
                state=template_state,
            )
            return

        template = self._template
        complete = template is not None and template_is_complete(template)
        self.file_menu.entryconfigure(
            3,
            label="Uložit křížovku",
        )
        self.file_menu.entryconfigure(
            4,
            label="Uložit křížovku jako…",
        )
        result_state = "normal" if complete else "disabled"
        self.export_menu.entryconfigure(
            0,
            state=result_state,
        )
        self.export_menu.entryconfigure(
            1,
            state=result_state,
        )

    def _refresh_template_view(self) -> None:
        if self._base_template is None:
            self.template_preview.clear_preview("Šablona zatím není vytvořená.")
            self.create_crossword_button.configure(state="disabled")
            self._refresh_file_menu()
            return
        self.template_preview.show_crossword(
            create_grid_from_template(self._base_template),
            show_letters=False,
        )
        self.create_crossword_button.configure(state="normal")
        self._refresh_file_menu()

    def _slot_label(self, selected: WordSlot) -> str:
        assert self._template is not None
        number = 0
        for slot in self._template.slots:
            if slot.direction == selected.direction:
                number += 1
            if slot.identifier == selected.identifier:
                return f"{_DIRECTION_LABELS[slot.direction]} {number}"
        return selected.identifier

    def _rebuild_slot_tree(self) -> None:
        selected_identifier = self._selected_slot_identifier
        for item in self.slots_tree.get_children():
            self.slots_tree.delete(item)
        template = self._template
        if template is None:
            self._slot_selection_changed()
            return
        for slot in template.slots:
            self.slots_tree.insert(
                "",
                "end",
                iid=slot.identifier,
                values=(
                    self._slot_label(slot),
                    slot.length,
                    slot.answer or "—",
                    slot.clue or "—",
                ),
            )
        identifiers = {slot.identifier for slot in template.slots}
        if selected_identifier not in identifiers:
            selected_identifier = template.slots[0].identifier
        self.slots_tree.selection_set(selected_identifier)
        self.slots_tree.focus(selected_identifier)
        self.slots_tree.see(selected_identifier)
        self._selected_slot_identifier = selected_identifier
        self._slot_selection_changed()

    def _selected_slot(self) -> WordSlot | None:
        if self._template is None or self._selected_slot_identifier is None:
            return None
        try:
            _, slot = _template_slot(
                self._template,
                self._selected_slot_identifier,
            )
        except GuiInputError:
            return None
        return slot

    def _slot_selection_changed(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> None:
        selection = self.slots_tree.selection()
        if not selection or self._template is None:
            self._selected_slot_identifier = None
            self.slot_title_value.set("Vyberte místo v náhledu nebo seznamu.")
            self.slot_pattern_value.set("Vzor z křížení: —")
            self.answer_value.set("")
            self.clue_value.set("")
            self._set_slot_form_state("disabled")
            self._refresh_crossword_preview()
            return

        self._selected_slot_identifier = selection[0]
        slot = self._selected_slot()
        if slot is None:
            return
        self.slot_title_value.set(
            f"{self._slot_label(slot)} · {_cell_count_text(slot.length)}"
        )
        pattern = template_slot_pattern(self._template, slot.identifier)
        self.slot_pattern_value.set(
            "Vzor z křížení: "
            + " ".join(letter if letter is not None else "·" for letter in pattern)
        )
        self.answer_value.set(slot.answer or "")
        self.clue_value.set(slot.clue or "")
        self._set_slot_form_state("normal")
        self.clear_slot_button.configure(
            state="normal" if slot.answer is not None else "disabled"
        )
        self._refresh_crossword_preview()

    def _set_slot_form_state(self, state: str) -> None:
        self.answer_entry.configure(state=state)
        self.clue_entry.configure(state=state)
        self.save_slot_button.configure(state=state)
        if state == "disabled":
            self.clear_slot_button.configure(state="disabled")

    def _preview_cell_clicked(self, coordinate: Coordinate) -> None:
        template = self._template
        if template is None:
            return
        candidates = [
            slot.identifier
            for slot in template.slots
            if coordinate in slot_coordinates(slot)
        ]
        if not candidates:
            return
        current = self._selected_slot_identifier
        if current in candidates:
            selected = candidates[(candidates.index(current) + 1) % len(candidates)]
        else:
            selected = next(
                (
                    identifier
                    for identifier in candidates
                    if _template_slot(template, identifier)[1].answer is None
                ),
                candidates[0],
            )
        self.slots_tree.selection_set(selected)
        self.slots_tree.focus(selected)
        self.slots_tree.see(selected)
        self._selected_slot_identifier = selected
        self._slot_selection_changed()

    def save_selected_slot(self) -> None:
        template = self._template
        identifier = self._selected_slot_identifier
        if template is None or identifier is None:
            self._show_action_error(
                "Heslo nelze uložit",
                "Vyberte nejprve místo v náhledu nebo seznamu.",
                document="crossword",
            )
            return
        try:
            self._template = fill_template_slot(
                template,
                identifier,
                self.answer_value.get(),
                self.clue_value.get(),
            )
        except GuiInputError as error:
            self._show_action_error(
                "Heslo nelze uložit",
                str(error),
                document="crossword",
            )
            return
        self._set_dirty(True)
        self._rebuild_slot_tree()
        self._refresh_crossword_view()
        slot = self._selected_slot()
        if slot is None:
            return
        self._set_crossword_status(
            f"Heslo {slot.answer!r} bylo uloženo. "
            f"Vyplněno {_word_count_text(self._filled_slot_count())} "
            f"z {_word_count_text(len(self._template.slots))}."
        )

    def clear_selected_slot(self) -> None:
        template = self._template
        identifier = self._selected_slot_identifier
        if template is None or identifier is None:
            return
        self._template = clear_template_slot(template, identifier)
        self._set_dirty(True)
        self._rebuild_slot_tree()
        self._refresh_crossword_view()
        self._set_crossword_status("Heslo bylo z vybraného místa odstraněno.")

    def _filled_slot_count(self) -> int:
        if self._template is None:
            return 0
        return sum(slot.answer is not None for slot in self._template.slots)

    def _refresh_crossword_view(self) -> None:
        self._refresh_crossword_preview()
        template = self._template
        if template is None:
            self.progress_value.set("Křížovka zatím není vytvořená.")
            self._selected_slot_identifier = None
            self.slot_title_value.set("Křížovka zatím není vytvořená.")
            self.slot_pattern_value.set("Vzor z křížení: —")
            self.answer_value.set("")
            self.clue_value.set("")
            self._set_slot_form_state("disabled")
            self._refresh_file_menu()
            return
        filled = self._filled_slot_count()
        remaining = len(template.slots) - filled
        layout = (
            "číslovaná" if self._crossword_layout == "numbered" else "švédská"
        )
        document = (
            f"Křížovka {template.grid.width} × {template.grid.height} · {layout}. "
        )
        if remaining:
            self.progress_value.set(
                document + f"Vyplněno {_word_count_text(filled)} z "
                f"{_word_count_text(len(template.slots))}; zbývá "
                f"{_word_count_text(remaining)}."
            )
        else:
            self.progress_value.set(
                document + f"Všech {_word_count_text(filled)} je vyplněno."
            )
        self._refresh_file_menu()

    def _refresh_crossword_preview(self) -> None:
        template = self._template
        if template is None:
            self._grid = None
            self.crossword_preview.clear_preview("Křížovka zatím není vytvořená.")
            return
        self._grid = create_grid_from_template(template)
        slot = self._selected_slot()
        selected_coordinates = slot_coordinates(slot) if slot is not None else ()
        self.crossword_preview.show_crossword(
            self._grid,
            selected_coordinates=selected_coordinates,
            show_letters=True,
        )

    def _choose_output(
        self,
        *,
        title: str,
        initialfile: str,
        extension: str,
        filetypes: tuple[tuple[str, str], ...],
        overwrite_title: str,
    ) -> tuple[Path, bool] | None:
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title=title,
            initialfile=initialfile,
            defaultextension=extension,
            filetypes=filetypes,
            confirmoverwrite=False,
        )
        if not filename:
            return None

        output = Path(filename)
        overwrite = output.exists()
        if overwrite and not messagebox.askyesno(
            overwrite_title,
            f"Soubor {output.name} už existuje. Chcete jej přepsat?",
            parent=self.root,
        ):
            return None
        return output, overwrite

    def _complete_grid_or_error(self) -> CrosswordGrid | None:
        template = self._template
        if template is None:
            self._show_action_error(
                "Křížovka není připravena",
                "Dokument křížovky zatím není vytvořený.",
                document="crossword",
            )
            return None
        if not template_is_complete(template):
            remaining = len(template.slots) - self._filled_slot_count()
            self._show_action_error(
                "Křížovka není připravena",
                f"Doplňte ještě {_word_count_text(remaining)}.",
                document="crossword",
            )
            return None
        return create_grid_from_template(template)

    def save_crossword_pdf(self) -> None:
        grid = self._complete_grid_or_error()
        if grid is None:
            return
        self._save_pdf(
            grid,
            filled=False,
            title="Exportovat křížovku bez písmen",
            initialfile="krizovka.pdf",
            success_message="Křížovka bez písmen byla uložena",
            document="crossword",
        )

    def save_solution_pdf(self) -> None:
        grid = self._complete_grid_or_error()
        if grid is None:
            return
        self._save_pdf(
            grid,
            filled=True,
            title="Exportovat řešení s písmeny",
            initialfile="reseni.pdf",
            success_message="Řešení bylo uloženo",
            document="crossword",
        )

    def save_blank_template_pdf(self) -> None:
        if self._base_template is None:
            self._show_action_error(
                "Šablona není připravena",
                "Dokument šablony zatím není vytvořený.",
                document="template",
            )
            return
        self._save_pdf(
            create_grid_from_template(self._base_template),
            filled=False,
            title="Exportovat šablonu k tisku",
            initialfile="sablona.pdf",
            success_message="Šablona k tisku byla uložena",
            document="template",
        )

    def _choose_page_format(self, *, title: str) -> str | None:
        dialog = PdfExportDialog(
            self.root,
            title=title,
            initial_page_format=self._page_format,
        )
        page_format = cast(str | None, dialog.result)
        if page_format is not None:
            self._page_format = page_format
        return page_format

    def _save_pdf(
        self,
        crossword: CrosswordGrid,
        *,
        filled: bool,
        title: str,
        initialfile: str,
        success_message: str,
        document: str,
    ) -> None:
        page_format = self._choose_page_format(title=title)
        if page_format is None:
            return
        selected = self._choose_output(
            title=title,
            initialfile=initialfile,
            extension=".pdf",
            filetypes=(("PDF soubory", "*.pdf"), ("Všechny soubory", "*")),
            overwrite_title="Přepsat PDF?",
        )
        if selected is None:
            return
        output, overwrite = selected

        self._set_document_status(document, "Vytvářím PDF…")
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            render_pdf(
                crossword,
                output,
                overwrite=overwrite,
                page_format=page_format,
                filled=filled,
            )
        except RenderError as error:
            self._show_action_error(
                "PDF nelze vytvořit",
                str(error),
                document=document,
            )
            return
        finally:
            self.root.configure(cursor="")
        self._set_document_status(
            document,
            f"{success_message}: {output}",
            success=True,
        )

    def _document(self) -> CrosswordTemplate | CrosswordDocument:
        if self._document_kind == "template":
            assert self._base_template is not None
            return self._base_template
        assert isinstance(self._template, CrosswordDocument)
        return self._template

    def save_document(self) -> bool:
        if self._path is None:
            return self.save_document_as()
        return self._write_document(self._path, overwrite=True)

    def save_document_as(self) -> bool:
        document_label = (
            "šablonu" if self._document_kind == "template" else "křížovku"
        )
        if self._path is not None:
            initialfile = self._path.name
        elif self._document_kind == "template":
            initialfile = "sablona.yaml"
        else:
            initialfile = "krizovka.yaml"
        selected = self._choose_output(
            title=f"Uložit {document_label} jako",
            initialfile=initialfile,
            extension=".yaml",
            filetypes=(
                ("YAML soubory", "*.yaml *.yml"),
                ("Všechny soubory", "*"),
            ),
            overwrite_title="Přepsat datový soubor?",
        )
        if selected is None:
            return False
        output, overwrite = selected
        return self._write_document(output, overwrite=overwrite)

    def _write_document(self, output: Path, *, overwrite: bool) -> bool:
        document = self._document()
        try:
            if isinstance(document, CrosswordDocument):
                write_crossword_document(
                    document,
                    output,
                    overwrite=overwrite,
                )
            else:
                write_crossword_template(
                    document,
                    output,
                    overwrite=overwrite,
                )
        except ModelError as error:
            self._show_action_error(
                "Dokument nelze uložit",
                str(error),
                document=self._document_kind,
            )
            return False
        self._path = output
        self._set_dirty(False)
        subject = (
            "Šablona" if self._document_kind == "template" else "Křížovka"
        )
        self._set_document_status(
            self._document_kind,
            f"{subject} byla uložena: {output}",
            success=True,
        )
        return True

    def save_current_document_data(self) -> bool:
        return self.save_document()

    def _show_action_error(
        self,
        title: str,
        message: str,
        *,
        document: str,
    ) -> None:
        self._set_document_status(document, message, error=True)
        messagebox.showerror(title, message, parent=self.root)

    @staticmethod
    def _status_style(*, error: bool, success: bool) -> str:
        if error:
            return "Error.TLabel"
        if success:
            return "Success.TLabel"
        return "Muted.TLabel"

    def _set_template_status(
        self,
        message: str,
        *,
        error: bool = False,
        success: bool = False,
    ) -> None:
        self.template_status_value.set(message)
        self.template_status_label.configure(
            style=self._status_style(error=error, success=success)
        )

    def _set_crossword_status(
        self,
        message: str,
        *,
        error: bool = False,
        success: bool = False,
    ) -> None:
        self.crossword_status_value.set(message)
        self.crossword_status_label.configure(
            style=self._status_style(error=error, success=success)
        )

    def _set_document_status(
        self,
        document: str,
        message: str,
        *,
        error: bool = False,
        success: bool = False,
    ) -> None:
        if document == "template":
            self._set_template_status(message, error=error, success=success)
        else:
            self._set_crossword_status(message, error=error, success=success)

    def _update_title(self) -> None:
        if self._path is not None:
            name = self._path.name
        elif self._document_kind == "template":
            name = "Nová šablona"
        else:
            name = "Nová křížovka"
        marker = "*" if self._dirty else ""
        self.root.title(f"{marker}{name} — Křížovkář")

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._update_title()

    def request_close(self) -> None:
        if self._dirty:
            name = self._path.name if self._path is not None else "nový dokument"
            save = messagebox.askyesnocancel(
                "Uložit změny?",
                f"Dokument {name} obsahuje neuložené změny. "
                "Chcete je před zavřením uložit?",
                parent=self.root,
            )
            if save is None:
                return
            if save and not self.save_document():
                return
        self.application.close_window(self)

    def _new_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.application.new_template_document()
        return "break"

    def _open_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.application.choose_document(parent=self.root)
        return "break"

    def _save_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.save_current_document_data()
        return "break"

    def _save_as_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.save_document_as()
        return "break"

    def _close_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.request_close()
        return "break"


def main(argv: Sequence[str] | None = None) -> int:
    """Otevře zadané dokumenty, nebo novou šablonu, a spustí GUI."""

    document_paths = tuple(
        Path(argument) for argument in (sys.argv[1:] if argv is None else argv)
    )
    _configure_tk_runtime()
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"chyba: grafické rozhraní nelze spustit: {error}", file=sys.stderr)
        return 2
    application = CrosswordApplication(root)
    if document_paths:
        opened_any = False
        for source in document_paths:
            window = application.open_document(source, parent=root)
            opened_any = window is not None or opened_any
        if not opened_any:
            root.destroy()
            return 2
    else:
        application.new_template_document()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

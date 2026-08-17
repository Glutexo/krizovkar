"""Grafické rozhraní Křížovkáře postavené na Tk."""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Protocol, cast

from krizovkar.alphabet import split_answer_letters
from krizovkar.generator import (
    DEFAULT_GRID_HEIGHT,
    DEFAULT_GRID_WIDTH,
    GenerationError,
    SpecificationLayout,
    create_grid_from_crossword,
    generate_numbered_template,
    generate_swedish_template,
)
from krizovkar.localization import ngettext
from krizovkar.model import (
    Coordinate,
    CrosswordDocument,
    CrosswordGrid,
    EmptyCell,
    HelpCell,
    LegendCell,
    LetterCell,
    ModelError,
    SecretCell,
    WordSlot,
    dump_crossword_document,
    load_crossword_document,
    write_crossword_document,
)
from krizovkar.renderer import (
    DEFAULT_PAGE_FORMAT,
    SUPPORTED_PAGE_FORMATS,
    RenderError,
    render_pdf,
)

_MAX_CROSSWORD_DIMENSION = 50
_MAX_RECENT_DOCUMENTS = 10
_CROSSWORD_RESIZE_DELAY_MS = 150
_WINDOW_MENU_SELECTION_VARIABLE = "krizovkar_active_window"
_DIRECTION_LABELS = {
    "horizontal": "Vodorovně",
    "vertical": "Svisle",
}


class GuiInputError(ValueError):
    """Nastavení zadané v grafickém rozhraní není platné."""


@dataclass(frozen=True, slots=True)
class CrosswordSettings:
    """Rozměr automaticky rozvrhované křížovky."""

    width: int
    height: int


@dataclass(frozen=True, slots=True)
class _KeyboardShortcut:
    """Popisek nabídky a odpovídající vazba kláves podle platformy."""

    accelerator: str
    sequence: str


@dataclass(frozen=True, slots=True)
class _ExportAction:
    """Jedna položka exportu sdílená nabídkou a panelem nástrojů."""

    identifier: str
    label: str
    command: Callable[[], None]


@dataclass(frozen=True, slots=True)
class _ToolbarItem:
    """Přímá nebo rozbalovací položka panelu nástrojů."""

    identifier: str
    label: str
    tooltip: str
    image_name: str
    command: Callable[[], None] | None = None
    menu_actions: tuple[_ExportAction, ...] = ()


class _WindowToolbar(Protocol):
    """Společné rozhraní nativního a Tk panelu nástrojů."""

    def configure_action(self, identifier: str, *, state: str) -> None: ...


def _create_macos_toolbar(
    window: tk.Toplevel,
    items: Sequence[_ToolbarItem],
) -> _WindowToolbar:
    from krizovkar.macos_toolbar import MacWindowToolbar

    return MacWindowToolbar(window, items)


def _keyboard_shortcut(key: str, *, shift: bool = False) -> _KeyboardShortcut:
    normalized_key = key.lower()
    if sys.platform == "darwin":
        # Aqua převede pojmenované modifikátory na systémové symboly samo.
        accelerator = (
            f"Command-{'Shift-' if shift else ''}{normalized_key.upper()}"
        )
        modifier = "Command"
    else:
        accelerator = f"Ctrl+{'Shift+' if shift else ''}{normalized_key.upper()}"
        modifier = "Control"
    sequence_key = normalized_key.upper() if shift else normalized_key
    sequence = f"<{modifier}-{'Shift-' if shift else ''}{sequence_key}>"
    return _KeyboardShortcut(accelerator, sequence)


def _recent_documents_storage_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        configured = os.environ.get("APPDATA")
        base = (
            Path(configured)
            if configured
            else Path.home() / "AppData" / "Roaming"
        )
    else:
        configured = os.environ.get("XDG_STATE_HOME")
        base = (
            Path(configured)
            if configured
            else Path.home() / ".local" / "state"
        )
    return base / "krizovkar" / "recent-documents.json"


class _RecentDocuments:
    """Udržuje malý trvalý seznam naposledy použitých dokumentů."""

    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path or _recent_documents_storage_path()
        self._paths = list(self._load())

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(self._paths)

    def add(self, path: Path) -> None:
        normalized = path.expanduser().absolute()
        paths = [normalized]
        paths.extend(item for item in self._paths if item != normalized)
        paths = paths[:_MAX_RECENT_DOCUMENTS]
        if paths == self._paths:
            return
        self._paths = paths
        self._persist()

    def remove(self, path: Path) -> None:
        normalized = path.expanduser().absolute()
        paths = [item for item in self._paths if item != normalized]
        if paths == self._paths:
            return
        self._paths = paths
        self._persist()

    def clear(self) -> None:
        self._paths = []
        try:
            self._storage_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _load(self) -> tuple[Path, ...]:
        try:
            values = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ()
        if not isinstance(values, list):
            return ()
        paths: list[Path] = []
        for value in values:
            if not isinstance(value, str) or not value:
                continue
            path = Path(value)
            if not path.is_absolute() or path in paths:
                continue
            paths.append(path)
            if len(paths) == _MAX_RECENT_DOCUMENTS:
                break
        return tuple(paths)

    def _persist(self) -> None:
        temporary = self._storage_path.with_name(
            f".{self._storage_path.name}.tmp"
        )
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(
                    [str(path) for path in self._paths],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self._storage_path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _recent_document_label(path: Path, paths: Sequence[Path]) -> str:
    if sum(item.name == path.name for item in paths) == 1:
        return path.name
    return f"{path.name} — {path.parent}"


def _document_window_label(path: Path | None, dirty: bool) -> str:
    name = path.name if path is not None else "Nová šablona"
    marker = "*" if dirty else ""
    return f"{marker}{name}"


def _create_window_menu(
    parent: tk.Menu,
    refresh: Callable[[], None],
) -> tk.Menu:
    if sys.platform == "darwin":
        return tk.Menu(parent, name="window")
    return tk.Menu(parent, name="window", postcommand=refresh)


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


def parse_crossword_settings(width: str, height: str) -> CrosswordSettings:
    """Převede a omezí rozměr automaticky rozvrhované křížovky."""

    settings = CrosswordSettings(
        width=_positive_integer(width, "Počet sloupců"),
        height=_positive_integer(height, "Počet řádků"),
    )
    if (
        settings.width > _MAX_CROSSWORD_DIMENSION
        or settings.height > _MAX_CROSSWORD_DIMENSION
    ):
        raise GuiInputError(
            f"Křížovka může mít nejvýše {_MAX_CROSSWORD_DIMENSION} sloupců a řádků."
        )
    return settings


def create_blank_template(
    settings: CrosswordSettings,
    layout: SpecificationLayout,
) -> CrosswordDocument:
    """Vygeneruje hustou prázdnou šablonu z rozvržení a rozměru."""

    if layout not in {"swedish", "numbered"}:
        raise GuiInputError(f"Nepodporované rozvržení křížovky {layout!r}.")
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


def _crossword_slot(
    crossword: CrosswordDocument,
    identifier: str,
) -> tuple[int, WordSlot]:
    for index, slot in enumerate(crossword.slots):
        if slot.identifier == identifier:
            return index, slot
    raise GuiInputError(f"Křížovka neobsahuje místo {identifier!r}.")


def fill_crossword_slot(
    crossword: CrosswordDocument,
    identifier: str,
    answer: str,
    clue: str,
) -> CrosswordDocument:
    """Zapíše ručně zadané heslo do vybraného slotu dokumentu."""

    slot_index, slot = _crossword_slot(crossword, identifier)
    normalized_answer, normalized_clue = parse_slot_content(
        answer,
        clue,
        slot.length,
    )
    for other in crossword.slots:
        if other.identifier != identifier and other.answer == normalized_answer:
            raise GuiInputError(
                f"Heslo {normalized_answer!r} už je použité v jiném místě."
            )

    fixed_letters: dict[Coordinate, tuple[str, str]] = {}
    for other in crossword.slots:
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

    slots = list(crossword.slots)
    slots[slot_index] = replace(
        slot,
        answer=normalized_answer,
        clue=normalized_clue,
    )
    result = replace(crossword, slots=tuple(slots))
    try:
        dump_crossword_document(result, StringIO())
    except ModelError as error:
        raise GuiInputError(str(error)) from error
    return result


def clear_crossword_slot(
    crossword: CrosswordDocument,
    identifier: str,
) -> CrosswordDocument:
    """Odstraní ručně zadaný obsah jednoho slotu dokumentu."""

    slot_index, slot = _crossword_slot(crossword, identifier)
    slots = list(crossword.slots)
    slots[slot_index] = replace(
        slot,
        answer=None,
        clue=None,
        in_help=False,
    )
    return replace(crossword, slots=tuple(slots))


def crossword_slot_pattern(
    crossword: CrosswordDocument,
    identifier: str,
) -> tuple[str | None, ...]:
    """Vrátí písmena známá z ostatních hesel křížících vybraný slot."""

    _, selected = _crossword_slot(crossword, identifier)
    fixed_letters: dict[Coordinate, str] = {}
    for slot in crossword.slots:
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


def crossword_is_complete(crossword: CrosswordDocument) -> bool:
    """Určí, zda mají všechny sloty odpověď i nápovědu."""

    return all(
        slot.answer is not None and slot.clue is not None
        for slot in crossword.slots
    )


def _template_generation_layout(
    document: CrosswordDocument,
) -> SpecificationLayout:
    """Určí rozvržení pro nové vygenerování šablony."""

    if any(slot.legend_position is not None for slot in document.slots):
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
    """Náhled křížovky a jejího postupně doplňovaného obsahu."""

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
) -> CrosswordDocument:
    """Načte prázdnou, rozpracovanou nebo hotovou křížovku."""

    return load_crossword_document(source)


def _grid_from_editable_document(
    document: CrosswordDocument,
) -> CrosswordGrid:
    return create_grid_from_crossword(document)


class CrosswordApplication:
    """Spravuje životní cyklus samostatných dokumentových oken."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        recent_documents: _RecentDocuments | None = None,
    ) -> None:
        self.root = root
        self._windows: list[CrosswordDocumentWindow] = []
        self._recent_documents = (
            recent_documents
            if recent_documents is not None
            else _RecentDocuments()
        )
        self._configure_no_document_window()
        self._build_menu()
        self.root.withdraw()

    @property
    def recent_document_paths(self) -> tuple[Path, ...]:
        return self._recent_documents.paths

    def _configure_no_document_window(self) -> None:
        self.root.title("Křížovkář")
        self.root.geometry("560x260")
        self.root.minsize(440, 220)
        self.root.option_add("*tearOff", False)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        content = ttk.Frame(self.root, padding=32)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        ttk.Label(
            content,
            text="Není otevřený žádný dokument.",
            anchor="center",
        ).grid(row=0, column=0, sticky="nsew")

    def _build_menu(self) -> None:
        new_shortcut = _keyboard_shortcut("n")
        open_shortcut = _keyboard_shortcut("o")
        menu = tk.Menu(self.root)
        self.file_menu = tk.Menu(menu)
        self.file_menu.add_command(
            label="Nová šablona",
            accelerator=new_shortcut.accelerator,
            command=self.new_template_document,
        )
        self.file_menu.add_command(
            label="Otevřít…",
            accelerator=open_shortcut.accelerator,
            command=lambda: self.choose_document(
                parent=self._no_document_dialog_parent()
            ),
        )
        self.recent_documents_menu = tk.Menu(
            self.file_menu,
            postcommand=self._refresh_recent_documents_menu,
        )
        self.file_menu.add_cascade(
            label="Otevřít poslední",
            menu=self.recent_documents_menu,
        )
        menu.add_cascade(label="Soubor", menu=self.file_menu)
        self.window_menu = _create_window_menu(
            menu,
            self._refresh_window_menu,
        )
        menu.add_cascade(label="Okno", menu=self.window_menu)
        self.root.configure(menu=menu)
        self.root.bind(new_shortcut.sequence, self._new_event)
        self.root.bind(open_shortcut.sequence, self._open_event)

    def _refresh_recent_documents_menu(self) -> None:
        self.recent_documents_menu.delete(0, "end")
        paths = self.recent_document_paths
        if not paths:
            self.recent_documents_menu.add_command(
                label="Žádné nedávné dokumenty",
                state="disabled",
            )
            return
        for path in paths:
            self.recent_documents_menu.add_command(
                label=_recent_document_label(path, paths),
                command=lambda recent_path=path: self.open_recent_document(
                    recent_path,
                    parent=self._no_document_dialog_parent(),
                ),
            )
        self.recent_documents_menu.add_separator()
        self.recent_documents_menu.add_command(
            label="Vymazat nabídku",
            command=self.clear_recent_documents,
        )

    def _refresh_window_menu(self) -> None:
        self._populate_window_menu(self.window_menu, current=None)

    def _populate_window_menu(
        self,
        menu: tk.Menu,
        *,
        current: CrosswordDocumentWindow | None,
    ) -> None:
        menu.delete(0, "end")
        windows = tuple(self._windows)
        selected = str(id(current)) if current in windows else ""
        menu.setvar(_WINDOW_MENU_SELECTION_VARIABLE, selected)
        if not windows:
            menu.add_command(
                label="Žádná otevřená okna",
                state="disabled",
            )
            return
        for window in windows:
            menu.add_radiobutton(
                label=_document_window_label(window._path, window._dirty),
                value=str(id(window)),
                variable=_WINDOW_MENU_SELECTION_VARIABLE,
                command=lambda target=window: self.activate_window(target),
            )

    def _no_document_dialog_parent(self) -> tk.Misc | None:
        return None if sys.platform == "darwin" else self.root

    def show_no_document_state(self) -> None:
        if sys.platform != "darwin":
            self.root.deiconify()
            self.root.lift()

    def _new_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.new_template_document()
        return "break"

    def _open_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.choose_document(parent=self._no_document_dialog_parent())
        return "break"

    def new_template_document(self) -> CrosswordDocumentWindow:
        template = create_blank_template(
            CrosswordSettings(DEFAULT_GRID_WIDTH, DEFAULT_GRID_HEIGHT),
            "swedish",
        )
        return self._open_window(template, dirty=True)

    def choose_document(
        self,
        *,
        parent: tk.Misc | None,
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
        parent: tk.Misc | None,
    ) -> CrosswordDocumentWindow | None:
        source = source.expanduser().absolute()
        try:
            document = load_editable_document(source)
        except ModelError as error:
            messagebox.showerror(
                "Dokument nelze otevřít",
                str(error),
                parent=parent,
            )
            return None
        window = self._open_window(document, path=source, dirty=False)
        self.remember_recent_document(source)
        return window

    def open_recent_document(
        self,
        source: Path,
        *,
        parent: tk.Misc | None,
    ) -> CrosswordDocumentWindow | None:
        if not source.exists():
            self._recent_documents.remove(source)
            messagebox.showerror(
                "Dokument nelze otevřít",
                f"Soubor {source} už neexistuje a byl odebrán "
                "z nabídky posledních dokumentů.",
                parent=parent,
            )
            return None
        return self.open_document(source, parent=parent)

    def remember_recent_document(self, source: Path) -> None:
        self._recent_documents.add(source)

    def clear_recent_documents(self) -> None:
        self._recent_documents.clear()

    def _open_window(
        self,
        document: CrosswordDocument,
        *,
        path: Path | None = None,
        dirty: bool,
    ) -> CrosswordDocumentWindow:
        self.root.withdraw()
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

    def activate_window(self, window: CrosswordDocumentWindow) -> None:
        if window not in self._windows:
            return
        window.root.deiconify()
        window.root.lift()
        window.root.focus_force()

    def close_window(self, window: CrosswordDocumentWindow) -> None:
        if window in self._windows:
            self._windows.remove(window)
        window.root.destroy()
        if not self._windows:
            self.show_no_document_state()


class CrosswordDocumentWindow(ttk.Frame):
    """Jedno viditelné okno svázané s jedním YAML dokumentem."""

    def __init__(
        self,
        root: tk.Toplevel,
        *,
        application: CrosswordApplication,
        document: CrosswordDocument,
        path: Path | None,
        dirty: bool,
    ) -> None:
        super().__init__(root, padding=(24, 18))
        self.root = root
        self.application = application
        self._path = path
        self._dirty = dirty
        self._crossword = document
        self._grid: CrosswordGrid | None = None
        self._template_layout = _template_generation_layout(document)
        self._selected_slot_identifier: str | None = None
        self._content_row = 0 if sys.platform == "darwin" else 1
        self._changing_dimension_values = False

        self.width_value = tk.StringVar(value=str(document.grid.width))
        self.height_value = tk.StringVar(value=str(document.grid.height))
        self.dimension_error_value = tk.StringVar()
        self.answer_value = tk.StringVar()
        self.clue_value = tk.StringVar()
        self.slot_title_value = tk.StringVar(value="Vyberte heslo.")
        self.slot_pattern_value = tk.StringVar(value="Vzor z křížení: —")
        self._page_format = DEFAULT_PAGE_FORMAT
        self._resize_job: str | None = None

        self._configure_window()
        self._configure_styles()
        self._build_menu()
        self._build_content()
        self._build_toolbar()
        self._watch_inputs()
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
        self.rowconfigure(self._content_row, weight=1)
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Muted.TLabel", foreground="#667085")
        style.configure("Error.TLabel", foreground="#b42318")

    def _build_menu(self) -> None:
        new_shortcut = _keyboard_shortcut("n")
        open_shortcut = _keyboard_shortcut("o")
        save_shortcut = _keyboard_shortcut("s")
        save_as_shortcut = _keyboard_shortcut("s", shift=True)
        close_shortcut = _keyboard_shortcut("w")
        menu = tk.Menu(self.root)
        self.file_menu = tk.Menu(menu)
        self.file_menu.add_command(
            label="Nová šablona",
            accelerator=new_shortcut.accelerator,
            command=self.application.new_template_document,
        )
        self.file_menu.add_command(
            label="Otevřít…",
            accelerator=open_shortcut.accelerator,
            command=lambda: self.application.choose_document(parent=self.root),
        )
        self.recent_documents_menu = tk.Menu(
            self.file_menu,
            postcommand=self._refresh_recent_documents_menu,
        )
        self.file_menu.add_cascade(
            label="Otevřít poslední",
            menu=self.recent_documents_menu,
        )
        self.file_menu.add_separator()
        self.file_menu.add_command(
            label="Uložit",
            accelerator=save_shortcut.accelerator,
            command=self.save_current_document_data,
        )
        self._save_menu_index = cast(int, self.file_menu.index("end"))
        self.file_menu.add_command(
            label="Uložit jako…",
            accelerator=save_as_shortcut.accelerator,
            command=self.save_document_as,
        )
        self._save_as_menu_index = cast(int, self.file_menu.index("end"))
        self.file_menu.add_separator()
        self.export_menu = tk.Menu(self.file_menu)
        self._add_export_actions()
        self.file_menu.add_cascade(label="Exportovat", menu=self.export_menu)
        self.file_menu.add_separator()
        self.file_menu.add_command(
            label="Zavřít okno",
            accelerator=close_shortcut.accelerator,
            command=self.request_close,
        )
        menu.add_cascade(label="Soubor", menu=self.file_menu)
        self.window_menu = _create_window_menu(
            menu,
            self._refresh_window_menu,
        )
        menu.add_cascade(label="Okno", menu=self.window_menu)
        self.root.configure(menu=menu)
        self.root.bind(new_shortcut.sequence, self._new_event)
        self.root.bind(open_shortcut.sequence, self._open_event)
        self.root.bind(save_shortcut.sequence, self._save_event)
        self.root.bind(save_as_shortcut.sequence, self._save_as_event)
        self.root.bind(close_shortcut.sequence, self._close_event)

    def _add_export_actions(self) -> None:
        for action in self._export_actions():
            options: dict[str, object] = {
                "label": action.label,
                "command": action.command,
            }
            if action.identifier == "solution":
                options["state"] = "disabled"
            self.export_menu.add_command(**options)

    def _export_actions(self) -> tuple[_ExportAction, ...]:
        return (
            _ExportAction(
                "blank-crossword",
                "Křížovku bez písmen (PDF)…",
                self.save_crossword_pdf,
            ),
            _ExportAction(
                "solution",
                "Řešení s písmeny (PDF)…",
                self.save_solution_pdf,
            ),
        )

    def _toolbar_items(self) -> tuple[_ToolbarItem, ...]:
        return (
            _ToolbarItem(
                identifier="export",
                label="Exportovat",
                tooltip="Exportovat dokument do PDF",
                image_name="square.and.arrow.up",
                menu_actions=self._export_actions(),
            ),
        )

    def _build_toolbar(self) -> None:
        items = self._toolbar_items()
        if sys.platform == "darwin":
            self.toolbar = _create_macos_toolbar(
                self.root,
                items,
            )
            return
        self.toolbar = ttk.Frame(self, padding=(14, 0, 14, 10))
        self.toolbar.grid(row=0, column=0, sticky="ew")
        self._toolbar_controls: dict[str, ttk.Widget] = {}
        for item in items:
            if item.menu_actions:
                control = ttk.Menubutton(
                    self.toolbar,
                    text=item.label,
                    menu=self.export_menu,
                )
            else:
                assert item.command is not None
                control = ttk.Button(
                    self.toolbar,
                    text=item.label,
                    command=item.command,
                )
            control.pack(side="left", padx=(0, 6))
            self._toolbar_controls[item.identifier] = control

    def _configure_toolbar_action(self, identifier: str, state: str) -> None:
        if sys.platform == "darwin":
            self.toolbar.configure_action(identifier, state=state)
            return
        self._toolbar_controls[identifier].configure(state=state)

    def _refresh_recent_documents_menu(self) -> None:
        self.recent_documents_menu.delete(0, "end")
        paths = self.application.recent_document_paths
        if not paths:
            self.recent_documents_menu.add_command(
                label="Žádné nedávné dokumenty",
                state="disabled",
            )
            return
        for path in paths:
            self.recent_documents_menu.add_command(
                label=_recent_document_label(path, paths),
                command=lambda recent_path=path: (
                    self.application.open_recent_document(
                        recent_path,
                        parent=self.root,
                    )
                ),
            )
        self.recent_documents_menu.add_separator()
        self.recent_documents_menu.add_command(
            label="Vymazat nabídku",
            command=self.application.clear_recent_documents,
        )

    def _refresh_window_menu(self) -> None:
        self.application._populate_window_menu(
            self.window_menu,
            current=self,
        )

    def _build_content(self) -> None:
        document_frame = ttk.Frame(self, padding=14)
        document_frame.grid(
            row=self._content_row,
            column=0,
            sticky="nsew",
        )
        self.crossword_tab = document_frame
        self._build_crossword_document()

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
        self._build_crossword_dimensions(document)

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

    def _build_crossword_dimensions(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="w")
        ttk.Label(controls, text="Řádky").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.height_spinbox = ttk.Spinbox(
            controls,
            from_=1,
            to=_MAX_CROSSWORD_DIMENSION,
            width=5,
            textvariable=self.height_value,
        )
        self.height_spinbox.grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(controls, text="Sloupce").grid(
            row=0,
            column=2,
            sticky="w",
            padx=(14, 0),
        )
        self.width_spinbox = ttk.Spinbox(
            controls,
            from_=1,
            to=_MAX_CROSSWORD_DIMENSION,
            width=5,
            textvariable=self.width_value,
        )
        self.width_spinbox.grid(row=0, column=3, sticky="w", padx=(6, 0))
        ttk.Label(
            parent,
            textvariable=self.dimension_error_value,
            style="Error.TLabel",
            wraplength=310,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

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
            text="Náhled křížovky",
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
        for value in (self.width_value, self.height_value):
            value.trace_add("write", self._dimension_input_changed)

    def _dimension_input_changed(self, *_args: str) -> None:
        if self._changing_dimension_values:
            return
        self.dimension_error_value.set("")
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(
            _CROSSWORD_RESIZE_DELAY_MS,
            self._regenerate_template_from_inputs,
        )

    def _regenerate_template_from_inputs(self) -> None:
        self._resize_job = None
        try:
            settings = parse_crossword_settings(
                self.width_value.get(),
                self.height_value.get(),
            )
            current = self._crossword
            if current is None:
                return
            if (
                current.grid.width == settings.width
                and current.grid.height == settings.height
            ):
                return
            has_authored_content = bool(current.secrets) or any(
                slot.answer is not None or slot.clue is not None
                for slot in current.slots
            )
            if has_authored_content and not messagebox.askyesno(
                "Změnit rozměry křížovky?",
                "Změna rozměrů znovu vytvoří rozvržení a odstraní "
                "vyplněná hesla i nastavení tajenky. Chcete pokračovat?",
                parent=self.root,
            ):
                self._restore_dimension_values(current)
                return
            layout = self._template_layout or "swedish"
            template = create_blank_template(settings, layout)
        except GuiInputError as error:
            self.dimension_error_value.set(str(error))
            return

        self._crossword = template
        self._template_layout = layout
        self._selected_slot_identifier = None
        self._set_dirty(True)
        self._rebuild_slot_tree()
        self._refresh_crossword_view()

    def _restore_dimension_values(self, crossword: CrosswordDocument) -> None:
        self._changing_dimension_values = True
        try:
            self.width_value.set(str(crossword.grid.width))
            self.height_value.set(str(crossword.grid.height))
        finally:
            self._changing_dimension_values = False

    def _refresh_file_menu(self) -> None:
        crossword = self._crossword
        complete = crossword is not None and crossword_is_complete(crossword)
        self.file_menu.entryconfigure(
            self._save_menu_index,
            label="Uložit křížovku",
        )
        self.file_menu.entryconfigure(
            self._save_as_menu_index,
            label="Uložit křížovku jako…",
        )
        self.export_menu.entryconfigure(
            0,
            state="normal",
        )
        self.export_menu.entryconfigure(
            1,
            state="normal" if complete else "disabled",
        )
        self._configure_toolbar_action("export", "normal")

    def _slot_label(self, selected: WordSlot) -> str:
        assert self._crossword is not None
        number = 0
        for slot in self._crossword.slots:
            if slot.direction == selected.direction:
                number += 1
            if slot.identifier == selected.identifier:
                return f"{_DIRECTION_LABELS[slot.direction]} {number}"
        return selected.identifier

    def _rebuild_slot_tree(self) -> None:
        selected_identifier = self._selected_slot_identifier
        for item in self.slots_tree.get_children():
            self.slots_tree.delete(item)
        crossword = self._crossword
        if crossword is None:
            self._slot_selection_changed()
            return
        for slot in crossword.slots:
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
        identifiers = {slot.identifier for slot in crossword.slots}
        if selected_identifier not in identifiers:
            selected_identifier = crossword.slots[0].identifier
        self.slots_tree.selection_set(selected_identifier)
        self.slots_tree.focus(selected_identifier)
        self.slots_tree.see(selected_identifier)
        self._selected_slot_identifier = selected_identifier
        self._slot_selection_changed()

    def _selected_slot(self) -> WordSlot | None:
        if self._crossword is None or self._selected_slot_identifier is None:
            return None
        try:
            _, slot = _crossword_slot(
                self._crossword,
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
        if not selection or self._crossword is None:
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
        pattern = crossword_slot_pattern(self._crossword, slot.identifier)
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
        crossword = self._crossword
        if crossword is None:
            return
        candidates = [
            slot.identifier
            for slot in crossword.slots
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
                    if _crossword_slot(crossword, identifier)[1].answer is None
                ),
                candidates[0],
            )
        self.slots_tree.selection_set(selected)
        self.slots_tree.focus(selected)
        self.slots_tree.see(selected)
        self._selected_slot_identifier = selected
        self._slot_selection_changed()

    def save_selected_slot(self) -> None:
        crossword = self._crossword
        identifier = self._selected_slot_identifier
        if crossword is None or identifier is None:
            self._show_action_error(
                "Heslo nelze uložit",
                "Vyberte nejprve místo v náhledu nebo seznamu.",
            )
            return
        try:
            self._crossword = fill_crossword_slot(
                crossword,
                identifier,
                self.answer_value.get(),
                self.clue_value.get(),
            )
        except GuiInputError as error:
            self._show_action_error(
                "Heslo nelze uložit",
                str(error),
            )
            return
        self._set_dirty(True)
        self._rebuild_slot_tree()
        self._refresh_crossword_view()

    def clear_selected_slot(self) -> None:
        crossword = self._crossword
        identifier = self._selected_slot_identifier
        if crossword is None or identifier is None:
            return
        self._crossword = clear_crossword_slot(crossword, identifier)
        self._set_dirty(True)
        self._rebuild_slot_tree()
        self._refresh_crossword_view()

    def _refresh_crossword_view(self) -> None:
        self._refresh_crossword_preview()
        crossword = self._crossword
        if crossword is None:
            self._selected_slot_identifier = None
            self.slot_title_value.set("Křížovka zatím není vytvořená.")
            self.slot_pattern_value.set("Vzor z křížení: —")
            self.answer_value.set("")
            self.clue_value.set("")
            self._set_slot_form_state("disabled")
            self._refresh_file_menu()
            return
        self._refresh_file_menu()

    def _refresh_crossword_preview(self) -> None:
        crossword = self._crossword
        if crossword is None:
            self._grid = None
            self.crossword_preview.clear_preview("Křížovka zatím není vytvořená.")
            return
        self._grid = _grid_from_editable_document(crossword)
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
        crossword = self._crossword
        if crossword is None:
            self._show_action_error(
                "Křížovka není připravena",
                "Dokument křížovky zatím není vytvořený.",
            )
            return None
        if not crossword_is_complete(crossword):
            remaining = sum(slot.answer is None for slot in crossword.slots)
            self._show_action_error(
                "Křížovka není připravena",
                f"Doplňte ještě {_word_count_text(remaining)}.",
            )
            return None
        return _grid_from_editable_document(crossword)

    def save_crossword_pdf(self) -> None:
        crossword = self._crossword
        if crossword is None:
            self._show_action_error(
                "Křížovka není připravena",
                "Dokument křížovky zatím není vytvořený.",
            )
            return
        self._save_pdf(
            _grid_from_editable_document(crossword),
            filled=False,
            title="Exportovat křížovku bez písmen",
            initialfile="krizovka.pdf",
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
            )
            return
        finally:
            self.root.configure(cursor="")

    def _document(self) -> CrosswordDocument:
        return self._crossword

    def save_document(self) -> bool:
        if self._path is None:
            return self.save_document_as()
        return self._write_document(self._path, overwrite=True)

    def save_document_as(self) -> bool:
        if self._path is not None:
            initialfile = self._path.name
        else:
            initialfile = "sablona.yaml"
        selected = self._choose_output(
            title="Uložit křížovku jako",
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
            write_crossword_document(
                document,
                output,
                overwrite=overwrite,
            )
        except ModelError as error:
            self._show_action_error(
                "Dokument nelze uložit",
                str(error),
            )
            return False
        self._path = output
        self._set_dirty(False)
        self.application.remember_recent_document(output)
        return True

    def save_current_document_data(self) -> bool:
        return self.save_document()

    def _show_action_error(
        self,
        title: str,
        message: str,
    ) -> None:
        messagebox.showerror(title, message, parent=self.root)

    def _update_title(self) -> None:
        label = _document_window_label(self._path, self._dirty)
        self.root.title(f"{label} — Křížovkář")
        if sys.platform == "darwin":
            title_path = (
                str(self._path.absolute()) if self._path is not None else ""
            )
            self.root.attributes("-titlepath", title_path)

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
    """Otevře zadané dokumenty nebo zobrazí jejich systémový výběr."""

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
        if application.choose_document(parent=None) is None:
            application.show_no_document_state()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

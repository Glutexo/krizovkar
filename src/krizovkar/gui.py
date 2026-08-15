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
    create_grid_from_template,
    create_template_from_specification,
    generate_numbered_template,
    generate_swedish_template,
)
from krizovkar.localization import ngettext
from krizovkar.model import (
    Coordinate,
    CrosswordGrid,
    CrosswordSpecification,
    CrosswordTemplate,
    EmptyCell,
    GridDimensions,
    HelpCell,
    LegendCell,
    LetterCell,
    ModelError,
    SecretCell,
    WordDirection,
    WordPlacement,
    dump_crossword_specification,
    write_crossword_specification,
    write_crossword_template,
)
from krizovkar.renderer import (
    DEFAULT_PAGE_FORMAT,
    SUPPORTED_PAGE_FORMATS,
    RenderError,
    render_pdf,
)

_DIRECTIONS = frozenset(("horizontal", "vertical"))
_MAX_TEMPLATE_DIMENSION = 50
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


@dataclass(frozen=True, slots=True)
class PreparedCrossword:
    """Datová šablona a mřížka připravená z vlastních hesel."""

    template: CrosswordTemplate
    grid: CrosswordGrid


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


def parse_template_settings(
    width: str,
    height: str,
) -> SpecificationSettings:
    """Převede a omezí rozměr automaticky rozvrhované šablony."""

    settings = parse_specification_settings(width, height)
    if (
        settings.width > _MAX_TEMPLATE_DIMENSION
        or settings.height > _MAX_TEMPLATE_DIMENSION
    ):
        raise GuiInputError(
            "Prázdná šablona může mít nejvýše "
            f"{_MAX_TEMPLATE_DIMENSION} sloupců a řádků."
        )
    return settings


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


def prepare_crossword(
    specification: CrosswordSpecification,
    layout: SpecificationLayout,
) -> PreparedCrossword:
    """Připraví z vlastních hesel datovou šablonu i tiskovou mřížku."""

    template = create_template(specification, layout)
    return PreparedCrossword(
        template=template,
        grid=create_grid_from_template(template),
    )


def create_blank_template(
    settings: SpecificationSettings,
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
    """Náhled rozepsaného zadání nebo výsledné mřížky."""

    _GRID_COLOR = "#667085"
    _LETTER_FILL = "#eff6ff"
    _SELECTED_FILL = "#bfdbfe"
    _LEGEND_FILL = "#fef3c7"
    _EMPTY_FILL = "#e2e8f0"
    _HELP_FILL = "#dcfce7"
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
        self._crossword: CrosswordGrid | None = None
        self._show_letters = True
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
        self._crossword = None
        self._show_letters = True
        self._redraw()

    def show_crossword(
        self,
        crossword: CrosswordGrid,
        *,
        words: tuple[WordPlacement, ...] = (),
        selected_index: int | None = None,
        show_letters: bool = True,
    ) -> None:
        """Zobrazí role buněk, čísla a volitelně i písmena."""

        self._dimensions = GridDimensions(
            width=crossword.grid.width,
            height=crossword.grid.height,
        )
        self._words = words
        self._selected_index = selected_index
        self._crossword = crossword
        self._show_letters = show_letters
        self._redraw()

    def clear_preview(self, message: str) -> None:
        self._dimensions = None
        self._words = ()
        self._selected_index = None
        self._crossword = None
        self._show_letters = True
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
        draft_letters, selected_coordinates = self._placed_letters()
        grid_cells = self._crossword.grid.cells if self._crossword is not None else None

        for row in range(1, dimensions.height + 1):
            for column in range(1, dimensions.width + 1):
                x1 = left + (column - 1) * cell_size
                y1 = top + (row - 1) * cell_size
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                coordinate = (row, column)
                cell = (
                    grid_cells[row - 1][column - 1] if grid_cells is not None else None
                )
                letter = draft_letters.get(coordinate)
                fill = "#ffffff"
                marker: str | None = None
                number: int | None = None
                bars: tuple[str, ...] = ()
                if isinstance(cell, LegendCell):
                    fill = self._LEGEND_FILL
                    marker = "N" if any(cell.texts) else "?"
                    letter = None
                elif isinstance(cell, EmptyCell):
                    fill = self._EMPTY_FILL
                    letter = None
                elif isinstance(cell, HelpCell):
                    fill = self._HELP_FILL
                    marker = "P"
                    letter = None
                elif isinstance(cell, (LetterCell, SecretCell)):
                    letter = cell.value if self._show_letters else None
                    number = cell.number
                    bars = cell.bars

                if coordinate in selected_coordinates and (
                    cell is None or isinstance(cell, (LetterCell, SecretCell))
                ):
                    fill = self._SELECTED_FILL
                elif cell is None and letter is not None:
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
                        fill=self._COORDINATE_COLOR,
                        font=("TkDefaultFont", max(7, int(cell_size * 0.3)), "bold"),
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
                        font=("TkDefaultFont", max(5, int(cell_size * 0.2))),
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


class CrosswordApplication(ttk.Frame):
    """Hlavní okno se dvěma srozumitelnými cestami tvorby."""

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, padding=(24, 18))
        self.root = root
        self._words: list[WordPlacement] = []
        self._specification: CrosswordSpecification | None = None
        self._prepared_crossword: PreparedCrossword | None = None
        self._blank_template: CrosswordTemplate | None = None
        self._blank_grid: CrosswordGrid | None = None
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
        self.page_format_value = tk.StringVar(value=DEFAULT_PAGE_FORMAT)
        self.crossword_layout_help_value = tk.StringVar()
        self.crossword_status_value = tk.StringVar(value="Připravuji editor křížovky…")

        self.template_width_value = tk.StringVar(value=str(DEFAULT_GRID_WIDTH))
        self.template_height_value = tk.StringVar(value=str(DEFAULT_GRID_HEIGHT))
        self.template_layout_value = tk.StringVar(value="swedish")
        self.template_page_format_value = tk.StringVar(value=DEFAULT_PAGE_FORMAT)
        self.template_layout_help_value = tk.StringVar()
        self.template_status_value = tk.StringVar(value="Připravuji prázdnou šablonu…")

        self._configure_window()
        self._configure_styles()
        self._build_menu()
        self._build_content()
        self._watch_inputs()
        self.root.after_idle(self.refresh_specification)
        self.root.after_idle(self.refresh_blank_template)

    def _configure_window(self) -> None:
        self.root.title("Křížovkář – křížovka nebo prázdná šablona")
        self.root.geometry("1220x850")
        self.root.minsize(980, 700)
        self.root.option_add("*tearOff", False)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
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
        style.configure("Primary.TButton", font=("TkDefaultFont", 10, "bold"))
        style.configure("Muted.TLabel", foreground="#667085")
        style.configure("Error.TLabel", foreground="#b42318")
        style.configure("Success.TLabel", foreground="#067647")

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu)
        file_menu.add_command(
            label="Uložit aktuální výsledek do PDF…",
            accelerator="Ctrl+S",
            command=self.save_current_pdf,
        )
        data_menu = tk.Menu(file_menu)
        data_menu.add_command(
            label="Zadání vlastních hesel…",
            command=self.save_specification,
        )
        data_menu.add_command(
            label="Datová šablona aktuální karty…",
            command=self.save_current_data_template,
        )
        file_menu.add_cascade(label="Zdrojová data (YAML)", menu=data_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Konec", command=self.root.destroy)
        menu.add_cascade(label="Soubor", menu=file_menu)
        self.root.configure(menu=menu)
        self.root.bind("<Control-s>", self._save_event)
        self.root.bind("<Command-s>", self._save_event)

    def _build_content(self) -> None:
        ttk.Label(self, text="Křížovkář", style="Title.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Label(
            self,
            text=(
                "Vyberte, zda chcete vytvořit hotovou křížovku z vlastních "
                "hesel, nebo prázdnou šablonu k dalšímu vyplnění."
            ),
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="ew", pady=(2, 14))

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=2, column=0, sticky="nsew")

        self.crossword_tab = ttk.Frame(self.notebook, padding=14)
        self.blank_template_tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(
            self.crossword_tab,
            text="Křížovka z vlastních hesel",
        )
        self.notebook.add(
            self.blank_template_tab,
            text="Prázdná šablona",
        )
        self._build_crossword_tab()
        self._build_blank_template_tab()

    def _build_dimension_fields(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        width_value: tk.StringVar,
        height_value: tk.StringVar,
        maximum: int = 100,
    ) -> None:
        dimensions = ttk.Frame(parent)
        dimensions.grid(row=row, column=0, sticky="w", pady=(7, 0))
        ttk.Label(dimensions, text="Sloupce").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            dimensions,
            from_=1,
            to=maximum,
            width=7,
            textvariable=width_value,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(dimensions, text="×").grid(row=1, column=1, padx=10)
        ttk.Label(dimensions, text="Řádky").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(
            dimensions,
            from_=1,
            to=maximum,
            width=7,
            textvariable=height_value,
        ).grid(row=1, column=2, sticky="w", pady=(3, 0))

    def _build_layout_fields(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        value: tk.StringVar,
        help_value: tk.StringVar,
    ) -> None:
        ttk.Radiobutton(
            parent,
            text="Švédská – nápovědy přímo v mřížce",
            variable=value,
            value="swedish",
        ).grid(row=row, column=0, sticky="w", pady=(7, 0))
        ttk.Radiobutton(
            parent,
            text="Číslovaná – nápovědy pod mřížkou",
            variable=value,
            value="numbered",
        ).grid(row=row + 1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(
            parent,
            textvariable=help_value,
            style="Muted.TLabel",
            wraplength=310,
            justify="left",
        ).grid(row=row + 2, column=0, sticky="w", pady=(6, 0))

    def _build_page_format_field(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        value: tk.StringVar,
    ) -> None:
        page = ttk.Frame(parent)
        page.grid(row=row, column=0, sticky="w", pady=(7, 0))
        ttk.Label(page, text="Formát stránky").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Combobox(
            page,
            state="readonly",
            width=9,
            values=SUPPORTED_PAGE_FORMATS,
            textvariable=value,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

    def _build_crossword_tab(self) -> None:
        tab = self.crossword_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        editor_panel = ScrollablePanel(tab, width=350, height=600)
        editor_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        editor = ttk.LabelFrame(
            editor_panel.content,
            text="Postup",
            padding=14,
        )
        editor.pack(fill="x", expand=True)
        editor.columnconfigure(0, weight=1)

        ttk.Label(editor, text="1  Zvolte rozměr", style="Step.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self._build_dimension_fields(
            editor,
            row=1,
            width_value=self.width_value,
            height_value=self.height_value,
        )

        ttk.Separator(editor).grid(row=2, column=0, sticky="ew", pady=13)
        ttk.Label(
            editor,
            text="2  Přidávejte vlastní hesla",
            style="Step.TLabel",
        ).grid(row=3, column=0, sticky="w")

        form = ttk.Frame(editor)
        form.grid(row=4, column=0, sticky="ew", pady=(7, 0))
        form.columnconfigure(0, weight=1)

        ttk.Label(form, text="Heslo (odpověď)").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.answer_entry = ttk.Entry(form, textvariable=self.answer_value)
        self.answer_entry.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(3, 7),
        )

        ttk.Label(form, text="Nápověda (legenda)").grid(
            row=2,
            column=0,
            sticky="w",
        )
        ttk.Entry(form, textvariable=self.legend_value).grid(
            row=3,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(3, 7),
        )

        ttk.Label(form, text="První písmeno: řádek").grid(
            row=4,
            column=0,
            sticky="w",
        )
        ttk.Label(form, text="sloupec").grid(
            row=4,
            column=1,
            sticky="w",
            padx=(8, 0),
        )
        ttk.Spinbox(
            form,
            from_=1,
            to=100,
            width=7,
            textvariable=self.row_value,
        ).grid(row=5, column=0, sticky="w", pady=(3, 5))
        ttk.Spinbox(
            form,
            from_=1,
            to=100,
            width=7,
            textvariable=self.column_value,
        ).grid(row=5, column=1, sticky="w", padx=(8, 0), pady=(3, 5))
        ttk.Label(
            form,
            text="Souřadnice se počítají od 1 z levého horního rohu.",
            style="Muted.TLabel",
            wraplength=300,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(form, text="Směr hesla").grid(row=7, column=0, sticky="w")
        directions = ttk.Frame(form)
        directions.grid(row=8, column=0, columnspan=3, sticky="w", pady=(3, 5))
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
            text="Uvést odpověď v pomůcce",
            variable=self.in_help_value,
        ).grid(row=9, column=0, columnspan=3, sticky="w")

        form_actions = ttk.Frame(editor)
        form_actions.grid(row=5, column=0, sticky="ew", pady=(11, 0))
        form_actions.columnconfigure(0, weight=1)
        self.word_button = ttk.Button(
            form_actions,
            text="Přidat heslo do mřížky",
            command=self.add_or_update_word,
        )
        self.word_button.grid(row=0, column=0, sticky="ew")
        self.cancel_edit_button = ttk.Button(
            form_actions,
            text="Zrušit úpravu",
            command=self.clear_word_form,
            state="disabled",
        )
        self.cancel_edit_button.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        ttk.Label(
            editor,
            text="Tajenky zatím tento editor neumí přidat.",
            style="Muted.TLabel",
        ).grid(row=6, column=0, sticky="w", pady=(9, 0))

        ttk.Separator(editor).grid(row=7, column=0, sticky="ew", pady=13)
        ttk.Label(
            editor,
            text="3  Vyberte podobu křížovky",
            style="Step.TLabel",
        ).grid(row=8, column=0, sticky="w")
        self._build_layout_fields(
            editor,
            row=9,
            value=self.layout_value,
            help_value=self.crossword_layout_help_value,
        )

        ttk.Separator(editor).grid(row=12, column=0, sticky="ew", pady=13)
        ttk.Label(
            editor,
            text="4  Uložte hotový výsledek",
            style="Step.TLabel",
        ).grid(row=13, column=0, sticky="w")
        self._build_page_format_field(
            editor,
            row=14,
            value=self.page_format_value,
        )
        self.puzzle_button = ttk.Button(
            editor,
            text="Uložit křížovku bez písmen (PDF)…",
            command=self.save_crossword_pdf,
            state="disabled",
            style="Primary.TButton",
        )
        self.puzzle_button.grid(row=15, column=0, sticky="ew", pady=(10, 0))
        self.solution_button = ttk.Button(
            editor,
            text="Uložit řešení s písmeny (PDF)…",
            command=self.save_solution_pdf,
            state="disabled",
        )
        self.solution_button.grid(row=16, column=0, sticky="ew", pady=(5, 0))
        self.crossword_template_button = ttk.Button(
            editor,
            text="Uložit datovou šablonu (YAML)…",
            command=self.save_template,
            state="disabled",
        )
        self.crossword_template_button.grid(
            row=17,
            column=0,
            sticky="ew",
            pady=(5, 0),
        )

        workspace = ttk.Frame(tab)
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)

        preview_frame = ttk.LabelFrame(
            workspace,
            text="Náhled výsledné křížovky",
            padding=12,
        )
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.preview = SpecificationPreview(preview_frame, width=590, height=310)
        self.preview.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            preview_frame,
            text=(
                "Žluté pole s N je vepsaná nápověda, zelené pomůcka a "
                "šedé nevyplňované pole. Čísla odkazují na nápovědy "
                "pod mřížkou."
            ),
            style="Muted.TLabel",
            wraplength=600,
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        words_frame = ttk.LabelFrame(
            workspace,
            text="Přidaná hesla",
            padding=12,
        )
        words_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        words_frame.columnconfigure(0, weight=1)
        tree_container = ttk.Frame(words_frame)
        tree_container.grid(row=0, column=0, sticky="ew")
        tree_container.columnconfigure(0, weight=1)
        self.words_tree = ttk.Treeview(
            tree_container,
            columns=("answer", "legend", "start", "direction", "help"),
            show="headings",
            height=4,
            selectmode="browse",
        )
        self.words_tree.heading("answer", text="Heslo")
        self.words_tree.heading("legend", text="Nápověda")
        self.words_tree.heading("start", text="První pole")
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
        list_actions.grid(row=1, column=0, sticky="e", pady=(7, 0))
        self.edit_button = ttk.Button(
            list_actions,
            text="Upravit vybrané",
            command=self.edit_selected_word,
            state="disabled",
        )
        self.edit_button.grid(row=0, column=0)
        self.remove_button = ttk.Button(
            list_actions,
            text="Odebrat vybrané",
            command=self.remove_selected_word,
            state="disabled",
        )
        self.remove_button.grid(row=0, column=1, padx=(8, 0))

        self.crossword_status_label = ttk.Label(
            workspace,
            textvariable=self.crossword_status_value,
            style="Muted.TLabel",
            wraplength=620,
        )
        self.crossword_status_label.grid(
            row=2,
            column=0,
            sticky="w",
            pady=(10, 0),
        )

    def _build_blank_template_tab(self) -> None:
        tab = self.blank_template_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        settings_panel = ScrollablePanel(tab, width=350, height=600)
        settings_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        settings = ttk.LabelFrame(
            settings_panel.content,
            text="Postup",
            padding=14,
        )
        settings.pack(fill="x", expand=True)
        settings.columnconfigure(0, weight=1)

        ttk.Label(settings, text="1  Zvolte rozměr", style="Step.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self._build_dimension_fields(
            settings,
            row=1,
            width_value=self.template_width_value,
            height_value=self.template_height_value,
            maximum=_MAX_TEMPLATE_DIMENSION,
        )

        ttk.Separator(settings).grid(row=2, column=0, sticky="ew", pady=15)
        ttk.Label(
            settings,
            text="2  Vyberte podobu šablony",
            style="Step.TLabel",
        ).grid(row=3, column=0, sticky="w")
        self._build_layout_fields(
            settings,
            row=4,
            value=self.template_layout_value,
            help_value=self.template_layout_help_value,
        )

        ttk.Separator(settings).grid(row=7, column=0, sticky="ew", pady=15)
        ttk.Label(
            settings,
            text="3  Uložte šablonu",
            style="Step.TLabel",
        ).grid(row=8, column=0, sticky="w")
        self._build_page_format_field(
            settings,
            row=9,
            value=self.template_page_format_value,
        )
        self.blank_template_pdf_button = ttk.Button(
            settings,
            text="Uložit prázdnou šablonu (PDF)…",
            command=self.save_blank_template_pdf,
            state="disabled",
            style="Primary.TButton",
        )
        self.blank_template_pdf_button.grid(
            row=10,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )
        self.blank_template_data_button = ttk.Button(
            settings,
            text="Uložit datovou šablonu (YAML)…",
            command=self.save_blank_template_data,
            state="disabled",
        )
        self.blank_template_data_button.grid(
            row=11,
            column=0,
            sticky="ew",
            pady=(5, 0),
        )
        ttk.Label(
            settings,
            text=(
                "PDF je prázdná kresba k vytištění. YAML uchovává sloty "
                "a role buněk pro pozdější automatické vyplnění."
            ),
            style="Muted.TLabel",
            wraplength=310,
            justify="left",
        ).grid(row=12, column=0, sticky="w", pady=(9, 0))

        workspace = ttk.Frame(tab)
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)

        preview_frame = ttk.LabelFrame(
            workspace,
            text="Náhled prázdné šablony",
            padding=12,
        )
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.blank_template_preview = SpecificationPreview(
            preview_frame,
            width=620,
            height=440,
        )
        self.blank_template_preview.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            preview_frame,
            text=(
                "Otazník označuje buňku pro vepsanou nápovědu; čísla "
                "označují začátky hesel s nápovědami pod mřížkou."
            ),
            style="Muted.TLabel",
            wraplength=620,
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.template_status_label = ttk.Label(
            workspace,
            textvariable=self.template_status_value,
            style="Muted.TLabel",
            wraplength=620,
        )
        self.template_status_label.grid(
            row=1,
            column=0,
            sticky="w",
            pady=(10, 0),
        )

    def _watch_inputs(self) -> None:
        self.width_value.trace_add("write", self._crossword_input_changed)
        self.height_value.trace_add("write", self._crossword_input_changed)
        self.layout_value.trace_add("write", self._crossword_input_changed)
        self.template_width_value.trace_add(
            "write",
            self._template_input_changed,
        )
        self.template_height_value.trace_add(
            "write",
            self._template_input_changed,
        )
        self.template_layout_value.trace_add(
            "write",
            self._template_input_changed,
        )

    @staticmethod
    def _layout_description(layout: str) -> str:
        if layout == "numbered":
            return (
                "Všechna pole zůstávají pro písmena; nápovědy budou "
                "očíslované a vysázené pod mřížkou."
            )
        return (
            "Každé heslo potřebuje volné pole pro nápovědu: vlevo před "
            "vodorovným nebo nahoře před svislým heslem."
        )

    def _crossword_input_changed(self, *_args: str) -> None:
        self.refresh_specification()

    def _template_input_changed(self, *_args: str) -> None:
        self.refresh_blank_template()

    def _current_settings(self) -> SpecificationSettings:
        return parse_specification_settings(
            self.width_value.get(),
            self.height_value.get(),
        )

    def _current_template_settings(self) -> SpecificationSettings:
        return parse_template_settings(
            self.template_width_value.get(),
            self.template_height_value.get(),
        )

    def _selected_word_index(self) -> int | None:
        selection = self.words_tree.selection()
        return int(selection[0]) if selection else None

    def _set_crossword_output_state(self, state: str) -> None:
        self.puzzle_button.configure(state=state)
        self.solution_button.configure(state=state)
        self.crossword_template_button.configure(state=state)

    def _set_blank_template_output_state(self, state: str) -> None:
        self.blank_template_pdf_button.configure(state=state)
        self.blank_template_data_button.configure(state=state)

    def refresh_specification(self) -> bool:
        layout = cast(SpecificationLayout, self.layout_value.get())
        self.crossword_layout_help_value.set(self._layout_description(layout))
        try:
            settings = self._current_settings()
        except GuiInputError as error:
            self._specification = None
            self._prepared_crossword = None
            self._set_crossword_output_state("disabled")
            self.preview.clear_preview("Zadejte platný rozměr mřížky.")
            self._set_crossword_status(str(error), error=True)
            return False

        words = tuple(self._words)
        selected_index = self._selected_word_index()
        dimensions = GridDimensions(
            width=settings.width,
            height=settings.height,
        )
        self.preview.show_draft(dimensions, words, selected_index)
        if not words:
            self._specification = None
            self._prepared_crossword = None
            self._set_crossword_output_state("disabled")
            self._set_crossword_status(
                f"Mřížka {settings.width} × {settings.height} je připravena. "
                "Přidejte první heslo."
            )
            return False

        try:
            specification = create_specification(settings, words)
        except GuiInputError as error:
            self._specification = None
            self._prepared_crossword = None
            self._set_crossword_output_state("disabled")
            self._set_crossword_status(f"Hesla nejsou platná: {error}", error=True)
            return False

        self._specification = specification
        try:
            prepared = prepare_crossword(specification, layout)
        except GuiInputError as error:
            self._prepared_crossword = None
            self._set_crossword_output_state("disabled")
            self._set_crossword_status(
                f"Hesla jsou platná, ale vybraná podoba křížovky není: {error}",
                error=True,
            )
            return True

        self._prepared_crossword = prepared
        self._set_crossword_output_state("normal")
        self.preview.show_crossword(
            prepared.grid,
            words=words,
            selected_index=selected_index,
            show_letters=True,
        )
        self._set_crossword_status(
            f"Křížovka je připravená: {settings.width} × {settings.height}, "
            f"{_word_count_text(len(words))}. Můžete uložit PDF bez písmen "
            "nebo řešení."
        )
        return True

    def refresh_blank_template(self) -> bool:
        layout = cast(SpecificationLayout, self.template_layout_value.get())
        self.template_layout_help_value.set(self._layout_description(layout))
        try:
            settings = self._current_template_settings()
        except GuiInputError as error:
            self._blank_template = None
            self._blank_grid = None
            self._set_blank_template_output_state("disabled")
            self.blank_template_preview.clear_preview("Zadejte platný rozměr šablony.")
            self._set_template_status(str(error), error=True)
            return False

        dimensions = GridDimensions(
            width=settings.width,
            height=settings.height,
        )
        try:
            template = create_blank_template(settings, layout)
        except GuiInputError as error:
            self._blank_template = None
            self._blank_grid = None
            self._set_blank_template_output_state("disabled")
            self.blank_template_preview.show_draft(dimensions, ())
            self._set_template_status(
                f"Šablonu nelze pro tento rozměr vytvořit: {error}",
                error=True,
            )
            return False

        grid = create_grid_from_template(template)
        self._blank_template = template
        self._blank_grid = grid
        self._set_blank_template_output_state("normal")
        self.blank_template_preview.show_crossword(grid, show_letters=False)
        self._set_template_status(
            f"Prázdná šablona {settings.width} × {settings.height} je "
            f"připravená; obsahuje {_word_count_text(len(template.slots))} "
            "k vyplnění."
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
            self._show_action_error(
                "Heslo nelze přidat",
                str(error),
                template_tab=False,
            )
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
        self.word_button.configure(text="Přidat heslo do mřížky")
        self.cancel_edit_button.configure(state="disabled")
        for selected in self.words_tree.selection():
            self.words_tree.selection_remove(selected)
        self._word_selection_changed()
        self.answer_entry.focus_set()

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

    def _prepared_crossword_or_error(self) -> PreparedCrossword | None:
        self.refresh_specification()
        if self._prepared_crossword is not None:
            return self._prepared_crossword
        message = (
            "Přidejte alespoň jedno platné heslo a opravte chybu uvedenou pod náhledem."
        )
        self._show_action_error(
            "Křížovka není připravena",
            message,
            template_tab=False,
        )
        return None

    def save_crossword_pdf(self) -> None:
        prepared = self._prepared_crossword_or_error()
        if prepared is None:
            return
        self._save_pdf(
            prepared.grid,
            filled=False,
            title="Uložit křížovku bez písmen",
            initialfile="krizovka.pdf",
            success_message="Křížovka bez písmen byla uložena",
            page_format=self.page_format_value.get(),
            template_tab=False,
        )

    def save_solution_pdf(self) -> None:
        prepared = self._prepared_crossword_or_error()
        if prepared is None:
            return
        self._save_pdf(
            prepared.grid,
            filled=True,
            title="Uložit řešení křížovky",
            initialfile="reseni.pdf",
            success_message="Řešení bylo uloženo",
            page_format=self.page_format_value.get(),
            template_tab=False,
        )

    def save_blank_template_pdf(self) -> None:
        if not self.refresh_blank_template() or self._blank_grid is None:
            self._show_action_error(
                "Šablona není připravena",
                "Opravte chybu uvedenou pod náhledem.",
                template_tab=True,
            )
            return
        self._save_pdf(
            self._blank_grid,
            filled=False,
            title="Uložit prázdnou šablonu",
            initialfile="prazdna-sablona.pdf",
            success_message="Prázdná šablona byla uložena",
            page_format=self.template_page_format_value.get(),
            template_tab=True,
        )

    def _save_pdf(
        self,
        crossword: CrosswordGrid,
        *,
        filled: bool,
        title: str,
        initialfile: str,
        success_message: str,
        page_format: str,
        template_tab: bool,
    ) -> None:
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

        if template_tab:
            self._set_template_status("Vytvářím PDF…")
        else:
            self._set_crossword_status("Vytvářím PDF…")
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
                template_tab=template_tab,
            )
            return
        finally:
            self.root.configure(cursor="")
        if template_tab:
            self._set_template_status(
                f"{success_message}: {output}",
                success=True,
            )
        else:
            self._set_crossword_status(
                f"{success_message}: {output}",
                success=True,
            )

    def save_specification(self) -> None:
        if not self.refresh_specification() or self._specification is None:
            self._show_action_error(
                "Zdrojová data nelze uložit",
                "Přidejte alespoň jedno platné heslo.",
                template_tab=False,
            )
            return
        selected = self._choose_output(
            title="Uložit zdrojová data vlastních hesel",
            initialfile="zadani.yaml",
            extension=".yaml",
            filetypes=(
                ("YAML soubory", "*.yaml *.yml"),
                ("Všechny soubory", "*"),
            ),
            overwrite_title="Přepsat zdrojová data?",
        )
        if selected is None:
            return
        output, overwrite = selected
        try:
            write_crossword_specification(
                self._specification,
                output,
                overwrite=overwrite,
            )
        except ModelError as error:
            self._show_action_error(
                "Zdrojová data nelze uložit",
                str(error),
                template_tab=False,
            )
            return
        self._set_crossword_status(
            f"Zdrojová data uložena: {output}",
            success=True,
        )

    def save_template(self) -> None:
        prepared = self._prepared_crossword_or_error()
        if prepared is None:
            return
        self._save_template_data(
            prepared.template,
            title="Uložit datovou šablonu křížovky",
            initialfile="sablona-krizovky.yaml",
            template_tab=False,
        )

    def save_blank_template_data(self) -> None:
        if not self.refresh_blank_template() or self._blank_template is None:
            self._show_action_error(
                "Datovou šablonu nelze uložit",
                "Opravte chybu uvedenou pod náhledem.",
                template_tab=True,
            )
            return
        self._save_template_data(
            self._blank_template,
            title="Uložit prázdnou datovou šablonu",
            initialfile="prazdna-sablona.yaml",
            template_tab=True,
        )

    def _save_template_data(
        self,
        template: CrosswordTemplate,
        *,
        title: str,
        initialfile: str,
        template_tab: bool,
    ) -> None:
        selected = self._choose_output(
            title=title,
            initialfile=initialfile,
            extension=".yaml",
            filetypes=(
                ("YAML soubory", "*.yaml *.yml"),
                ("Všechny soubory", "*"),
            ),
            overwrite_title="Přepsat datovou šablonu?",
        )
        if selected is None:
            return
        output, overwrite = selected
        try:
            write_crossword_template(
                template,
                output,
                overwrite=overwrite,
            )
        except ModelError as error:
            self._show_action_error(
                "Datovou šablonu nelze uložit",
                str(error),
                template_tab=template_tab,
            )
            return
        if template_tab:
            self._set_template_status(
                f"Datová šablona uložena: {output}",
                success=True,
            )
        else:
            self._set_crossword_status(
                f"Datová šablona uložena: {output}",
                success=True,
            )

    def save_current_pdf(self) -> None:
        if self.notebook.index("current") == 0:
            self.save_crossword_pdf()
        else:
            self.save_blank_template_pdf()

    def save_current_data_template(self) -> None:
        if self.notebook.index("current") == 0:
            self.save_template()
        else:
            self.save_blank_template_data()

    def _show_action_error(
        self,
        title: str,
        message: str,
        *,
        template_tab: bool,
    ) -> None:
        if template_tab:
            self._set_template_status(message, error=True)
        else:
            self._set_crossword_status(message, error=True)
        messagebox.showerror(title, message, parent=self.root)

    @staticmethod
    def _status_style(*, error: bool, success: bool) -> str:
        if error:
            return "Error.TLabel"
        if success:
            return "Success.TLabel"
        return "Muted.TLabel"

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

    def _edit_event(self, _event: tk.Event[tk.Misc]) -> None:
        self.edit_selected_word()

    def _save_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.save_current_pdf()
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

"""Grafické rozhraní Křížovkáře postavené na Tk."""

from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Literal, cast

from krizovkar.generator import (
    DEFAULT_GRID_HEIGHT,
    DEFAULT_GRID_WIDTH,
    GenerationError,
    create_grid_from_template,
    generate_numbered_template,
    generate_swedish_template,
)
from krizovkar.localization import ngettext
from krizovkar.model import (
    CrosswordGrid,
    CrosswordTemplate,
    LetterCell,
    ModelError,
    SecretCell,
    TemplateEmptyCell,
    TemplateLegendCell,
    write_crossword_template,
)

TemplateLayout = Literal["swedish", "numbered"]
_TEMPLATE_LAYOUTS = frozenset(("swedish", "numbered"))


class GuiInputError(ValueError):
    """Nastavení zadané v grafickém rozhraní není platné."""


@dataclass(frozen=True, slots=True)
class TemplateSettings:
    """Nastavení prvního kroku tvorby křížovky."""

    layout: TemplateLayout
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


def parse_template_settings(
    layout: str,
    width: str,
    height: str,
) -> TemplateSettings:
    """Převede textová pole formuláře na nastavení šablony."""

    if layout not in _TEMPLATE_LAYOUTS:
        raise GuiInputError("Vyberte způsob rozvržení.")
    return TemplateSettings(
        layout=cast(TemplateLayout, layout),
        width=_positive_integer(width, "Počet sloupců"),
        height=_positive_integer(height, "Počet řádků"),
    )


def create_template(settings: TemplateSettings) -> CrosswordTemplate:
    """Vytvoří šablonu pomocí stejných generátorů jako CLI."""

    generator = (
        generate_numbered_template
        if settings.layout == "numbered"
        else generate_swedish_template
    )
    return generator(width=settings.width, height=settings.height)


def _slot_count_text(count: int) -> str:
    return f"{count} {ngettext('slot', 'slotů', count)}"


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


class TemplatePreview(tk.Canvas):
    """Jednoduchý náhled rolí buněk vytvořené šablony."""

    _LETTER_FILL = "#ffffff"
    _LEGEND_FILL = "#f7e7b2"
    _EMPTY_FILL = "#e5e7eb"
    _GRID_COLOR = "#475467"
    _EMPTY_MARK_COLOR = "#98a2b3"
    _NUMBER_COLOR = "#344054"

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        super().__init__(
            master,
            background="#f8fafc",
            highlightbackground="#cbd5e1",
            highlightthickness=1,
            **kwargs,
        )
        self._template: CrosswordTemplate | None = None
        self._grid: CrosswordGrid | None = None
        self._empty_message = "Náhled se zobrazí po vytvoření šablony."
        self.bind("<Configure>", self._redraw)

    def show_template(self, template: CrosswordTemplate) -> None:
        self._template = template
        self._grid = create_grid_from_template(template)
        self._redraw()

    def clear_template(self, message: str) -> None:
        self._template = None
        self._grid = None
        self._empty_message = message
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.delete("all")
        template = self._template
        if template is None:
            self.create_text(
                max(self.winfo_width(), 2) / 2,
                max(self.winfo_height(), 2) / 2,
                text=self._empty_message,
                fill="#667085",
                width=max(self.winfo_width() - 48, 120),
                justify="center",
            )
            return

        canvas_width = max(self.winfo_width(), 2)
        canvas_height = max(self.winfo_height(), 2)
        available_width = max(canvas_width - 32, 1)
        available_height = max(canvas_height - 32, 1)
        cell_size = min(
            available_width / template.grid.width,
            available_height / template.grid.height,
            36,
        )
        grid_width = cell_size * template.grid.width
        grid_height = cell_size * template.grid.height
        left = (canvas_width - grid_width) / 2
        top = (canvas_height - grid_height) / 2

        for row_index, row in enumerate(template.grid.cells):
            for column_index, cell in enumerate(row):
                x1 = left + column_index * cell_size
                y1 = top + row_index * cell_size
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                if isinstance(cell, TemplateLegendCell):
                    fill = self._LEGEND_FILL
                elif isinstance(cell, TemplateEmptyCell):
                    fill = self._EMPTY_FILL
                else:
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
                if isinstance(cell, TemplateEmptyCell) and cell_size >= 7:
                    inset = max(cell_size * 0.22, 2)
                    self.create_line(
                        x1 + inset,
                        y1 + inset,
                        x2 - inset,
                        y2 - inset,
                        fill=self._EMPTY_MARK_COLOR,
                    )
                    self.create_line(
                        x2 - inset,
                        y1 + inset,
                        x1 + inset,
                        y2 - inset,
                        fill=self._EMPTY_MARK_COLOR,
                    )

        self._draw_numbered_annotations(left, top, cell_size)
        self.create_rectangle(
            left,
            top,
            left + grid_width,
            top + grid_height,
            outline="#101828",
            width=2,
        )

    def _draw_numbered_annotations(
        self,
        left: float,
        top: float,
        cell_size: float,
    ) -> None:
        if self._grid is None or self._grid.grid.cells is None:
            return
        for row_index, row in enumerate(self._grid.grid.cells):
            for column_index, cell in enumerate(row):
                if not isinstance(cell, (LetterCell, SecretCell)):
                    continue
                x1 = left + column_index * cell_size
                y1 = top + row_index * cell_size
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                if cell.number is not None and cell_size >= 15:
                    self.create_text(
                        x1 + 3,
                        y1 + 2,
                        text=str(cell.number),
                        anchor="nw",
                        fill=self._NUMBER_COLOR,
                        font=("TkDefaultFont", max(7, int(cell_size * 0.28))),
                    )
                if "right" in cell.bars:
                    self.create_line(
                        x2,
                        y1,
                        x2,
                        y2,
                        fill="#101828",
                        width=3,
                    )
                if "bottom" in cell.bars:
                    self.create_line(
                        x1,
                        y2,
                        x2,
                        y2,
                        fill="#101828",
                        width=3,
                    )


class CrosswordApplication(ttk.Frame):
    """Hlavní okno s prvním krokem tvorby křížovky."""

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, padding=(24, 20))
        self.root = root
        self._template: CrosswordTemplate | None = None
        self._settings: TemplateSettings | None = None
        self.layout_value = tk.StringVar(value="swedish")
        self.width_value = tk.StringVar(value=str(DEFAULT_GRID_WIDTH))
        self.height_value = tk.StringVar(value=str(DEFAULT_GRID_HEIGHT))
        self.status_value = tk.StringVar(value="Připravuji výchozí náhled…")

        self._configure_window()
        self._configure_styles()
        self._build_menu()
        self._build_content()
        self._watch_settings()
        self.root.after_idle(self.refresh_template)

    def _configure_window(self) -> None:
        self.root.title("Křížovkář")
        self.root.geometry("960x620")
        self.root.minsize(760, 520)
        self.root.option_add("*tearOff", False)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure(
            "Title.TLabel",
            font=("TkDefaultFont", 22, "bold"),
        )
        style.configure(
            "Step.TLabel",
            foreground="#175cd3",
            font=("TkDefaultFont", 10, "bold"),
        )
        style.configure("Muted.TLabel", foreground="#667085")
        style.configure("Error.TLabel", foreground="#b42318")
        style.configure("Success.TLabel", foreground="#067647")

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu)
        file_menu.add_command(
            label="Uložit šablonu…",
            accelerator="Ctrl+S",
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
            text="PRVNÍ KROK  ·  ŠABLONA",
            style="Step.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            self,
            text="Křížovkář",
            style="Title.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(
            self,
            text=(
                "Zvolte rozvržení a rozměr. Křížovkář vytvoří "
                "nevyplněnou šablonu pro navazující doplnění hesel."
            ),
            style="Muted.TLabel",
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(2, 18),
        )

        settings = ttk.LabelFrame(self, text="Nastavení šablony", padding=16)
        settings.grid(row=3, column=0, sticky="nsew", padx=(0, 16))
        settings.columnconfigure(0, weight=1)

        ttk.Label(settings, text="Rozvržení").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.swedish_button = ttk.Radiobutton(
            settings,
            text="Švédské – legendy v mřížce",
            variable=self.layout_value,
            value="swedish",
        )
        self.swedish_button.grid(row=1, column=0, sticky="w", pady=(6, 2))
        ttk.Radiobutton(
            settings,
            text="Číslované – legendy pod mřížkou",
            variable=self.layout_value,
            value="numbered",
        ).grid(row=2, column=0, sticky="w", pady=2)

        ttk.Separator(settings).grid(
            row=3,
            column=0,
            sticky="ew",
            pady=16,
        )
        ttk.Label(settings, text="Rozměr mřížky").grid(
            row=4,
            column=0,
            sticky="w",
        )
        dimensions = ttk.Frame(settings)
        dimensions.grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Label(dimensions, text="Sloupce").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            dimensions,
            from_=1,
            to=100,
            width=7,
            textvariable=self.width_value,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(dimensions, text="×").grid(
            row=1,
            column=1,
            padx=10,
        )
        ttk.Label(dimensions, text="Řádky").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(
            dimensions,
            from_=1,
            to=100,
            width=7,
            textvariable=self.height_value,
        ).grid(row=1, column=2, sticky="w", pady=(3, 0))

        ttk.Label(
            settings,
            text=("Generátor rozdělí obě osy na hesla o délce 3 až 8 polí."),
            style="Muted.TLabel",
            wraplength=260,
        ).grid(row=6, column=0, sticky="w", pady=(14, 0))

        actions = ttk.Frame(settings)
        actions.grid(row=7, column=0, sticky="ew", pady=(24, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Button(
            actions,
            text="Aktualizovat náhled",
            command=self.refresh_template,
        ).grid(row=0, column=0, sticky="ew")
        self.save_button = ttk.Button(
            actions,
            text="Uložit šablonu…",
            command=self.save_template,
            state="disabled",
        )
        self.save_button.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        preview_frame = ttk.LabelFrame(self, text="Náhled rozvržení", padding=12)
        preview_frame.grid(row=3, column=1, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.preview = TemplatePreview(preview_frame, width=520, height=390)
        self.preview.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            preview_frame,
            text=("Bílá: písmena  ·  Žlutá: legendy  ·  Šedá: nevyplňovaná pole"),
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(10, 0))

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
            wraplength=880,
        )
        self.status_label.grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="w",
        )

    def _watch_settings(self) -> None:
        for variable in (
            self.layout_value,
            self.width_value,
            self.height_value,
        ):
            variable.trace_add("write", self._mark_template_outdated)

    def _mark_template_outdated(self, *_args: str) -> None:
        if self._template is None:
            return
        self._template = None
        self._settings = None
        self.save_button.configure(state="disabled")
        self.preview.clear_template("Nastavení se změnilo. Aktualizujte náhled.")
        self._set_status("Nastavení se změnilo; před uložením vytvořte nový náhled.")

    def refresh_template(self) -> bool:
        try:
            settings = parse_template_settings(
                self.layout_value.get(),
                self.width_value.get(),
                self.height_value.get(),
            )
            template = create_template(settings)
        except (GuiInputError, GenerationError) as error:
            self._template = None
            self._settings = None
            self.save_button.configure(state="disabled")
            self.preview.clear_template("Pro toto nastavení nelze zobrazit náhled.")
            self._set_status(f"Náhled nelze vytvořit: {error}", error=True)
            return False

        self._template = template
        self._settings = settings
        self.preview.show_template(template)
        self.save_button.configure(state="normal")
        self._set_status(
            "Náhled připraven: "
            f"{settings.width} × {settings.height}, "
            f"{_slot_count_text(len(template.slots))}."
        )
        return True

    def save_template(self) -> None:
        if self._template is None and not self.refresh_template():
            return
        assert self._template is not None
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
                self._template,
                output,
                overwrite=overwrite,
            )
        except ModelError as error:
            self._set_status(f"Šablonu nelze uložit: {error}", error=True)
            messagebox.showerror(
                "Šablonu nelze uložit",
                str(error),
                parent=self.root,
            )
            return

        self._set_status(f"Šablona uložena: {output}", success=True)

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

    def _save_event(self, _event: tk.Event[tk.Misc]) -> str:
        self.save_template()
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

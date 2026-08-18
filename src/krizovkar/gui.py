"""Grafické rozhraní Křížovkáře postavené na Tk."""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Literal, cast

from krizovkar.alphabet import split_answer_letters
from krizovkar.generator import (
    DEFAULT_GRID_HEIGHT,
    DEFAULT_GRID_WIDTH,
    GenerationError,
    SpecificationLayout,
    create_grid_from_crossword,
    crossword_external_slot_numbers,
    generate_numbered_template,
    generate_swedish_template,
)
from krizovkar.layout import MIN_SEGMENT_LENGTH
from krizovkar.localization import ngettext
from krizovkar.model import (
    Coordinate,
    CrosswordDocument,
    CrosswordGrid,
    CrosswordSecret,
    CrosswordSecretCellsPart,
    CrosswordSecretSlotPart,
    EmptyCell,
    EmptyCellRole,
    HelpCell,
    LegendCell,
    LegendCellRole,
    LetterCell,
    LetterCellRole,
    ModelError,
    SecretCell,
    WordDirection,
    WordSlot,
    cell_numbers,
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
_MINIMUM_TK_VERSION = 9.0
_GRID_RESIZE_HIT_RADIUS = 7
_GRID_RESIZE_HANDLE_RADIUS = 3
_GRID_RESIZE_FEEDBACK_TAG = "grid-resize-feedback"
_WINDOW_MENU_SELECTION_VARIABLE = "krizovkar_active_window"
_SHADOW_ANSWER_TAG = "shadow-answer"
_SLOT_LIST_PLACEMENT_MAIN = "main"
_SLOT_LIST_PLACEMENT_WINDOW = "window"
_SLOT_TREE_STYLE = "KrizovkarSlots.Treeview"
# Výchozí pole Aqua potřebuje 27 px plus okraj buňky.
_SLOT_TREE_ROW_HEIGHT = 30
_SLOT_COMPACT_COLUMN_WIDTH = 60
# Některé motivy kreslí uvnitř Treeviewu dvoupixelový rámeček.
_SLOT_TABLE_HORIZONTAL_INSET = 4
_SLOT_EDITOR_STYLE = "KrizovkarSlot.TEntry"
_SLOT_EDITOR_ERROR_COLOR = "#c62828"
_PROJECT_REPOSITORY_URL = "https://github.com/Glutexo/krizovkar"
_DIRECTION_LABELS = {
    "horizontal": "→",
    "vertical": "↓",
}
_CELL_SLOT_LABELS: dict[WordDirection, str] = {
    "horizontal": "Heslo →",
    "vertical": "Heslo ↓",
}
_DIRECTION_STEPS: dict[WordDirection, tuple[int, int]] = {
    "horizontal": (0, 1),
    "vertical": (1, 0),
}

EditableCellRole = Literal["letter", "secret", "legend", "empty"]


class GuiInputError(ValueError):
    """Nastavení zadané v grafickém rozhraní není platné."""


class _CrossingConflictError(GuiInputError):
    """Zadané heslo odporuje písmenu už uloženému na křížení."""


@dataclass(frozen=True, slots=True)
class CrosswordSettings:
    """Rozměr automaticky rozvrhované křížovky."""

    width: int
    height: int


@dataclass(frozen=True, slots=True)
class _GridResizeDrag:
    """Počáteční stav tažení jednoho okraje nebo rohu náhledu."""

    horizontal_edge: int
    vertical_edge: int
    start_x: float
    start_y: float
    start_width: int
    start_height: int
    cell_size: float


@dataclass(frozen=True, slots=True)
class _KeyboardShortcut:
    """Popisek nabídky a odpovídající vazba kláves podle platformy."""

    accelerator: str
    sequence: str


@dataclass(frozen=True, slots=True)
class _ExportAction:
    """Jedna položka nabídky exportu."""

    identifier: str
    label: str
    command: Callable[[], None]


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


def _multiple_cell_selection_sequence() -> str:
    modifier = "Command" if sys.platform == "darwin" else "Control"
    return f"<{modifier}-Button-1>"


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


def _create_view_menu(
    parent: tk.Menu,
    command: Callable[[], None] | None,
) -> tk.Menu:
    menu = tk.Menu(parent)
    options: dict[str, object] = {
        "label": "Zdroj YAML",
        "state": "normal" if command is not None else "disabled",
    }
    if command is not None:
        options["command"] = command
    menu.add_command(**options)
    return menu


def _create_slot_list_placement_menu(
    parent: tk.Menu,
    *,
    variable: str,
    selected: str,
    command: Callable[[str], None],
) -> tk.Menu:
    menu = tk.Menu(parent)
    menu.setvar(variable, selected)
    for label, value in (
        ("V hlavním okně", _SLOT_LIST_PLACEMENT_MAIN),
        ("V samostatném okně", _SLOT_LIST_PLACEMENT_WINDOW),
    ):
        menu.add_radiobutton(
            label=label,
            variable=variable,
            value=value,
            command=lambda placement=value: command(placement),
        )
    return menu


def _create_help_menu(parent: tk.Menu) -> tk.Menu:
    menu = tk.Menu(parent, name="help")
    menu.add_command(
        label="Křížovkář na GitHubu",
        command=lambda: webbrowser.open_new_tab(_PROJECT_REPOSITORY_URL),
    )
    return menu


def _bind_text_entry_context_menu(editor: ttk.Entry) -> None:
    menu = tk.Menu(editor, tearoff=False)
    for label, event_name in (
        ("Vyjmout", "<<Cut>>"),
        ("Kopírovat", "<<Copy>>"),
        ("Vložit", "<<Paste>>"),
    ):
        menu.add_command(
            label=label,
            command=lambda name=event_name: editor.event_generate(name),
        )
    menu.add_separator()
    menu.add_command(
        label="Vybrat vše",
        command=lambda: editor.event_generate("<<SelectAll>>"),
    )

    def show_context_menu(event: tk.Event[tk.Misc]) -> str:
        selection_state = (
            tk.NORMAL if editor.selection_present() else tk.DISABLED
        )
        menu.entryconfigure("Vyjmout", state=selection_state)
        menu.entryconfigure("Kopírovat", state=selection_state)
        try:
            editor.clipboard_get()
        except tk.TclError:
            paste_state = tk.DISABLED
        else:
            paste_state = tk.NORMAL
        menu.entryconfigure("Vložit", state=paste_state)
        menu.entryconfigure(
            "Vybrat vše",
            state=tk.NORMAL if editor.get() else tk.DISABLED,
        )
        editor.focus_set()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    editor.bind("<<ContextMenu>>", show_context_menu, add="+")


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


def _minimum_generated_dimension(layout: SpecificationLayout | None) -> int:
    if layout == "numbered":
        return MIN_SEGMENT_LENGTH
    return MIN_SEGMENT_LENGTH + 1


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


def _shift_coordinate(
    coordinate: Coordinate,
    direction: WordDirection,
    distance: int,
) -> Coordinate:
    row_step, column_step = _DIRECTION_STEPS[direction]
    return Coordinate(
        row=coordinate.row + distance * row_step,
        column=coordinate.column + distance * column_step,
    )


def _blank_changed_slot(slot: WordSlot, **changes: object) -> WordSlot:
    return replace(
        slot,
        answer=None,
        clue=None,
        in_help=False,
        **changes,
    )


def _next_slot_identifier(
    identifiers: set[str],
    direction: WordDirection,
) -> str:
    prefix = "h" if direction == "horizontal" else "v"
    number = 1
    while f"{prefix}{number}" in identifiers:
        number += 1
    identifier = f"{prefix}{number}"
    identifiers.add(identifier)
    return identifier


def _secrets_after_cell_role_change(
    crossword: CrosswordDocument,
    affected_slots: set[str],
    coordinate: Coordinate,
) -> tuple[CrosswordSecret, ...]:
    slots_by_identifier = {
        slot.identifier: slot for slot in crossword.slots
    }
    secrets: list[CrosswordSecret] = []
    for secret in crossword.secrets:
        if any(
            isinstance(part, CrosswordSecretSlotPart)
            and (
                part.slot_identifier in affected_slots
                or coordinate
                in slot_coordinates(slots_by_identifier[part.slot_identifier])
            )
            for part in secret.parts
        ):
            continue

        parts: list[CrosswordSecretSlotPart | CrosswordSecretCellsPart] = []
        for part in secret.parts:
            if not (
                isinstance(part, CrosswordSecretCellsPart)
                and coordinate in part.cells
            ):
                parts.append(part)
                continue
            remaining = tuple(
                cell for cell in part.cells if cell != coordinate
            )
            if remaining:
                parts.append(
                    replace(part, cells=remaining, arrows=False)
                    if part.arrows
                    else replace(part, cells=remaining)
                )
        if parts:
            secrets.append(replace(secret, parts=tuple(parts)))
    return tuple(secrets)


def _crossword_secret_coordinates(
    crossword: CrosswordDocument,
) -> frozenset[Coordinate]:
    slots_by_identifier = {
        slot.identifier: slot for slot in crossword.slots
    }
    coordinates: set[Coordinate] = set()
    for secret in crossword.secrets:
        for part in secret.parts:
            if isinstance(part, CrosswordSecretSlotPart):
                coordinates.update(
                    slot_coordinates(slots_by_identifier[part.slot_identifier])
                )
            else:
                coordinates.update(part.cells)
    return frozenset(coordinates)


def _crossword_with_cell_role(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
    role: LetterCellRole | LegendCellRole | EmptyCellRole,
    slots: tuple[WordSlot, ...],
    affected_slots: set[str],
) -> CrosswordDocument:
    rows = [list(row) for row in crossword.grid.cells]
    rows[coordinate.row - 1][coordinate.column - 1] = role
    used_legends = {
        slot.legend_position
        for slot in slots
        if slot.legend_position is not None
    }
    for row_index, row in enumerate(rows, start=1):
        for column_index, cell in enumerate(row, start=1):
            cell_coordinate = Coordinate(row_index, column_index)
            if (
                isinstance(cell, LegendCellRole)
                and cell_coordinate not in used_legends
            ):
                row[column_index - 1] = EmptyCellRole()
    return replace(
        crossword,
        grid=replace(
            crossword.grid,
            cells=tuple(tuple(row) for row in rows),
        ),
        slots=slots,
        secrets=_secrets_after_cell_role_change(
            crossword,
            affected_slots,
            coordinate,
        ),
    )


def _letter_cell_to_nonletter(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
    role: LegendCellRole | EmptyCellRole,
) -> CrosswordDocument:
    identifiers = {slot.identifier for slot in crossword.slots}
    affected_slots: set[str] = set()
    slots: list[WordSlot] = []
    legend_position = (
        coordinate if isinstance(role, LegendCellRole) else None
    )

    for slot in crossword.slots:
        coordinates = slot_coordinates(slot)
        if coordinate not in coordinates:
            slots.append(slot)
            continue
        if slot.in_help:
            raise GuiInputError(
                "Roli pole nelze změnit, protože jím prochází heslo "
                "uvedené v pomůcce."
            )

        affected_slots.add(slot.identifier)
        had_inline_legend = slot.legend_position is not None
        offset = coordinates.index(coordinate)
        before_length = offset
        after_length = slot.length - offset - 1
        if before_length:
            slots.append(
                _blank_changed_slot(slot, length=before_length)
            )
        if not after_length:
            continue
        if isinstance(role, EmptyCellRole) and had_inline_legend:
            continue

        after_start = coordinates[offset + 1]
        if before_length:
            slots.append(
                WordSlot(
                    identifier=_next_slot_identifier(
                        identifiers,
                        slot.direction,
                    ),
                    start=after_start,
                    direction=slot.direction,
                    length=after_length,
                    legend_position=legend_position,
                )
            )
        else:
            slots.append(
                _blank_changed_slot(
                    slot,
                    start=after_start,
                    length=after_length,
                    legend_position=legend_position,
                )
            )

    if isinstance(role, LegendCellRole):
        for index, slot in enumerate(slots):
            expected_start = _shift_coordinate(coordinate, slot.direction, 1)
            if slot.start == expected_start and slot.legend_position is None:
                slots[index] = replace(slot, legend_position=coordinate)

        if not any(slot.legend_position == coordinate for slot in slots):
            raise GuiInputError(
                "Legenda musí mít bezprostředně napravo nebo pod sebou "
                "místo pro heslo."
            )

    return _crossword_with_cell_role(
        crossword,
        coordinate,
        role,
        tuple(slots),
        affected_slots,
    )


def _nonletter_cell_to_letter(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
) -> CrosswordDocument:
    replacements: dict[str, WordSlot] = {}
    removed_slots: set[str] = set()
    affected_slots: set[str] = set()

    for direction in ("horizontal", "vertical"):
        before_coordinate = _shift_coordinate(coordinate, direction, -1)
        after_coordinate = _shift_coordinate(coordinate, direction, 1)
        before = next(
            (
                slot
                for slot in crossword.slots
                if slot.direction == direction
                and slot_coordinates(slot)[-1] == before_coordinate
            ),
            None,
        )
        after = next(
            (
                slot
                for slot in crossword.slots
                if slot.direction == direction
                and slot.start == after_coordinate
            ),
            None,
        )
        changed = tuple(slot for slot in (before, after) if slot is not None)
        if any(slot.in_help for slot in changed):
            raise GuiInputError(
                "Roli pole nelze změnit, protože na něj navazuje heslo "
                "uvedené v pomůcce."
            )
        affected_slots.update(slot.identifier for slot in changed)

        if before is not None and after is not None:
            replacements[before.identifier] = _blank_changed_slot(
                before,
                length=before.length + 1 + after.length,
            )
            removed_slots.add(after.identifier)
        elif before is not None:
            replacements[before.identifier] = _blank_changed_slot(
                before,
                length=before.length + 1,
            )
        elif after is not None:
            replacements[after.identifier] = _blank_changed_slot(
                after,
                start=coordinate,
                length=after.length + 1,
                legend_position=None,
            )

    slots = tuple(
        replacements.get(slot.identifier, slot)
        for slot in crossword.slots
        if slot.identifier not in removed_slots
    )
    return _crossword_with_cell_role(
        crossword,
        coordinate,
        LetterCellRole(),
        slots,
        affected_slots,
    )


def _legend_cell_to_empty(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
) -> CrosswordDocument:
    slots = tuple(
        replace(slot, legend_position=None)
        if slot.legend_position == coordinate
        else slot
        for slot in crossword.slots
    )
    return _crossword_with_cell_role(
        crossword,
        coordinate,
        EmptyCellRole(),
        slots,
        set(),
    )


def _empty_cell_to_legend(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
) -> CrosswordDocument:
    slots: list[WordSlot] = []
    for slot in crossword.slots:
        expected_start = _shift_coordinate(coordinate, slot.direction, 1)
        if slot.start == expected_start and slot.legend_position is None:
            slot = replace(slot, legend_position=coordinate)
        slots.append(slot)

    if not any(slot.legend_position == coordinate for slot in slots):
        raise GuiInputError(
            "Legenda musí mít bezprostředně napravo nebo pod sebou "
            "místo pro heslo."
        )
    return _crossword_with_cell_role(
        crossword,
        coordinate,
        LegendCellRole(),
        tuple(slots),
        set(),
    )


def _add_crossword_secret_cells(
    crossword: CrosswordDocument,
    coordinates: Sequence[Coordinate],
) -> CrosswordDocument:
    ordered_coordinates = tuple(
        sorted(set(coordinates), key=lambda item: (item.row, item.column))
    )
    for coordinate in ordered_coordinates:
        if not (
            1 <= coordinate.row <= crossword.grid.height
            and 1 <= coordinate.column <= crossword.grid.width
        ):
            raise GuiInputError("Vybrané pole leží mimo křížovku.")

    changed = crossword
    for coordinate in ordered_coordinates:
        if coordinate in _crossword_secret_coordinates(changed):
            continue
        try:
            changed = set_crossword_cell_role(changed, coordinate, "letter")
        except GuiInputError as error:
            if len(ordered_coordinates) == 1:
                raise
            raise GuiInputError(
                f"Pole v řádku {coordinate.row}, sloupci "
                f"{coordinate.column}: {error}"
            ) from error

    secret_coordinates = _crossword_secret_coordinates(changed)
    additions = tuple(
        coordinate
        for coordinate in ordered_coordinates
        if coordinate not in secret_coordinates
    )
    if not additions:
        return changed
    changed = replace(
        changed,
        secrets=changed.secrets
        + (
            CrosswordSecret(
                parts=(CrosswordSecretCellsPart(cells=additions),),
            ),
        ),
    )
    try:
        dump_crossword_document(changed, StringIO())
    except ModelError as error:
        raise GuiInputError(
            "Pole nelze nastavit jako tajenku, aniž by vzniklo neplatné "
            f"rozvržení: {error}"
        ) from error
    return changed


def set_crossword_cell_role(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
    role: EditableCellRole,
) -> CrosswordDocument:
    """Přepne roli buňky a upraví navazující sloty."""

    if role not in {"letter", "secret", "legend", "empty"}:
        raise GuiInputError(f"Nepodporovaná role pole {role!r}.")
    if not (
        1 <= coordinate.row <= crossword.grid.height
        and 1 <= coordinate.column <= crossword.grid.width
    ):
        raise GuiInputError("Vybrané pole leží mimo křížovku.")
    if role == "secret":
        return _add_crossword_secret_cells(crossword, (coordinate,))

    current = crossword.grid.cells[coordinate.row - 1][coordinate.column - 1]
    if role == "letter" and isinstance(current, LetterCellRole):
        if coordinate not in _crossword_secret_coordinates(crossword):
            return crossword
        changed = replace(
            crossword,
            secrets=_secrets_after_cell_role_change(
                crossword,
                set(),
                coordinate,
            ),
        )
    elif (
        role == "legend" and isinstance(current, LegendCellRole)
    ) or (
        role == "empty" and isinstance(current, EmptyCellRole)
    ):
        return crossword
    elif not isinstance(
        current,
        (LetterCellRole, LegendCellRole, EmptyCellRole),
    ):
        raise GuiInputError(
            "Roli lze měnit pouze mezi písmenným, tajenkovým, legendovým "
            "a prázdným polem."
        )
    elif isinstance(current, LetterCellRole):
        changed = _letter_cell_to_nonletter(
            crossword,
            coordinate,
            LegendCellRole() if role == "legend" else EmptyCellRole(),
        )
    elif role == "letter":
        changed = _nonletter_cell_to_letter(crossword, coordinate)
    elif isinstance(current, LegendCellRole):
        changed = _legend_cell_to_empty(crossword, coordinate)
    else:
        changed = _empty_cell_to_legend(crossword, coordinate)
    try:
        dump_crossword_document(changed, StringIO())
    except ModelError as error:
        raise GuiInputError(
            "Roli tohoto pole nelze změnit, aniž by vzniklo neplatné "
            f"rozvržení: {error}"
        ) from error
    return changed


def set_crossword_cells_role(
    crossword: CrosswordDocument,
    coordinates: Sequence[Coordinate],
    role: EditableCellRole,
) -> CrosswordDocument:
    """Atomicky přepne roli všech vybraných buněk."""

    ordered_coordinates = tuple(
        sorted(set(coordinates), key=lambda item: (item.row, item.column))
    )
    if role == "secret":
        return _add_crossword_secret_cells(crossword, ordered_coordinates)
    changed = crossword
    for coordinate in ordered_coordinates:
        try:
            changed = set_crossword_cell_role(changed, coordinate, role)
        except GuiInputError as error:
            if len(ordered_coordinates) == 1:
                raise
            raise GuiInputError(
                f"Pole v řádku {coordinate.row}, sloupci "
                f"{coordinate.column}: {error}"
            ) from error
    return changed


def _secrets_after_slot_change(
    crossword: CrosswordDocument,
    affected_slots: set[str],
) -> tuple[CrosswordSecret, ...]:
    return tuple(
        secret
        for secret in crossword.secrets
        if not any(
            isinstance(part, CrosswordSecretSlotPart)
            and part.slot_identifier in affected_slots
            for part in secret.parts
        )
    )


def _crossword_with_slots(
    crossword: CrosswordDocument,
    slots: tuple[WordSlot, ...],
    affected_slots: set[str],
) -> CrosswordDocument:
    return replace(
        crossword,
        slots=slots,
        secrets=_secrets_after_slot_change(crossword, affected_slots),
    )


def _slot_order_key(slot: WordSlot) -> tuple[int, int, int]:
    return (
        0 if slot.direction == "horizontal" else 1,
        slot.start.row,
        slot.start.column,
    )


def _new_external_slot_length(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
    direction: WordDirection,
) -> int:
    following_starts = {
        slot.start
        for slot in crossword.slots
        if slot.direction == direction and slot.start != coordinate
    }
    current = coordinate
    length = 0
    while (
        1 <= current.row <= crossword.grid.height
        and 1 <= current.column <= crossword.grid.width
        and isinstance(
            crossword.grid.cells[current.row - 1][current.column - 1],
            LetterCellRole,
        )
        and (length == 0 or current not in following_starts)
    ):
        length += 1
        current = _shift_coordinate(current, direction, 1)
    return length


def _add_crossword_slot_start(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
    direction: WordDirection,
) -> CrosswordDocument:
    starting = next(
        (
            slot
            for slot in crossword.slots
            if slot.direction == direction and slot.start == coordinate
        ),
        None,
    )
    if starting is not None:
        if starting.legend_position is None:
            return crossword
        raise GuiInputError(
            "Pole už začíná heslo s vepsanou legendou."
        )

    covering = next(
        (
            slot
            for slot in crossword.slots
            if slot.direction == direction
            and coordinate in slot_coordinates(slot)
        ),
        None,
    )
    identifiers = {slot.identifier for slot in crossword.slots}
    if covering is not None:
        if covering.in_help:
            raise GuiInputError(
                "Začátek nelze přidat do hesla uvedeného v pomůcce."
            )
        offset = slot_coordinates(covering).index(coordinate)
        assert offset > 0
        following = WordSlot(
            identifier=_next_slot_identifier(identifiers, direction),
            start=coordinate,
            direction=direction,
            length=covering.length - offset,
        )
        slots: list[WordSlot] = []
        for slot in crossword.slots:
            if slot.identifier == covering.identifier:
                slots.extend(
                    (
                        _blank_changed_slot(covering, length=offset),
                        following,
                    )
                )
            else:
                slots.append(slot)
        return _crossword_with_slots(
            crossword,
            tuple(slots),
            {covering.identifier},
        )

    slot = WordSlot(
        identifier=_next_slot_identifier(identifiers, direction),
        start=coordinate,
        direction=direction,
        length=_new_external_slot_length(crossword, coordinate, direction),
    )
    slots = list(crossword.slots)
    slot_key = _slot_order_key(slot)
    insertion = next(
        (
            index
            for index, existing in enumerate(slots)
            if slot_key < _slot_order_key(existing)
        ),
        len(slots),
    )
    slots.insert(insertion, slot)
    return _crossword_with_slots(crossword, tuple(slots), set())


def _remove_crossword_slot_start(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
    direction: WordDirection,
) -> CrosswordDocument:
    removed = next(
        (
            slot
            for slot in crossword.slots
            if slot.direction == direction
            and slot.start == coordinate
            and slot.legend_position is None
        ),
        None,
    )
    if removed is None:
        return crossword
    before_coordinate = _shift_coordinate(coordinate, direction, -1)
    previous = next(
        (
            slot
            for slot in crossword.slots
            if slot.direction == direction
            and slot_coordinates(slot)[-1] == before_coordinate
        ),
        None,
    )
    changed_slots = tuple(
        slot for slot in (previous, removed) if slot is not None
    )
    if any(slot.in_help for slot in changed_slots):
        raise GuiInputError(
            "Začátek nelze odebrat z hesla uvedeného v pomůcce."
        )

    affected_slots = {slot.identifier for slot in changed_slots}
    slots: list[WordSlot] = []
    for slot in crossword.slots:
        if slot.identifier == removed.identifier:
            continue
        if previous is not None and slot.identifier == previous.identifier:
            slots.append(
                _blank_changed_slot(
                    previous,
                    length=previous.length + removed.length,
                )
            )
        else:
            slots.append(slot)
    return _crossword_with_slots(
        crossword,
        tuple(slots),
        affected_slots,
    )


def set_crossword_cell_slot_start(
    crossword: CrosswordDocument,
    coordinate: Coordinate,
    direction: WordDirection,
    enabled: bool,
) -> CrosswordDocument:
    """Přidá nebo odebere virtuální začátek nelegendovaného slotu."""

    if direction not in {"horizontal", "vertical"}:
        raise GuiInputError(f"Nepodporovaný směr hesla {direction!r}.")
    if not (
        1 <= coordinate.row <= crossword.grid.height
        and 1 <= coordinate.column <= crossword.grid.width
        and isinstance(
            crossword.grid.cells[coordinate.row - 1][coordinate.column - 1],
            LetterCellRole,
        )
    ):
        raise GuiInputError("Heslo lze založit pouze na písmenném poli.")

    changed = (
        _add_crossword_slot_start(crossword, coordinate, direction)
        if enabled
        else _remove_crossword_slot_start(crossword, coordinate, direction)
    )
    try:
        dump_crossword_document(changed, StringIO())
    except ModelError as error:
        raise GuiInputError(
            "Začátek hesla nelze změnit, aniž by vzniklo neplatné "
            f"rozvržení: {error}"
        ) from error
    return changed


def set_crossword_cells_slot_start(
    crossword: CrosswordDocument,
    coordinates: Sequence[Coordinate],
    direction: WordDirection,
    enabled: bool,
) -> CrosswordDocument:
    """Atomicky přepne virtuální začátek u všech vybraných buněk."""

    ordered_coordinates = tuple(
        sorted(set(coordinates), key=lambda item: (item.row, item.column))
    )
    changed = crossword
    for coordinate in ordered_coordinates:
        try:
            changed = set_crossword_cell_slot_start(
                changed,
                coordinate,
                direction,
                enabled,
            )
        except GuiInputError as error:
            if len(ordered_coordinates) == 1:
                raise
            raise GuiInputError(
                f"Pole v řádku {coordinate.row}, sloupci "
                f"{coordinate.column}: {error}"
            ) from error
    return changed


def _crossword_change_discards_content(
    before: CrosswordDocument,
    after: CrosswordDocument,
) -> bool:
    after_slots = {slot.identifier: slot for slot in after.slots}
    for slot in before.slots:
        if slot.answer is None and slot.clue is None and not slot.in_help:
            continue
        changed = after_slots.get(slot.identifier)
        if changed is None or (
            changed.answer,
            changed.clue,
            changed.in_help,
        ) != (slot.answer, slot.clue, slot.in_help):
            return True
    return any(secret not in after.secrets for secret in before.secrets)


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
        raise _CrossingConflictError(
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


def _answer_conflicts_with_crossing(
    crossword: CrosswordDocument,
    identifier: str,
    answer: str,
) -> bool:
    normalized_answer = answer.strip().upper()
    if not normalized_answer:
        return False
    try:
        letters = split_answer_letters(normalized_answer)
    except ValueError:
        return False

    pattern = crossword_slot_pattern(crossword, identifier)
    for index, (letter, expected) in enumerate(zip(letters, pattern)):
        if expected is None or letter == expected:
            continue
        if letter == "C" and expected == "CH" and index == len(letters) - 1:
            continue
        return True
    return False


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
    _ROLE_SELECTED_FILL = "#c4b5fd"
    _SECRET_FILL = "#d9d9d9"
    _LEGEND_FILL = "#fef3c7"
    _EMPTY_FILL = "#e2e8f0"
    _HELP_FILL = "#dcfce7"
    _LETTER_COLOR = "#101828"
    _MUTED_COLOR = "#667085"
    _RESIZE_COLOR = "#2563eb"

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
        self._role_selected_coordinates: frozenset[Coordinate] = frozenset()
        self._role_selection_anchor: Coordinate | None = None
        self._role_selection_base: frozenset[Coordinate] = frozenset()
        self._slot_starts: frozenset[
            tuple[Coordinate, WordDirection]
        ] = frozenset()
        self._external_slot_starts: frozenset[
            tuple[Coordinate, WordDirection]
        ] = frozenset()
        self._empty_message = "Vytvořte rozvržení mřížky."
        self._grid_geometry: tuple[float, float, float] | None = None
        self._cell_click_handler: Callable[[Coordinate], None] | None = None
        self._grid_resize_handler: Callable[[int, int], None] | None = None
        self._cell_role_handler: (
            Callable[[tuple[Coordinate, ...], EditableCellRole], None] | None
        ) = None
        self._cell_slot_handler: (
            Callable[
                [tuple[Coordinate, ...], WordDirection, bool],
                None,
            ]
            | None
        ) = None
        self._context_menu_coordinates: tuple[Coordinate, ...] = ()
        self._cell_role_variable = f"krizovkar_cell_role_{id(self)}"
        self._cell_slot_variables = {
            direction: f"krizovkar_cell_slot_{direction}_{id(self)}"
            for direction in _CELL_SLOT_LABELS
        }
        self._cell_role_menu = self._build_cell_role_menu()
        self._minimum_dimension = 1
        self._maximum_dimension = _MAX_CROSSWORD_DIMENSION
        self._resize_drag: _GridResizeDrag | None = None
        self._resize_target: tuple[int, int] | None = None
        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._pointer_pressed)
        self.bind(
            _multiple_cell_selection_sequence(),
            self._toggle_cell_role_selection,
        )
        self.bind("<Shift-Button-1>", self._select_cell_role_range)
        self.bind("<B1-Motion>", self._resize_dragged)
        self.bind("<Shift-B1-Motion>", self._select_cell_role_range)
        self.bind("<ButtonRelease-1>", self._resize_released)
        self.bind("<Motion>", self._pointer_moved)
        self.bind("<Leave>", self._pointer_left)
        self.bind("<<ContextMenu>>", self._show_cell_role_menu)

    def _build_cell_role_menu(self) -> tk.Menu:
        menu = tk.Menu(self, tearoff=False)
        menu.add_radiobutton(
            label="Písmeno",
            value="letter",
            variable=self._cell_role_variable,
            command=lambda: self._choose_cell_role("letter"),
        )
        menu.add_radiobutton(
            label="Tajenka",
            value="secret",
            variable=self._cell_role_variable,
            command=lambda: self._choose_cell_role("secret"),
        )
        menu.add_radiobutton(
            label="Legenda",
            value="legend",
            variable=self._cell_role_variable,
            command=lambda: self._choose_cell_role("legend"),
        )
        menu.add_radiobutton(
            label="Prázdné",
            value="empty",
            variable=self._cell_role_variable,
            command=lambda: self._choose_cell_role("empty"),
        )
        menu.add_separator()
        for direction, label in _CELL_SLOT_LABELS.items():
            menu.add_checkbutton(
                label=label,
                variable=self._cell_slot_variables[direction],
                onvalue=1,
                offvalue=0,
                command=lambda selected=direction: self._choose_cell_slot(
                    selected
                ),
            )
        return menu

    def set_cell_click_handler(
        self,
        handler: Callable[[Coordinate], None],
    ) -> None:
        self._cell_click_handler = handler

    def set_cell_role_handler(
        self,
        handler: Callable[[tuple[Coordinate, ...], EditableCellRole], None],
    ) -> None:
        self._cell_role_handler = handler

    def set_cell_slot_handler(
        self,
        handler: Callable[
            [tuple[Coordinate, ...], WordDirection, bool],
            None,
        ],
    ) -> None:
        self._cell_slot_handler = handler

    def set_grid_resize_handler(
        self,
        handler: Callable[[int, int], None],
        *,
        minimum_dimension: int,
        maximum_dimension: int,
    ) -> None:
        """Zapne změnu rozměru tažením okrajů vykreslené mřížky."""

        self._grid_resize_handler = handler
        self._minimum_dimension = minimum_dimension
        self._maximum_dimension = maximum_dimension
        self._redraw()

    def show_crossword(
        self,
        crossword: CrosswordGrid,
        *,
        selected_coordinates: tuple[Coordinate, ...] = (),
        slot_starts: tuple[tuple[Coordinate, WordDirection], ...] = (),
        external_slot_starts: tuple[
            tuple[Coordinate, WordDirection], ...
        ] = (),
        show_letters: bool = True,
    ) -> None:
        """Zobrazí role buněk, čísla, výběr a volitelně písmena."""

        self._crossword = crossword
        self._selected_coordinates = frozenset(selected_coordinates)
        self._slot_starts = frozenset(slot_starts)
        self._external_slot_starts = frozenset(external_slot_starts)
        self._role_selected_coordinates = frozenset(
            coordinate
            for coordinate in self._role_selected_coordinates
            if self._editable_cell_role_at(coordinate) is not None
        )
        self._role_selection_base = frozenset(
            coordinate
            for coordinate in self._role_selection_base
            if coordinate in self._role_selected_coordinates
        )
        if (
            self._role_selection_anchor is not None
            and self._editable_cell_role_at(self._role_selection_anchor) is None
        ):
            self._role_selection_anchor = None
        self._show_letters = show_letters
        self._redraw()

    def clear_preview(self, message: str) -> None:
        self._crossword = None
        self._selected_coordinates = frozenset()
        self._role_selected_coordinates = frozenset()
        self._role_selection_anchor = None
        self._role_selection_base = frozenset()
        self._slot_starts = frozenset()
        self._external_slot_starts = frozenset()
        self._context_menu_coordinates = ()
        self._empty_message = message
        self._grid_geometry = None
        self._resize_drag = None
        self._resize_target = None
        self.configure(cursor="")
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
                numbers: tuple[int, ...] = ()
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
                    if isinstance(cell, SecretCell):
                        fill = self._SECRET_FILL
                    letter = cell.value if self._show_letters else None
                    numbers = cell_numbers(cell)
                    bars = cell.bars
                    if coordinate in self._selected_coordinates:
                        fill = self._SELECTED_FILL
                if coordinate in self._role_selected_coordinates:
                    fill = self._ROLE_SELECTED_FILL

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
                if numbers and cell_size >= 18:
                    self._draw_cell_numbers(
                        numbers,
                        x1=x1,
                        y1=y1,
                        x2=x2,
                        cell_size=cell_size,
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

        if self._grid_resize_handler is not None:
            self._draw_resize_handles(
                left,
                top,
                left + grid_width,
                top + grid_height,
            )

    def _draw_cell_numbers(
        self,
        numbers: tuple[int, ...],
        *,
        x1: float,
        y1: float,
        x2: float,
        cell_size: float,
    ) -> None:
        font = (
            "TkDefaultFont",
            max(5, int(cell_size * (0.17 if len(numbers) > 1 else 0.2))),
        )
        if len(numbers) == 1:
            labels = ((str(numbers[0]), x1 + 2, "nw"),)
        else:
            labels = (
                (f"{numbers[0]}→", x1 + 2, "nw"),
                (f"{numbers[1]}↓", x2 - 2, "ne"),
            )
        for label, x, anchor in labels:
            self.create_text(
                x,
                y1 + 1,
                text=label,
                anchor=anchor,
                fill=self._LETTER_COLOR,
                font=font,
            )

    def _draw_resize_handles(
        self,
        left: float,
        top: float,
        right: float,
        bottom: float,
    ) -> None:
        radius = _GRID_RESIZE_HANDLE_RADIUS
        horizontal_center = (left + right) / 2
        vertical_center = (top + bottom) / 2
        positions = (
            (left, top),
            (horizontal_center, top),
            (right, top),
            (left, vertical_center),
            (right, vertical_center),
            (left, bottom),
            (horizontal_center, bottom),
            (right, bottom),
        )
        for x, y in positions:
            self.create_rectangle(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill="#ffffff",
                outline=self._RESIZE_COLOR,
                width=1,
            )

    def _resize_edges_at(self, x: float, y: float) -> tuple[int, int]:
        crossword = self._crossword
        geometry = self._grid_geometry
        if (
            crossword is None
            or geometry is None
            or self._grid_resize_handler is None
        ):
            return (0, 0)

        left, top, cell_size = geometry
        right = left + crossword.grid.width * cell_size
        bottom = top + crossword.grid.height * cell_size
        radius = min(
            _GRID_RESIZE_HIT_RADIUS,
            max(_GRID_RESIZE_HANDLE_RADIUS, cell_size / 3),
        )
        within_rows = top - radius <= y <= bottom + radius
        within_columns = left - radius <= x <= right + radius

        horizontal_edge = 0
        if within_rows and abs(x - left) <= radius:
            horizontal_edge = -1
        elif within_rows and abs(x - right) <= radius:
            horizontal_edge = 1

        vertical_edge = 0
        if within_columns and abs(y - top) <= radius:
            vertical_edge = -1
        elif within_columns and abs(y - bottom) <= radius:
            vertical_edge = 1
        return (horizontal_edge, vertical_edge)

    def _set_resize_cursor(self, edges: tuple[int, int]) -> None:
        horizontal_edge, vertical_edge = edges
        if horizontal_edge and vertical_edge:
            cursor = "sizing"
        elif horizontal_edge:
            cursor = "sb_h_double_arrow"
        elif vertical_edge:
            cursor = "sb_v_double_arrow"
        else:
            cursor = ""
        try:
            self.configure(cursor=cursor)
        except tk.TclError:
            self.configure(cursor="")

    def _pointer_moved(self, event: tk.Event[tk.Misc]) -> None:
        if self._resize_drag is None:
            self._set_resize_cursor(self._resize_edges_at(event.x, event.y))

    def _pointer_left(self, _event: tk.Event[tk.Misc]) -> None:
        if self._resize_drag is None:
            self._set_resize_cursor((0, 0))

    def _pointer_pressed(self, event: tk.Event[tk.Misc]) -> str | None:
        edges = self._resize_edges_at(event.x, event.y)
        if edges == (0, 0):
            self._clear_cell_role_selection()
            self._cell_clicked(event)
            return None

        assert self._crossword is not None
        assert self._grid_geometry is not None
        _, _, cell_size = self._grid_geometry
        horizontal_edge, vertical_edge = edges
        self._resize_drag = _GridResizeDrag(
            horizontal_edge=horizontal_edge,
            vertical_edge=vertical_edge,
            start_x=event.x,
            start_y=event.y,
            start_width=self._crossword.grid.width,
            start_height=self._crossword.grid.height,
            cell_size=cell_size,
        )
        self._resize_target = (
            self._crossword.grid.width,
            self._crossword.grid.height,
        )
        self._set_resize_cursor(edges)
        self._draw_resize_feedback()
        return "break"

    @staticmethod
    def _rounded_grid_steps(value: float) -> int:
        if value >= 0:
            return int(value + 0.5)
        return int(value - 0.5)

    def _resize_target_at(self, x: float, y: float) -> tuple[int, int]:
        drag = self._resize_drag
        assert drag is not None
        width_delta = self._rounded_grid_steps(
            drag.horizontal_edge * (x - drag.start_x) / drag.cell_size
        )
        height_delta = self._rounded_grid_steps(
            drag.vertical_edge * (y - drag.start_y) / drag.cell_size
        )
        width = (
            self._bounded_drag_dimension(drag.start_width, width_delta)
            if drag.horizontal_edge
            else drag.start_width
        )
        height = (
            self._bounded_drag_dimension(drag.start_height, height_delta)
            if drag.vertical_edge
            else drag.start_height
        )
        return (width, height)

    def _bounded_drag_dimension(self, current: int, delta: int) -> int:
        if delta == 0:
            return current
        if current < self._minimum_dimension and delta < 0:
            return current
        if current > self._maximum_dimension and delta > 0:
            return current
        return min(
            self._maximum_dimension,
            max(self._minimum_dimension, current + delta),
        )

    def _resize_dragged(self, event: tk.Event[tk.Misc]) -> str | None:
        if self._resize_drag is None:
            return None
        self._resize_target = self._resize_target_at(event.x, event.y)
        self._draw_resize_feedback()
        return "break"

    def _draw_resize_feedback(self) -> None:
        drag = self._resize_drag
        target = self._resize_target
        geometry = self._grid_geometry
        if drag is None or target is None or geometry is None:
            return
        self.delete(_GRID_RESIZE_FEEDBACK_TAG)

        left, top, cell_size = geometry
        current_right = left + drag.start_width * cell_size
        current_bottom = top + drag.start_height * cell_size
        target_width, target_height = target
        if drag.horizontal_edge < 0:
            target_left = current_right - target_width * cell_size
            target_right = current_right
        else:
            target_left = left
            target_right = left + target_width * cell_size
        if drag.vertical_edge < 0:
            target_top = current_bottom - target_height * cell_size
            target_bottom = current_bottom
        else:
            target_top = top
            target_bottom = top + target_height * cell_size

        self.create_rectangle(
            target_left,
            target_top,
            target_right,
            target_bottom,
            outline=self._RESIZE_COLOR,
            width=3,
            dash=(5, 3),
            tags=_GRID_RESIZE_FEEDBACK_TAG,
        )
        label_x = min(
            max((target_left + target_right) / 2, 42),
            max(self.winfo_width() - 42, 42),
        )
        label_y = min(
            max((target_top + target_bottom) / 2, 18),
            max(self.winfo_height() - 18, 18),
        )
        label = self.create_text(
            label_x,
            label_y,
            text=f"{target_width} × {target_height}",
            fill=self._RESIZE_COLOR,
            font=("TkDefaultFont", 11, "bold"),
            tags=_GRID_RESIZE_FEEDBACK_TAG,
        )
        bounds = self.bbox(label)
        if bounds is not None:
            background = self.create_rectangle(
                bounds[0] - 6,
                bounds[1] - 3,
                bounds[2] + 6,
                bounds[3] + 3,
                fill="#ffffff",
                outline=self._RESIZE_COLOR,
                width=1,
                tags=_GRID_RESIZE_FEEDBACK_TAG,
            )
            self.tag_lower(background, label)

    def _resize_released(self, event: tk.Event[tk.Misc]) -> str | None:
        drag = self._resize_drag
        if drag is None:
            return None
        target = self._resize_target_at(event.x, event.y)
        changed = target != (drag.start_width, drag.start_height)
        handler = self._grid_resize_handler
        self._resize_drag = None
        self._resize_target = None
        self.delete(_GRID_RESIZE_FEEDBACK_TAG)
        if changed and handler is not None:
            handler(*target)
        self._set_resize_cursor(self._resize_edges_at(event.x, event.y))
        return "break"

    def _cell_clicked(self, event: tk.Event[tk.Misc]) -> None:
        coordinate = self._cell_coordinate_at(event.x, event.y)
        if coordinate is None:
            return
        if self._editable_cell_role_at(coordinate) is not None:
            self._role_selection_anchor = coordinate
            self._role_selection_base = frozenset()
        handler = self._cell_click_handler
        if handler is not None:
            handler(coordinate)

    def _toggle_cell_role_selection(
        self,
        event: tk.Event[tk.Misc],
    ) -> str:
        if self._resize_edges_at(event.x, event.y) != (0, 0):
            return "break"
        coordinate = self._cell_coordinate_at(event.x, event.y)
        if (
            coordinate is None
            or self._editable_cell_role_at(coordinate) is None
        ):
            return "break"

        selected = set(self._role_selected_coordinates)
        if coordinate in selected:
            selected.remove(coordinate)
        else:
            selected.add(coordinate)
        self._role_selected_coordinates = frozenset(selected)
        self._role_selection_anchor = coordinate
        self._role_selection_base = frozenset(selected - {coordinate})
        self._context_menu_coordinates = ()
        self._redraw()
        return "break"

    def _select_cell_role_range(
        self,
        event: tk.Event[tk.Misc],
    ) -> str:
        if self._resize_edges_at(event.x, event.y) != (0, 0):
            return "break"
        coordinate = self._cell_coordinate_at(event.x, event.y)
        if (
            coordinate is None
            or self._editable_cell_role_at(coordinate) is None
        ):
            return "break"

        anchor = self._role_selection_anchor
        if anchor is None or self._editable_cell_role_at(anchor) is None:
            anchor = coordinate
            self._role_selection_anchor = coordinate
            self._role_selection_base = frozenset()
        selected = set(self._role_selection_base)
        for row in range(
            min(anchor.row, coordinate.row),
            max(anchor.row, coordinate.row) + 1,
        ):
            for column in range(
                min(anchor.column, coordinate.column),
                max(anchor.column, coordinate.column) + 1,
            ):
                ranged_coordinate = Coordinate(row=row, column=column)
                if self._editable_cell_role_at(ranged_coordinate) is not None:
                    selected.add(ranged_coordinate)
        self._role_selected_coordinates = frozenset(selected)
        self._context_menu_coordinates = ()
        self._redraw()
        return "break"

    def _clear_cell_role_selection(self) -> None:
        if (
            not self._role_selected_coordinates
            and self._role_selection_anchor is None
            and not self._role_selection_base
        ):
            return
        needs_redraw = bool(self._role_selected_coordinates)
        self._role_selected_coordinates = frozenset()
        self._role_selection_anchor = None
        self._role_selection_base = frozenset()
        self._context_menu_coordinates = ()
        if needs_redraw:
            self._redraw()

    def _cell_coordinate_at(self, x: float, y: float) -> Coordinate | None:
        if self._crossword is None or self._grid_geometry is None:
            return None
        left, top, cell_size = self._grid_geometry
        column = int((x - left) // cell_size) + 1
        row = int((y - top) // cell_size) + 1
        if (
            x < left
            or y < top
            or row < 1
            or column < 1
            or row > self._crossword.grid.height
            or column > self._crossword.grid.width
        ):
            return None
        return Coordinate(row=row, column=column)

    def _editable_cell_role_at(
        self,
        coordinate: Coordinate,
    ) -> EditableCellRole | None:
        crossword = self._crossword
        if (
            crossword is None
            or coordinate.row < 1
            or coordinate.column < 1
            or coordinate.row > crossword.grid.height
            or coordinate.column > crossword.grid.width
        ):
            return None
        cell = crossword.grid.cells[coordinate.row - 1][coordinate.column - 1]
        if isinstance(cell, SecretCell):
            return "secret"
        if isinstance(cell, LetterCell):
            return "letter"
        if isinstance(cell, LegendCell):
            return "legend"
        if isinstance(cell, EmptyCell):
            return "empty"
        return None

    def _show_cell_role_menu(self, event: tk.Event[tk.Misc]) -> str | None:
        coordinate = self._cell_coordinate_at(event.x, event.y)
        if coordinate is None or self._editable_cell_role_at(coordinate) is None:
            return None

        if coordinate not in self._role_selected_coordinates:
            self._role_selected_coordinates = frozenset({coordinate})
            self._role_selection_anchor = coordinate
            self._role_selection_base = frozenset()
            self._redraw()
        coordinates = tuple(
            sorted(
                self._role_selected_coordinates,
                key=lambda item: (item.row, item.column),
            )
        )
        roles = {
            role
            for selected in coordinates
            if (role := self._editable_cell_role_at(selected)) is not None
        }
        current_role = roles.pop() if len(roles) == 1 else ""
        self._context_menu_coordinates = coordinates
        self._cell_role_menu.setvar(self._cell_role_variable, current_role)
        all_letters = all(
            self._editable_cell_role_at(selected) in {"letter", "secret"}
            for selected in coordinates
        )
        for direction, label in _CELL_SLOT_LABELS.items():
            starts = {(selected, direction) for selected in coordinates}
            all_external = starts <= self._external_slot_starts
            has_inline = bool(
                (starts & self._slot_starts) - self._external_slot_starts
            )
            self._cell_role_menu.setvar(
                self._cell_slot_variables[direction],
                int(all_external),
            )
            self._cell_role_menu.entryconfigure(
                label,
                state="normal" if all_letters and not has_inline else "disabled",
            )
        try:
            self._cell_role_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._cell_role_menu.grab_release()
        return "break"

    def _choose_cell_role(self, role: EditableCellRole) -> None:
        coordinates = self._context_menu_coordinates
        handler = self._cell_role_handler
        if coordinates and handler is not None:
            handler(coordinates, role)

    def _choose_cell_slot(self, direction: WordDirection) -> None:
        coordinates = self._context_menu_coordinates
        handler = self._cell_slot_handler
        value = self._cell_role_menu.getvar(
            self._cell_slot_variables[direction]
        )
        enabled = value in {True, "1", "true"}
        if coordinates and handler is not None:
            handler(coordinates, direction, enabled)


def load_editable_document(
    source: str | Path,
) -> CrosswordDocument:
    """Načte prázdnou, rozpracovanou nebo hotovou křížovku."""

    return load_crossword_document(source)


def _grid_from_editable_document(
    document: CrosswordDocument,
) -> CrosswordGrid:
    return create_grid_from_crossword(document)


class _ReadOnlyText(tk.Text):
    """Text, který dovolí výběr a posun, ale odmítne změny obsahu."""

    _MUTATING_COMMANDS = frozenset({"delete", "insert", "replace"})

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        super().__init__(master, **kwargs)
        self._original_widget_command = f"{self._w}_readonly_original"
        self.tk.call("rename", self._w, self._original_widget_command)
        self.tk.createcommand(self._w, self._dispatch_widget_command)

    def _dispatch_widget_command(self, *arguments: object) -> object:
        if arguments and arguments[0] in self._MUTATING_COMMANDS:
            return ""
        return self.tk.call(self._original_widget_command, *arguments)

    def replace_content(self, content: str) -> None:
        """Nahradí obsah interně, aniž by zpřístupnil jeho úpravu."""

        self.tk.call(
            self._original_widget_command,
            "delete",
            "1.0",
            tk.END,
        )
        self.tk.call(
            self._original_widget_command,
            "insert",
            "1.0",
            content,
        )

    def destroy(self) -> None:
        self.tk.deletecommand(self._w)
        self.tk.call("rename", self._original_widget_command, self._w)
        super().destroy()


class CrosswordSourceWindow(ttk.Frame):
    """Samostatné okno s YAML podobou jednoho konkrétního dokumentu."""

    def __init__(
        self,
        root: tk.Toplevel,
        document_window: CrosswordDocumentWindow,
    ) -> None:
        super().__init__(root, padding=8)
        self.root = root
        self._document_window = document_window
        self._configure_window()
        self._build_content()

    def _configure_window(self) -> None:
        self.root.title("Zdroj YAML")
        self.root.geometry("560x680")
        self.root.minsize(360, 240)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def _build_content(self) -> None:
        self.source_text = _ReadOnlyText(
            self,
            wrap="none",
            font="TkFixedFont",
        )
        vertical_scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.source_text.yview,
        )
        horizontal_scrollbar = ttk.Scrollbar(
            self,
            orient="horizontal",
            command=self.source_text.xview,
        )
        self.source_text.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        self.source_text.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")

    def show(self, *, reveal: bool) -> None:
        """Aktualizuje pevně přiřazený dokument a případně okno odkryje."""

        vertical_position = self.source_text.yview()
        horizontal_position = self.source_text.xview()
        output = StringIO()
        window = self._document_window
        dump_crossword_document(window._document(), output)

        label = _document_window_label(window._path, window._dirty)
        self.root.title(f"Zdroj YAML — {label}")
        self.source_text.replace_content(output.getvalue())
        if vertical_position:
            self.source_text.yview_moveto(vertical_position[0])
        if horizontal_position:
            self.source_text.xview_moveto(horizontal_position[0])
        if reveal:
            self.root.deiconify()
            self.root.lift()
            self.source_text.focus_set()


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
        self._active_window: CrosswordDocumentWindow | None = None
        self._source_windows: dict[
            CrosswordDocumentWindow,
            CrosswordSourceWindow,
        ] = {}
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
        self.view_menu = _create_view_menu(menu, None)
        menu.add_cascade(label="Zobrazení", menu=self.view_menu)
        self.window_menu = _create_window_menu(
            menu,
            self._refresh_window_menu,
        )
        menu.add_cascade(label="Okno", menu=self.window_menu)
        self.help_menu = _create_help_menu(menu)
        menu.add_cascade(label="Nápověda", menu=self.help_menu)
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
        active = current if current in windows else self._active_window
        if active not in windows:
            active = None
        selected = str(id(active)) if active is not None else ""
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

    def show_source_window(
        self,
        window: CrosswordDocumentWindow | None = None,
    ) -> CrosswordSourceWindow | None:
        target = window if window in self._windows else self._active_window
        if target not in self._windows:
            return None
        source_window = self._source_windows.get(target)
        if source_window is None:
            source_root = tk.Toplevel(self.root)
            source_window = CrosswordSourceWindow(source_root, target)
            self._source_windows[target] = source_window
            source_root.protocol(
                "WM_DELETE_WINDOW",
                lambda target=target: self._close_source_window(target),
            )
        source_window.show(reveal=True)
        return source_window

    def _close_source_window(self, window: CrosswordDocumentWindow) -> None:
        source_window = self._source_windows.pop(window, None)
        if source_window is not None:
            source_window.root.destroy()

    def document_window_activated(
        self,
        window: CrosswordDocumentWindow,
    ) -> None:
        if window not in self._windows:
            return
        if window is self._active_window:
            return
        self._active_window = window

    def document_window_changed(self, window: CrosswordDocumentWindow) -> None:
        source_window = self._source_windows.get(window)
        if source_window is not None:
            source_window.show(reveal=False)

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
        self.document_window_activated(window)
        return window

    def activate_window(self, window: CrosswordDocumentWindow) -> None:
        if window not in self._windows:
            return
        self.document_window_activated(window)
        window.root.deiconify()
        window.root.lift()
        window.root.focus_force()

    def close_window(self, window: CrosswordDocumentWindow) -> None:
        if window in self._windows:
            self._windows.remove(window)
        self._close_source_window(window)
        if window is self._active_window or not self._windows:
            self._active_window = self._windows[-1] if self._windows else None
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
        super().__init__(root, padding=(12, 10))
        self.root = root
        self.application = application
        self._path = path
        self._dirty = dirty
        self._crossword = document
        self._grid: CrosswordGrid | None = None
        self._template_layout = _template_generation_layout(document)
        self._selected_slot_identifier: str | None = None
        self._slot_edit_identifier: str | None = None
        self._slot_answer_editor: ttk.Entry | None = None
        self._slot_clue_editor: ttk.Entry | None = None
        self._slot_list_placement = _SLOT_LIST_PLACEMENT_MAIN
        self._slot_list_window: tk.Toplevel | None = None
        self._slot_list_placement_variable = (
            f"krizovkar_slot_list_placement_{id(self)}"
        )
        self._page_format = DEFAULT_PAGE_FORMAT

        self._configure_window()
        self._build_menu()
        self._build_content()
        self._rebuild_slot_tree()
        self._refresh_crossword_view()
        self._update_title()

    def _configure_window(self) -> None:
        self.root.geometry("600x850")
        self.root.minsize(600, 700)
        self.root.option_add("*tearOff", False)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.root.bind("<FocusIn>", self._document_focus_in, add="+")

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
        self.view_menu = _create_view_menu(
            menu,
            lambda: self.application.show_source_window(self),
        )
        self.view_menu.add_separator()
        self.slot_list_placement_menu = _create_slot_list_placement_menu(
            self.view_menu,
            variable=self._slot_list_placement_variable,
            selected=self._slot_list_placement,
            command=self._set_slot_list_placement,
        )
        self.view_menu.add_cascade(
            label="Místa pro hesla",
            menu=self.slot_list_placement_menu,
        )
        menu.add_cascade(label="Zobrazení", menu=self.view_menu)
        self.window_menu = _create_window_menu(
            menu,
            self._refresh_window_menu,
        )
        menu.add_cascade(label="Okno", menu=self.window_menu)
        self.help_menu = _create_help_menu(menu)
        menu.add_cascade(label="Nápověda", menu=self.help_menu)
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

    def _document_focus_in(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> None:
        self.application.document_window_activated(self)

    def _build_content(self) -> None:
        document_frame = ttk.Frame(self)
        document_frame.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        self.crossword_tab = document_frame
        self._build_crossword_document()

    def _build_crossword_document(self) -> None:
        tab = self.crossword_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        workspace = ttk.Frame(tab)
        workspace.grid(row=0, column=0, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)
        self.crossword_workspace = workspace
        self._build_crossword_preview(workspace)
        self._build_slot_list(workspace)

    def _build_crossword_preview(self, parent: ttk.Frame) -> None:
        preview_frame = ttk.LabelFrame(
            parent,
            text=self._crossword_preview_title(),
            padding=12,
        )
        self.crossword_preview_frame = preview_frame
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
        self.crossword_preview.set_cell_role_handler(
            self._preview_cell_role_changed
        )
        self.crossword_preview.set_cell_slot_handler(
            self._preview_cell_slot_changed
        )
        self.crossword_preview.set_grid_resize_handler(
            self._preview_grid_resized,
            minimum_dimension=_minimum_generated_dimension(
                self._template_layout
            ),
            maximum_dimension=_MAX_CROSSWORD_DIMENSION,
        )

    def _crossword_preview_title(self) -> str:
        crossword = self._crossword
        if crossword is None:
            return "Náhled křížovky"
        return (
            "Náhled křížovky "
            f"({crossword.grid.width} × {crossword.grid.height})"
        )

    def _build_slot_list(
        self,
        parent: tk.Misc,
        *,
        standalone: bool = False,
    ) -> None:
        if standalone:
            slots_frame = ttk.Frame(parent, padding=12)
        else:
            slots_frame = ttk.LabelFrame(
                parent,
                text="Místa pro hesla",
                padding=12,
            )
        self.slots_frame = slots_frame
        slots_frame.grid(
            row=0 if standalone else 1,
            column=0,
            sticky="nsew" if standalone else "ew",
            pady=0 if standalone else (12, 0),
        )
        slots_frame.columnconfigure(0, weight=1)
        slots_frame.rowconfigure(0, weight=1)
        container = ttk.Frame(slots_frame)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        slot_style = ttk.Style(parent)
        slot_style.configure(
            _SLOT_TREE_STYLE,
            rowheight=_SLOT_TREE_ROW_HEIGHT,
        )
        slot_style.map(
            _SLOT_EDITOR_STYLE,
            foreground=[("invalid", _SLOT_EDITOR_ERROR_COLOR)],
        )
        self.slots_tree = ttk.Treeview(
            container,
            columns=("slot", "length", "answer", "clue"),
            show="headings",
            height=7,
            selectmode="browse",
            style=_SLOT_TREE_STYLE,
        )
        self.slots_tree.heading("slot", text="Místo")
        self.slots_tree.heading("length", text="Délka")
        self.slots_tree.heading("answer", text="Heslo")
        self.slots_tree.heading("clue", text="Nápověda")
        self.slots_tree.column(
            "slot",
            width=_SLOT_COMPACT_COLUMN_WIDTH,
            minwidth=_SLOT_COMPACT_COLUMN_WIDTH,
            stretch=False,
            anchor="center",
        )
        self.slots_tree.column(
            "length",
            width=_SLOT_COMPACT_COLUMN_WIDTH,
            minwidth=_SLOT_COMPACT_COLUMN_WIDTH,
            stretch=False,
            anchor="center",
        )
        self.slots_tree.column(
            "answer",
            width=120,
            minwidth=1,
            stretch=False,
        )
        self.slots_tree.column(
            "clue",
            width=240,
            minwidth=1,
            stretch=False,
        )
        self.slots_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.slots_tree.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.slots_tree.configure(yscrollcommand=scrollbar.set)
        self.slots_tree.bind("<Configure>", self._fit_slot_table_columns)
        self.slots_tree.bind("<Motion>", self._slot_table_pointer_moved)
        self.slots_tree.bind("<Button-1>", self._slot_table_button_pressed)
        self.slots_tree.bind("<<TreeviewSelect>>", self._slot_selection_changed)
        self.slots_tree.bind("<Double-Button-1>", self._begin_slot_edit)
        self.slots_tree.bind("<Return>", self._begin_selected_slot_edit)
        self.slots_tree.bind("<Delete>", self._clear_selected_slot_event)
        self.slots_tree.bind("<BackSpace>", self._clear_selected_slot_event)

    def _fit_slot_table_columns(self, event: tk.Event[tk.Misc]) -> None:
        fixed_width = (
            2 * _SLOT_COMPACT_COLUMN_WIDTH + _SLOT_TABLE_HORIZONTAL_INSET
        )
        editable_width = max(2, event.width - fixed_width)
        answer_width = max(1, editable_width // 3)
        clue_width = editable_width - answer_width
        self.slots_tree.column("answer", width=answer_width)
        self.slots_tree.column("clue", width=clue_width)
        self.slots_tree.xview_moveto(0)

    def _slot_table_pointer_moved(
        self,
        event: tk.Event[tk.Misc],
    ) -> str | None:
        if self.slots_tree.identify_region(event.x, event.y) != "separator":
            return None
        self.slots_tree.configure(cursor="")
        return "break"

    def _slot_table_button_pressed(
        self,
        event: tk.Event[tk.Misc],
    ) -> str | None:
        if self.slots_tree.identify_region(event.x, event.y) == "separator":
            return "break"
        return None

    def _set_slot_list_placement(self, placement: str) -> None:
        if placement not in {
            _SLOT_LIST_PLACEMENT_MAIN,
            _SLOT_LIST_PLACEMENT_WINDOW,
        }:
            raise ValueError(f"Neznámé umístění tabulky: {placement}")
        if placement == self._slot_list_placement:
            self._sync_slot_list_placement_menu()
            if self._slot_list_window is not None:
                self._slot_list_window.deiconify()
                self._slot_list_window.lift()
                self._slot_list_window.focus_force()
            return
        if not self._save_inline_slot_edit():
            self._sync_slot_list_placement_menu()
            return

        self.slots_frame.destroy()
        if placement == _SLOT_LIST_PLACEMENT_WINDOW:
            slot_list_window = tk.Toplevel(self.root)
            self._slot_list_window = slot_list_window
            self._slot_list_placement = placement
            slot_list_window.title(self._slot_list_window_title())
            slot_list_window.geometry("780x340")
            slot_list_window.minsize(520, 220)
            slot_list_window.columnconfigure(0, weight=1)
            slot_list_window.rowconfigure(0, weight=1)
            slot_list_window.protocol(
                "WM_DELETE_WINDOW",
                lambda: self._set_slot_list_placement(
                    _SLOT_LIST_PLACEMENT_MAIN
                ),
            )
            self._build_slot_list(slot_list_window, standalone=True)
            slot_list_window.lift()
            slot_list_window.focus_force()
        else:
            slot_list_window = self._slot_list_window
            self._slot_list_window = None
            self._slot_list_placement = placement
            if slot_list_window is not None:
                slot_list_window.destroy()
            self._build_slot_list(self.crossword_workspace)

        self._sync_slot_list_placement_menu()
        self._rebuild_slot_tree()

    def _sync_slot_list_placement_menu(self) -> None:
        self.slot_list_placement_menu.setvar(
            self._slot_list_placement_variable,
            self._slot_list_placement,
        )

    def _slot_list_window_title(self) -> str:
        label = _document_window_label(self._path, self._dirty)
        return f"Místa pro hesla — {label}"

    def _preview_grid_resized(self, width: int, height: int) -> None:
        if not self._save_inline_slot_edit():
            return
        current = self._crossword
        if current is None:
            return
        settings = CrosswordSettings(width, height)
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
            return
        layout = self._template_layout or "swedish"
        try:
            template = create_blank_template(settings, layout)
        except GuiInputError:
            return

        self._crossword = template
        self._template_layout = layout
        self._selected_slot_identifier = None
        self._set_dirty(True)
        self._rebuild_slot_tree()
        self._refresh_crossword_view()

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

    def _slot_label(self, selected: WordSlot) -> str:
        assert self._crossword is not None
        if selected.legend_position is None:
            numbers = crossword_external_slot_numbers(self._crossword)
            number = numbers.get(selected.identifier)
            if number is not None:
                return f"{_DIRECTION_LABELS[selected.direction]} {number}"
        number = 0
        for slot in self._crossword.slots:
            if slot.direction == selected.direction:
                number += 1
            if slot.identifier == selected.identifier:
                return f"{_DIRECTION_LABELS[slot.direction]} {number}"
        return selected.identifier

    def _slot_shadow_answer(self, slot: WordSlot) -> str | None:
        crossword = self._crossword
        if crossword is None or slot.answer is not None:
            return None
        pattern = crossword_slot_pattern(crossword, slot.identifier)
        if not any(pattern):
            return None
        return "".join(letter or "•" for letter in pattern)

    def _rebuild_slot_tree(self) -> None:
        self._cancel_inline_slot_edit()
        selected_identifier = self._selected_slot_identifier
        for item in self.slots_tree.get_children():
            self.slots_tree.delete(item)
        self.slots_tree.tag_configure(
            _SHADOW_ANSWER_TAG,
            foreground="gray50",
        )
        crossword = self._crossword
        if crossword is None:
            self._slot_selection_changed()
            return
        for slot in crossword.slots:
            shadow_answer = self._slot_shadow_answer(slot)
            self.slots_tree.insert(
                "",
                "end",
                iid=slot.identifier,
                values=(
                    self._slot_label(slot),
                    slot.length,
                    slot.answer or shadow_answer or "—",
                    slot.clue or "—",
                ),
            )
            if shadow_answer is not None:
                # Tkinter zatím buněčné tagy Treeviewu z Tk 9 neobaluje.
                self.slots_tree.tk.call(
                    self.slots_tree._w,
                    "tag",
                    "cell",
                    "add",
                    _SHADOW_ANSWER_TAG,
                    ((slot.identifier, "answer"),),
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
            self._refresh_crossword_preview()
            return

        self._selected_slot_identifier = selection[0]
        self._refresh_crossword_preview()

    def _begin_slot_edit(self, event: tk.Event[tk.Misc]) -> str | None:
        region = self.slots_tree.identify_region(event.x, event.y)
        if region == "separator":
            return "break"
        if region != "cell":
            return None
        identifier = self.slots_tree.identify_row(event.y)
        column = self.slots_tree.identify_column(event.x)
        if not identifier or column not in {"#3", "#4"}:
            return None
        self._open_inline_slot_edit(identifier, column)
        return "break"

    def _begin_selected_slot_edit(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> str:
        selection = self.slots_tree.selection()
        if selection:
            self._open_inline_slot_edit(selection[0], "#3")
        return "break"

    def _open_inline_slot_edit(self, identifier: str, column: str) -> bool:
        if (
            self._slot_edit_identifier is not None
            and not self._save_inline_slot_edit()
        ):
            return False
        crossword = self._crossword
        if crossword is None:
            return False
        try:
            _, slot = _crossword_slot(crossword, identifier)
        except GuiInputError:
            return False

        self.slots_tree.selection_set(identifier)
        self.slots_tree.focus(identifier)
        self.slots_tree.see(identifier)
        self.slots_tree.update_idletasks()
        answer_box = self.slots_tree.bbox(identifier, "#3")
        clue_box = self.slots_tree.bbox(identifier, "#4")
        if not answer_box or not clue_box:
            return False

        self._selected_slot_identifier = identifier
        self._slot_edit_identifier = identifier
        self._slot_answer_editor = self._create_slot_cell_editor(
            answer_box,
            slot.answer or "",
            check_crossings=True,
        )
        self._slot_clue_editor = self._create_slot_cell_editor(
            clue_box,
            slot.clue or "",
        )
        focused_editor = (
            self._slot_clue_editor if column == "#4" else self._slot_answer_editor
        )
        focused_editor.focus_set()
        focused_editor.selection_range(0, tk.END)
        self._refresh_crossword_preview()
        return True

    def _create_slot_cell_editor(
        self,
        bounding_box: tuple[int, int, int, int],
        value: str,
        *,
        check_crossings: bool = False,
    ) -> ttk.Entry:
        x, y, width, height = bounding_box
        editor = ttk.Entry(
            self.slots_tree,
            style=_SLOT_EDITOR_STYLE,
        )
        editor.insert(0, value)
        editor.place(
            x=x + 1,
            y=y + 1,
            width=max(1, width - 2),
            height=max(1, height - 2),
        )
        editor.bind("<Return>", self._commit_inline_slot_edit)
        editor.bind("<Escape>", self._cancel_inline_slot_edit)
        editor.bind("<FocusOut>", self._inline_slot_editor_focus_out)
        if check_crossings:
            validation_command = editor.register(
                lambda answer: self._update_slot_answer_error(editor, answer)
            )
            editor.configure(
                validate="key",
                validatecommand=(validation_command, "%P"),
            )
        _bind_text_entry_context_menu(editor)
        return editor

    def _update_slot_answer_error(
        self,
        editor: ttk.Entry,
        answer: str,
    ) -> bool:
        crossword = self._crossword
        identifier = self._slot_edit_identifier
        if crossword is None or identifier is None:
            return True
        try:
            conflicts = _answer_conflicts_with_crossing(
                crossword,
                identifier,
                answer,
            )
        except GuiInputError:
            conflicts = False
        editor.state(("invalid",) if conflicts else ("!invalid",))
        return True

    def _inline_slot_editor_focus_out(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> None:
        self.after_idle(self._save_slot_edit_if_focus_left)

    def _save_slot_edit_if_focus_left(self) -> None:
        focused = self.focus_get()
        if focused in (
            self._slot_answer_editor,
            self._slot_clue_editor,
        ):
            return
        self._save_inline_slot_edit()

    def _commit_inline_slot_edit(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> str:
        self._save_inline_slot_edit()
        return "break"

    def _save_inline_slot_edit(self) -> bool:
        crossword = self._crossword
        identifier = self._slot_edit_identifier
        answer_editor = self._slot_answer_editor
        clue_editor = self._slot_clue_editor
        if (
            crossword is None
            or identifier is None
            or answer_editor is None
            or clue_editor is None
        ):
            return True

        answer = answer_editor.get()
        clue = clue_editor.get()
        answer_editor.state(("!invalid",))
        try:
            if not answer.strip() and not clue.strip():
                updated = clear_crossword_slot(crossword, identifier)
            else:
                updated = fill_crossword_slot(
                    crossword,
                    identifier,
                    answer,
                    clue,
                )
        except GuiInputError as error:
            if isinstance(error, _CrossingConflictError):
                answer_editor.state(("invalid",))
            self._show_action_error(
                "Heslo nelze uložit",
                str(error),
            )
            if not answer.strip():
                answer_editor.focus_set()
            elif not clue.strip():
                clue_editor.focus_set()
            else:
                answer_editor.focus_set()
            return False

        changed = updated != crossword
        self._crossword = updated
        self._close_inline_slot_edit()
        if changed:
            self._set_dirty(True)
            self._rebuild_slot_tree()
            self._refresh_crossword_view()
        return True

    def _close_inline_slot_edit(self) -> None:
        editors = (self._slot_answer_editor, self._slot_clue_editor)
        self._slot_edit_identifier = None
        self._slot_answer_editor = None
        self._slot_clue_editor = None
        for editor in editors:
            if editor is not None:
                editor.destroy()

    def _cancel_inline_slot_edit(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> str:
        self._close_inline_slot_edit()
        return "break"

    def _clear_selected_slot_event(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> str:
        if self._save_inline_slot_edit():
            self.clear_selected_slot()
        return "break"

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

    def _preview_cell_role_changed(
        self,
        coordinates: tuple[Coordinate, ...],
        role: EditableCellRole,
    ) -> None:
        if not self._save_inline_slot_edit():
            return
        crossword = self._crossword
        if crossword is None:
            return
        try:
            changed = set_crossword_cells_role(crossword, coordinates, role)
        except GuiInputError as error:
            title = (
                "Role polí nelze změnit"
                if len(coordinates) > 1
                else "Roli pole nelze změnit"
            )
            self._show_action_error(title, str(error))
            return
        if changed is crossword:
            return
        if _crossword_change_discards_content(crossword, changed) and not (
            messagebox.askyesno(
                "Změnit role polí?"
                if len(coordinates) > 1
                else "Změnit roli pole?",
                "Změna upraví navazující místa pro hesla a odstraní "
                "jejich vyplněný obsah nebo nastavení tajenky. "
                "Chcete pokračovat?",
                parent=self.root,
            )
        ):
            return

        self._crossword = changed
        self._template_layout = _template_generation_layout(changed)
        self._selected_slot_identifier = None
        self._set_dirty(True)
        self._rebuild_slot_tree()
        self._refresh_crossword_view()

    def _preview_cell_slot_changed(
        self,
        coordinates: tuple[Coordinate, ...],
        direction: WordDirection,
        enabled: bool,
    ) -> None:
        if not self._save_inline_slot_edit():
            return
        crossword = self._crossword
        if crossword is None:
            return
        try:
            changed = set_crossword_cells_slot_start(
                crossword,
                coordinates,
                direction,
                enabled,
            )
        except GuiInputError as error:
            title = (
                "Hesla nelze změnit"
                if len(coordinates) > 1
                else "Heslo nelze změnit"
            )
            self._show_action_error(title, str(error))
            return
        if changed is crossword:
            return
        if _crossword_change_discards_content(crossword, changed) and not (
            messagebox.askyesno(
                "Změnit začátky hesel?"
                if len(coordinates) > 1
                else "Změnit začátek hesla?",
                "Změna upraví navazující místa pro hesla a odstraní "
                "jejich vyplněný obsah nebo nastavení tajenky. "
                "Chcete pokračovat?",
                parent=self.root,
            )
        ):
            return

        self._crossword = changed
        self._template_layout = _template_generation_layout(changed)
        self._selected_slot_identifier = None
        self._set_dirty(True)
        self._rebuild_slot_tree()
        self._refresh_crossword_view()

    def clear_selected_slot(self) -> None:
        crossword = self._crossword
        identifier = self._selected_slot_identifier
        if crossword is None or identifier is None:
            return
        try:
            _, slot = _crossword_slot(crossword, identifier)
        except GuiInputError:
            return
        if slot.answer is None and slot.clue is None:
            return
        self._crossword = clear_crossword_slot(crossword, identifier)
        self._set_dirty(True)
        self._rebuild_slot_tree()
        self._refresh_crossword_view()

    def _refresh_crossword_view(self) -> None:
        self.crossword_preview_frame.configure(
            text=self._crossword_preview_title()
        )
        self._refresh_crossword_preview()
        crossword = self._crossword
        if crossword is None:
            self._cancel_inline_slot_edit()
            self._selected_slot_identifier = None
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
            slot_starts=tuple(
                (item.start, item.direction) for item in crossword.slots
            ),
            external_slot_starts=tuple(
                (item.start, item.direction)
                for item in crossword.slots
                if item.legend_position is None
            ),
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
        if not self._save_inline_slot_edit():
            return
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
        if not self._save_inline_slot_edit():
            return
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
        if not self._save_inline_slot_edit():
            return False
        if self._path is None:
            return self.save_document_as()
        return self._write_document(self._path, overwrite=True)

    def save_document_as(self) -> bool:
        if not self._save_inline_slot_edit():
            return False
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
        if self._slot_list_window is not None:
            self._slot_list_window.title(self._slot_list_window_title())
        if sys.platform == "darwin":
            title_path = (
                str(self._path.absolute()) if self._path is not None else ""
            )
            self.root.attributes("-titlepath", title_path)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._update_title()
        self.application.document_window_changed(self)

    def request_close(self) -> None:
        if not self._save_inline_slot_edit():
            return
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
    if tk.TkVersion < _MINIMUM_TK_VERSION:
        print(
            "chyba: grafické rozhraní vyžaduje Tk 9.0 nebo novější "
            f"(nalezena verze {tk.TkVersion:.1f})",
            file=sys.stderr,
        )
        return 2
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

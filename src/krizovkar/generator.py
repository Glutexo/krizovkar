"""Deterministické plnění husté švédské křížovkové mřížky."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from krizovkar.alphabet import split_answer_letters
from krizovkar.dictionary import CrosswordDictionary
from krizovkar.layout import (
    AxisSegment,
    LayoutError,
    SwedishLayout,
    create_dense_swedish_layout,
)
from krizovkar.model import (
    Coordinate,
    CrosswordGrid,
    CrosswordTemplate,
    EmptyCell,
    ExternalClue,
    Grid,
    LegendCell,
    LetterCell,
    TemplateEmptyCell,
    TemplateGrid,
    TemplateLegendCell,
    TemplateLetterCell,
    WordSlot,
)


DEFAULT_GRID_WIDTH = 15
DEFAULT_GRID_HEIGHT = 10
DEFAULT_SEED = 0
MAX_CLUE_LENGTH = 48
GENERATION_ATTEMPTS = 4
MAX_SEARCH_NODES = 250_000

GridCoordinate = tuple[int, int]


class GenerationError(RuntimeError):
    """Ze zadaného slovníku a rozměru se nepodařilo vytvořit mřížku."""


class _SearchFailed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Entry:
    answer: str
    clue: str
    letters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _BlockFill:
    horizontal: tuple[_Entry, ...]
    vertical: tuple[_Entry, ...]


def generate_swedish_template(
    *,
    width: int = DEFAULT_GRID_WIDTH,
    height: int = DEFAULT_GRID_HEIGHT,
) -> CrosswordTemplate:
    """Vytvoří nevyplněnou hustou švédskou šablonu."""

    try:
        layout = create_dense_swedish_layout(width, height)
    except LayoutError as error:
        raise GenerationError(str(error)) from error

    cells = []
    for row in range(layout.height):
        cell_row = []
        for column in range(layout.width):
            role = layout.role(row, column)
            if role == "empty":
                cell_row.append(TemplateEmptyCell())
            elif role in {"horizontal_legend", "vertical_legend"}:
                cell_row.append(TemplateLegendCell())
            else:
                cell_row.append(TemplateLetterCell())
        cells.append(tuple(cell_row))

    slots = []
    horizontal_number = 1
    for row_segment in layout.row_segments:
        for row in range(row_segment.start, row_segment.stop):
            for column_segment in layout.column_segments:
                slots.append(
                    WordSlot(
                        identifier=f"h{horizontal_number}",
                        start=Coordinate(
                            row=row + 1,
                            column=column_segment.start + 1,
                        ),
                        direction="horizontal",
                        length=column_segment.length,
                        legend_position=Coordinate(
                            row=row + 1,
                            column=column_segment.legend + 1,
                        ),
                    )
                )
                horizontal_number += 1

    vertical_number = 1
    for row_segment in layout.row_segments:
        for column_segment in layout.column_segments:
            for column in range(column_segment.start, column_segment.stop):
                slots.append(
                    WordSlot(
                        identifier=f"v{vertical_number}",
                        start=Coordinate(
                            row=row_segment.start + 1,
                            column=column + 1,
                        ),
                        direction="vertical",
                        length=row_segment.length,
                        legend_position=Coordinate(
                            row=row_segment.legend + 1,
                            column=column + 1,
                        ),
                    )
                )
                vertical_number += 1

    return CrosswordTemplate(
        format_name="krizovkar",
        kind="template",
        version=1,
        grid=TemplateGrid(
            width=layout.width,
            height=layout.height,
            cells=tuple(cells),
        ),
        slots=tuple(slots),
    )


def _usable_entries(
    dictionary: CrosswordDictionary,
) -> dict[int, tuple[_Entry, ...]]:
    entries: dict[int, list[_Entry]] = defaultdict(list)
    for entry in dictionary.entries:
        letters = split_answer_letters(entry.answer)
        clue = next(
            (clue for clue in entry.clues if len(clue) <= MAX_CLUE_LENGTH),
            None,
        )
        if clue is not None:
            entries[len(letters)].append(
                _Entry(answer=entry.answer, clue=clue, letters=letters)
            )
    return {length: tuple(values) for length, values in entries.items()}


def _slot_coordinates(slot: WordSlot) -> tuple[GridCoordinate, ...]:
    row_step = 1 if slot.direction == "vertical" else 0
    column_step = 1 if slot.direction == "horizontal" else 0
    return tuple(
        (
            slot.start.row - 1 + offset * row_step,
            slot.start.column - 1 + offset * column_step,
        )
        for offset in range(slot.length)
    )


def _fill_template_slots(
    template: CrosswordTemplate,
    entries_by_length: dict[int, tuple[_Entry, ...]],
    randomizer: random.Random,
) -> dict[str, _Entry]:
    candidates_by_length = {
        length: list(entries)
        for length, entries in entries_by_length.items()
    }
    for candidates in candidates_by_length.values():
        randomizer.shuffle(candidates)

    coordinates = {
        slot.identifier: _slot_coordinates(slot) for slot in template.slots
    }
    assigned: dict[str, _Entry] = {}
    letters: dict[GridCoordinate, str] = {}
    used_answers: set[str] = set()
    search_nodes = 0

    def compatible_entries(slot: WordSlot) -> list[_Entry]:
        slot_coordinates = coordinates[slot.identifier]
        return [
            entry
            for entry in candidates_by_length.get(slot.length, ())
            if entry.answer not in used_answers
            and all(
                coordinate not in letters or letters[coordinate] == letter
                for coordinate, letter in zip(slot_coordinates, entry.letters)
            )
        ]

    def search() -> dict[str, _Entry] | None:
        nonlocal search_nodes
        if len(assigned) == len(template.slots):
            return dict(assigned)

        selected_slot: WordSlot | None = None
        selected_candidates: list[_Entry] | None = None
        for slot in template.slots:
            if slot.identifier in assigned:
                continue
            candidates = compatible_entries(slot)
            if not candidates:
                return None
            if (
                selected_candidates is None
                or len(candidates) < len(selected_candidates)
            ):
                selected_slot = slot
                selected_candidates = candidates

        assert selected_slot is not None
        assert selected_candidates is not None
        slot_coordinates = coordinates[selected_slot.identifier]
        for entry in selected_candidates:
            search_nodes += 1
            if search_nodes > MAX_SEARCH_NODES:
                raise _SearchFailed

            new_coordinates = []
            for coordinate, letter in zip(slot_coordinates, entry.letters):
                if coordinate not in letters:
                    letters[coordinate] = letter
                    new_coordinates.append(coordinate)
            assigned[selected_slot.identifier] = entry
            used_answers.add(entry.answer)

            result = search()
            if result is not None:
                return result

            used_answers.remove(entry.answer)
            del assigned[selected_slot.identifier]
            for coordinate in new_coordinates:
                del letters[coordinate]
        return None

    result = search()
    if result is None:
        raise _SearchFailed
    return result


def _filled_template_grid(
    template: CrosswordTemplate,
    assignments: dict[str, _Entry],
) -> CrosswordGrid:
    letters: dict[GridCoordinate, str] = {}
    slots_by_legend: dict[GridCoordinate, list[tuple[WordSlot, _Entry]]] = (
        defaultdict(list)
    )
    external_slots = []
    bars: dict[GridCoordinate, set[str]] = defaultdict(set)

    for slot in template.slots:
        entry = assignments[slot.identifier]
        for coordinate, letter in zip(_slot_coordinates(slot), entry.letters):
            letters[coordinate] = letter
        if slot.legend_position is None:
            external_slots.append((slot, entry))
        else:
            legend_coordinate = (
                slot.legend_position.row - 1,
                slot.legend_position.column - 1,
            )
            slots_by_legend[legend_coordinate].append((slot, entry))

        if slot.direction == "horizontal" and slot.start.column > 1:
            previous = (slot.start.row - 1, slot.start.column - 2)
            if isinstance(
                template.grid.cells[previous[0]][previous[1]],
                TemplateLetterCell,
            ):
                bars[previous].add("right")
        if slot.direction == "vertical" and slot.start.row > 1:
            previous = (slot.start.row - 2, slot.start.column - 1)
            if isinstance(
                template.grid.cells[previous[0]][previous[1]],
                TemplateLetterCell,
            ):
                bars[previous].add("bottom")

    external_starts = sorted(
        {
            (slot.start.row - 1, slot.start.column - 1)
            for slot, _ in external_slots
        }
    )
    numbers = {
        coordinate: number
        for number, coordinate in enumerate(external_starts, start=1)
    }
    direction_order = {"horizontal": 0, "vertical": 1}
    clues = tuple(
        ExternalClue(
            number=numbers[(slot.start.row - 1, slot.start.column - 1)],
            direction=slot.direction,
            text=entry.clue,
        )
        for slot, entry in sorted(
            external_slots,
            key=lambda item: (
                numbers[(item[0].start.row - 1, item[0].start.column - 1)],
                direction_order[item[0].direction],
            ),
        )
    )

    cells = []
    for row_index, template_row in enumerate(template.grid.cells):
        row = []
        for column_index, template_cell in enumerate(template_row):
            coordinate = (row_index, column_index)
            if isinstance(template_cell, TemplateEmptyCell):
                row.append(EmptyCell())
            elif isinstance(template_cell, TemplateLegendCell):
                legend_slots = sorted(
                    slots_by_legend[coordinate],
                    key=lambda item: direction_order[item[0].direction],
                )
                row.append(
                    LegendCell(
                        texts=tuple(entry.clue for _, entry in legend_slots)
                    )
                )
            else:
                cell_bars = bars.get(coordinate, set())
                row.append(
                    LetterCell(
                        value=letters[coordinate],
                        number=numbers.get(coordinate),
                        bars=tuple(
                            bar
                            for bar in ("right", "bottom")
                            if bar in cell_bars
                        ),
                    )
                )
        cells.append(tuple(row))

    return CrosswordGrid(
        format_name="krizovkar",
        kind="grid",
        version=1,
        grid=Grid(
            width=template.grid.width,
            height=template.grid.height,
            cells=tuple(cells),
        ),
        clues=clues,
    )


def fill_crossword_template(
    template: CrosswordTemplate,
    dictionary: CrosswordDictionary,
    *,
    seed: int = DEFAULT_SEED,
) -> CrosswordGrid:
    """Vyplní všechny sloty šablony různými hesly ze slovníku."""

    entries_by_length = _usable_entries(dictionary)
    required_lengths = {slot.length for slot in template.slots}
    missing_lengths = sorted(required_lengths - entries_by_length.keys())
    if missing_lengths:
        missing = ", ".join(str(length) for length in missing_lengths)
        raise GenerationError(
            f"slovník neobsahuje použitelná hesla délky: {missing}"
        )

    for attempt in range(GENERATION_ATTEMPTS):
        attempt_seed = seed + attempt * 1_000_003
        try:
            assignments = _fill_template_slots(
                template,
                entries_by_length,
                random.Random(attempt_seed),
            )
            return _filled_template_grid(template, assignments)
        except _SearchFailed:
            continue

    raise GenerationError(
        "nepodařilo se vyplnit všechny sloty platnými křížícími se hesly"
    )


def _prefixes(entries: tuple[_Entry, ...]) -> frozenset[tuple[str, ...]]:
    return frozenset(
        entry.letters[:length]
        for entry in entries
        for length in range(len(entry.letters) + 1)
    )


def _fill_block(
    *,
    width: int,
    height: int,
    entries_by_length: dict[int, tuple[_Entry, ...]],
    used_answers: set[str],
    randomizer: random.Random,
) -> _BlockFill:
    horizontal_candidates = list(entries_by_length.get(width, ()))
    vertical_candidates = entries_by_length.get(height, ())
    if not horizontal_candidates or not vertical_candidates:
        raise _SearchFailed

    randomizer.shuffle(horizontal_candidates)
    vertical_prefixes = _prefixes(vertical_candidates)
    vertical_lookup = {entry.letters: entry for entry in vertical_candidates}
    selected: list[_Entry] = []
    column_prefixes: tuple[tuple[str, ...], ...] = tuple(() for _ in range(width))
    search_nodes = 0

    def search(prefixes: tuple[tuple[str, ...], ...]) -> _BlockFill | None:
        nonlocal search_nodes
        if len(selected) == height:
            vertical = tuple(vertical_lookup.get(prefix) for prefix in prefixes)
            if any(entry is None for entry in vertical):
                return None
            complete_vertical = tuple(entry for entry in vertical if entry is not None)
            answers = [entry.answer for entry in complete_vertical]
            if len(answers) != len(set(answers)):
                return None
            selected_answers = {entry.answer for entry in selected}
            if any(
                answer in used_answers or answer in selected_answers
                for answer in answers
            ):
                return None
            return _BlockFill(
                horizontal=tuple(selected),
                vertical=complete_vertical,
            )

        selected_answers = {entry.answer for entry in selected}
        for entry in horizontal_candidates:
            search_nodes += 1
            if search_nodes > MAX_SEARCH_NODES:
                raise _SearchFailed
            if entry.answer in used_answers or entry.answer in selected_answers:
                continue

            next_prefixes = tuple(
                prefixes[column] + (entry.letters[column],)
                for column in range(width)
            )
            if any(prefix not in vertical_prefixes for prefix in next_prefixes):
                continue

            selected.append(entry)
            result = search(next_prefixes)
            if result is not None:
                return result
            selected.pop()
        return None

    result = search(column_prefixes)
    if result is None:
        raise _SearchFailed
    return result


def _block_order(layout: SwedishLayout) -> tuple[tuple[AxisSegment, AxisSegment], ...]:
    blocks = tuple(
        (row_segment, column_segment)
        for row_segment in layout.row_segments
        for column_segment in layout.column_segments
    )
    return tuple(
        sorted(
            blocks,
            key=lambda block: (
                -(block[0].length * block[1].length),
                -max(block[0].length, block[1].length),
                block[0].start,
                block[1].start,
            ),
        )
    )


def _filled_crossword(
    layout: SwedishLayout,
    entries_by_length: dict[int, tuple[_Entry, ...]],
    randomizer: random.Random,
) -> CrosswordGrid:
    letters: dict[GridCoordinate, str] = {}
    legends: dict[GridCoordinate, str] = {}
    used_answers: set[str] = set()

    for row_segment, column_segment in _block_order(layout):
        block = _fill_block(
            width=column_segment.length,
            height=row_segment.length,
            entries_by_length=entries_by_length,
            used_answers=used_answers,
            randomizer=randomizer,
        )

        for row_offset, entry in enumerate(block.horizontal):
            row = row_segment.start + row_offset
            legends[(row, column_segment.legend)] = entry.clue
            for column_offset, letter in enumerate(entry.letters):
                column = column_segment.start + column_offset
                letters[(row, column)] = letter

        for column_offset, entry in enumerate(block.vertical):
            column = column_segment.start + column_offset
            legends[(row_segment.legend, column)] = entry.clue

        used_answers.update(entry.answer for entry in block.horizontal)
        used_answers.update(entry.answer for entry in block.vertical)

    cells = []
    for row in range(layout.height):
        cell_row = []
        for column in range(layout.width):
            coordinate = (row, column)
            role = layout.role(row, column)
            if role == "empty":
                cell_row.append(EmptyCell())
            elif role in {"horizontal_legend", "vertical_legend"}:
                try:
                    clue = legends[coordinate]
                except KeyError as error:
                    raise _SearchFailed from error
                cell_row.append(LegendCell(texts=(clue,)))
            else:
                try:
                    letter = letters[coordinate]
                except KeyError as error:
                    raise _SearchFailed from error
                cell_row.append(LetterCell(value=letter))
        cells.append(tuple(cell_row))

    return CrosswordGrid(
        format_name="krizovkar",
        kind="grid",
        version=1,
        grid=Grid(
            width=layout.width,
            height=layout.height,
            cells=tuple(cells),
        ),
    )


def generate_swedish_grid(
    dictionary: CrosswordDictionary,
    *,
    width: int = DEFAULT_GRID_WIDTH,
    height: int = DEFAULT_GRID_HEIGHT,
    seed: int = DEFAULT_SEED,
) -> CrosswordGrid:
    """Vyplní hustou švédskou mřížku platnými křížícími se hesly."""

    try:
        layout = create_dense_swedish_layout(width, height)
    except LayoutError as error:
        raise GenerationError(str(error)) from error

    entries_by_length = _usable_entries(dictionary)
    required_lengths = {
        segment.length
        for segment in (*layout.row_segments, *layout.column_segments)
    }
    missing_lengths = sorted(required_lengths - entries_by_length.keys())
    if missing_lengths:
        missing = ", ".join(str(length) for length in missing_lengths)
        raise GenerationError(
            f"slovník neobsahuje použitelná hesla délky: {missing}"
        )

    for attempt in range(GENERATION_ATTEMPTS):
        attempt_seed = seed + attempt * 1_000_003
        try:
            return _filled_crossword(
                layout,
                entries_by_length,
                random.Random(attempt_seed),
            )
        except _SearchFailed:
            continue

    raise GenerationError(
        "nepodařilo se vyplnit všechny písmenné bloky platnými hesly"
    )

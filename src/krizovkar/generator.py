"""Deterministické plnění husté švédské křížovkové mřížky."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from krizovkar.alphabet import split_answer_letters
from krizovkar.dictionary import CrosswordDictionary
from krizovkar.layout import (
    MAX_SEGMENT_LENGTH,
    MIN_SEGMENT_LENGTH,
    AxisSegment,
    LayoutError,
    SwedishLayout,
    create_dense_swedish_layout,
)
from krizovkar.model import CrosswordGrid, EmptyCell, Grid, LegendCell, LetterCell


DEFAULT_GRID_WIDTH = 15
DEFAULT_GRID_HEIGHT = 10
DEFAULT_SEED = 0
MAX_CLUE_LENGTH = 48
GENERATION_ATTEMPTS = 4
MAX_SEARCH_NODES = 250_000

Coordinate = tuple[int, int]


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


def _usable_entries(
    dictionary: CrosswordDictionary,
) -> dict[int, tuple[_Entry, ...]]:
    entries: dict[int, list[_Entry]] = defaultdict(list)
    for entry in dictionary.entries:
        letters = split_answer_letters(entry.answer)
        if not MIN_SEGMENT_LENGTH <= len(letters) <= MAX_SEGMENT_LENGTH:
            continue
        clue = next(
            (clue for clue in entry.clues if len(clue) <= MAX_CLUE_LENGTH),
            None,
        )
        if clue is not None:
            entries[len(letters)].append(
                _Entry(answer=entry.answer, clue=clue, letters=letters)
            )
    return {length: tuple(values) for length, values in entries.items()}


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
    letters: dict[Coordinate, str] = {}
    legends: dict[Coordinate, str] = {}
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

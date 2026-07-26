"""První deterministický generátor švédské křížovkové mřížky."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from krizovkar.alphabet import split_answer_letters
from krizovkar.dictionary import CrosswordDictionary
from krizovkar.model import (
    CrosswordGrid,
    EmptyCell,
    Grid,
    LegendArrow,
    LegendCell,
    LetterCell,
)


DEFAULT_GRID_WIDTH = 15
DEFAULT_GRID_HEIGHT = 10
DEFAULT_SEED = 0
MIN_WORD_LENGTH = 3
MAX_CLUE_LENGTH = 48
MAX_GENERATED_WORDS = 30
MIN_GENERATED_WORDS = 3
CANDIDATE_TRIALS = 8_000
VALID_CANDIDATE_LIMIT = 160

Direction = Literal["horizontal", "vertical"]
Coordinate = tuple[int, int]


class GenerationError(RuntimeError):
    """Ze zadaného slovníku a rozměru se nepodařilo vytvořit mřížku."""


@dataclass(frozen=True, slots=True)
class _Entry:
    answer: str
    clue: str
    letters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Placement:
    entry: _Entry
    row: int
    column: int
    direction: Direction


class _Board:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.letters: dict[Coordinate, str] = {}
        self.orientations: dict[Coordinate, set[Direction]] = defaultdict(set)
        self.legends: dict[Coordinate, dict[LegendArrow, str]] = defaultdict(dict)
        self.placements: list[_Placement] = []
        self.used_answers: set[str] = set()

    def _positions(self, placement: _Placement) -> tuple[Coordinate, ...]:
        row_step = 1 if placement.direction == "vertical" else 0
        column_step = 1 if placement.direction == "horizontal" else 0
        return tuple(
            (
                placement.row + offset * row_step,
                placement.column + offset * column_step,
            )
            for offset in range(len(placement.entry.letters))
        )

    def _legend_position(self, placement: _Placement) -> Coordinate:
        if placement.direction == "horizontal":
            return (placement.row, placement.column - 1)
        return (placement.row - 1, placement.column)

    def _arrow(self, direction: Direction) -> LegendArrow:
        return "right" if direction == "horizontal" else "down"

    def evaluate(
        self,
        placement: _Placement,
        *,
        require_crossing: bool,
    ) -> int | None:
        positions = self._positions(placement)
        if any(
            row < 0 or row >= self.height or column < 0 or column >= self.width
            for row, column in positions
        ):
            return None

        legend_position = self._legend_position(placement)
        if not self._inside(legend_position) or legend_position in self.letters:
            return None

        arrow = self._arrow(placement.direction)
        legend = self.legends.get(legend_position, {})
        if arrow in legend or len(legend) >= 2:
            return None

        after = self._position_after(placement)
        if self._inside(after) and after in self.letters:
            return None

        crossings = 0
        for coordinate, letter in zip(
            positions, placement.entry.letters, strict=True
        ):
            if coordinate in self.legends:
                return None

            existing = self.letters.get(coordinate)
            if existing is not None:
                if existing != letter:
                    return None
                if placement.direction in self.orientations[coordinate]:
                    return None
                crossings += 1
                continue

            neighbors = self._side_neighbors(coordinate, placement.direction)
            if any(neighbor in self.letters for neighbor in neighbors):
                return None

        if require_crossing and crossings == 0:
            return None
        return crossings

    def place(self, placement: _Placement) -> None:
        positions = self._positions(placement)
        for coordinate, letter in zip(
            positions, placement.entry.letters, strict=True
        ):
            self.letters.setdefault(coordinate, letter)
            self.orientations[coordinate].add(placement.direction)

        legend_position = self._legend_position(placement)
        self.legends[legend_position][self._arrow(placement.direction)] = (
            placement.entry.clue
        )
        self.placements.append(placement)
        self.used_answers.add(placement.entry.answer)

    def to_crossword(self) -> CrosswordGrid:
        cells = []
        for row in range(self.height):
            cell_row = []
            for column in range(self.width):
                coordinate = (row, column)
                legend = self.legends.get(coordinate)
                if legend is not None:
                    arrow_order: tuple[LegendArrow, ...] = ("right", "down")
                    arrows = tuple(
                        arrow for arrow in arrow_order if arrow in legend
                    )
                    texts = tuple(legend[arrow] for arrow in arrows)
                    cell_row.append(LegendCell(texts=texts, arrows=arrows))
                elif coordinate in self.letters:
                    cell_row.append(LetterCell(value=self.letters[coordinate]))
                else:
                    cell_row.append(EmptyCell())
            cells.append(tuple(cell_row))

        return CrosswordGrid(
            format_name="krizovkar",
            kind="grid",
            version=1,
            grid=Grid(
                width=self.width,
                height=self.height,
                cells=tuple(cells),
            ),
        )

    def _inside(self, coordinate: Coordinate) -> bool:
        row, column = coordinate
        return 0 <= row < self.height and 0 <= column < self.width

    def _position_after(self, placement: _Placement) -> Coordinate:
        length = len(placement.entry.letters)
        if placement.direction == "horizontal":
            return (placement.row, placement.column + length)
        return (placement.row + length, placement.column)

    def _side_neighbors(
        self,
        coordinate: Coordinate,
        direction: Direction,
    ) -> tuple[Coordinate, Coordinate]:
        row, column = coordinate
        if direction == "horizontal":
            return ((row - 1, column), (row + 1, column))
        return ((row, column - 1), (row, column + 1))


def _usable_entries(
    dictionary: CrosswordDictionary,
    width: int,
    height: int,
) -> tuple[_Entry, ...]:
    maximum_length = max(width - 1, height - 1)
    entries = []
    for entry in dictionary.entries:
        letters = split_answer_letters(entry.answer)
        if not MIN_WORD_LENGTH <= len(letters) <= maximum_length:
            continue
        clue = next(
            (clue for clue in entry.clues if len(clue) <= MAX_CLUE_LENGTH),
            None,
        )
        if clue is not None:
            entries.append(
                _Entry(answer=entry.answer, clue=clue, letters=letters)
            )
    return tuple(entries)


def _initial_placement(
    entries: tuple[_Entry, ...],
    width: int,
    height: int,
    randomizer: random.Random,
) -> _Placement:
    if width > height:
        direction: Direction = "horizontal"
    elif height > width:
        direction = "vertical"
    else:
        direction = randomizer.choice(("horizontal", "vertical"))
    available_space = width - 1 if direction == "horizontal" else height - 1
    fitting = tuple(entry for entry in entries if len(entry.letters) <= available_space)
    if not fitting:
        raise GenerationError("slovník neobsahuje heslo, které se vejde do mřížky")

    longest = max(len(entry.letters) for entry in fitting)
    seeds = tuple(entry for entry in fitting if len(entry.letters) == longest)
    entry = randomizer.choice(seeds)
    if direction == "horizontal":
        legend_column = (width - len(entry.letters) - 1) // 2
        return _Placement(
            entry=entry,
            row=height // 2,
            column=legend_column + 1,
            direction=direction,
        )

    legend_row = (height - len(entry.letters) - 1) // 2
    return _Placement(
        entry=entry,
        row=legend_row + 1,
        column=width // 2,
        direction=direction,
    )


def _entry_index(
    entries: tuple[_Entry, ...],
) -> dict[str, tuple[tuple[_Entry, int], ...]]:
    indexed: dict[str, list[tuple[_Entry, int]]] = defaultdict(list)
    for entry in entries:
        for offset, letter in enumerate(entry.letters):
            indexed[letter].append((entry, offset))
    return {letter: tuple(options) for letter, options in indexed.items()}


def _crossing_placement(
    board: _Board,
    index: dict[str, tuple[tuple[_Entry, int], ...]],
    randomizer: random.Random,
) -> _Placement | None:
    candidates: dict[tuple[str, int, int, Direction], tuple[float, _Placement]] = {}
    anchors = tuple(board.letters.items())
    if not anchors:
        return None

    for _ in range(CANDIDATE_TRIALS):
        (anchor_row, anchor_column), letter = randomizer.choice(anchors)
        orientations = board.orientations[(anchor_row, anchor_column)]
        possible_directions = tuple(
            direction
            for direction in ("horizontal", "vertical")
            if direction not in orientations
        )
        if not possible_directions:
            continue
        direction = randomizer.choice(possible_directions)

        options = index.get(letter, ())
        if not options:
            continue
        entry, offset = randomizer.choice(options)
        if entry.answer in board.used_answers:
            continue

        row = anchor_row - (offset if direction == "vertical" else 0)
        column = anchor_column - (offset if direction == "horizontal" else 0)
        placement = _Placement(
            entry=entry,
            row=row,
            column=column,
            direction=direction,
        )
        crossings = board.evaluate(placement, require_crossing=True)
        if crossings is None:
            continue

        legend = board._legend_position(placement)
        shared_legend = int(legend in board.legends)
        center_distance = abs(row - board.height / 2) + abs(column - board.width / 2)
        score = (
            crossings * 100
            + shared_legend * 25
            + len(entry.letters) * 2
            - center_distance
            + randomizer.random()
        )
        key = (entry.answer, row, column, direction)
        candidates[key] = (score, placement)
        if len(candidates) >= VALID_CANDIDATE_LIMIT:
            break

    if not candidates:
        return None
    return max(candidates.values(), key=lambda item: item[0])[1]


def generate_swedish_grid(
    dictionary: CrosswordDictionary,
    *,
    width: int = DEFAULT_GRID_WIDTH,
    height: int = DEFAULT_GRID_HEIGHT,
    seed: int = DEFAULT_SEED,
) -> CrosswordGrid:
    """Vytvoří propojenou mřížku s hesly doprava a dolů.

    Neobsazené buňky označí jako nevyplňované. Písmenné buňky obsahují
    řešení, aby šlo v první experimentální verzi zkontrolovat křížení.
    """

    if width < 3 or height < 3:
        raise GenerationError("šířka i výška mřížky musí být alespoň 3")

    entries = _usable_entries(dictionary, width, height)
    if not entries:
        raise GenerationError("slovník neobsahuje použitelná hesla s legendami")

    randomizer = random.Random(seed)
    board = _Board(width, height)
    initial = _initial_placement(entries, width, height, randomizer)
    board.place(initial)
    index = _entry_index(entries)
    target = min(MAX_GENERATED_WORDS, max(MIN_GENERATED_WORDS, width * height // 7))

    while len(board.placements) < target:
        placement = _crossing_placement(board, index, randomizer)
        if placement is None:
            break
        board.place(placement)

    if len(board.placements) < MIN_GENERATED_WORDS:
        raise GenerationError(
            "nepodařilo se najít alespoň tři navzájem propojená hesla"
        )
    return board.to_crossword()

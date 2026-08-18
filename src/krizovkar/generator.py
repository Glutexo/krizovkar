"""Generování šablon a deterministické plnění křížovek."""

from __future__ import annotations

import random
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Literal

from krizovkar.alphabet import SUPPORTED_SINGLE_LETTERS, split_answer_letters
from krizovkar.dictionary import CrosswordDictionary
from krizovkar.layout import (
    MAX_SEGMENT_LENGTH,
    MIN_SEGMENT_LENGTH,
    LayoutError,
    NumberedLayout,
    SwedishLayout,
    create_dense_numbered_layout,
    create_dense_numbered_layout_candidates,
    create_dense_swedish_layout,
    create_dense_swedish_layout_candidates,
)
from krizovkar.model import (
    DEFAULT_SECRET_LEGEND,
    DEFAULT_SECRET_PART_LEGEND,
    Coordinate,
    CrosswordDocument,
    CrosswordGrid,
    CrosswordLayout,
    CrosswordSecret,
    CrosswordSecretCellsPart,
    CrosswordSecretSlotPart,
    CrosswordSpecification,
    EmptyCell,
    EmptyCellRole,
    ExternalClue,
    Grid,
    HelpCell,
    HelpCellRole,
    LegendCell,
    LegendCellRole,
    LetterCell,
    LetterCellRole,
    SecretArrow,
    SecretCell,
    SecretCells,
    SecretPart,
    SecretParts,
    SecretPrompt,
    SecretWord,
    WordDirection,
    WordSlot,
    secret_path_arrows,
)

DEFAULT_GRID_WIDTH = 15
DEFAULT_GRID_HEIGHT = 10
DEFAULT_SEED = 0
MAX_CLUE_LENGTH = 48
FILLING_ATTEMPTS = 4
MAX_SEARCH_NODES = 250_000
PREFERRED_SECRET_PART_LENGTH = 4

GridCoordinate = tuple[int, int]
SpecificationLayout = Literal["swedish", "numbered"]


class GenerationError(RuntimeError):
    """Šablonu se nepodařilo vygenerovat."""


class FillingError(RuntimeError):
    """Křížovku se nepodařilo vyplnit."""


class _SearchFailed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SecretRequirement:
    """Požadovaná délka nebo známá slova jedné tajenky."""

    total_length: int | None = None
    part_lengths: tuple[int, ...] = ()
    words: tuple[str, ...] = ()
    part_word_counts: tuple[int, ...] = ()
    prompt: SecretPrompt | None = None


@dataclass(frozen=True, slots=True)
class _Entry:
    answer: str
    clue: str
    letters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SpecificationSlot:
    """Pevné heslo zadání převáděné na místo v šabloně."""

    token: tuple[str, int, int]
    answer: str
    start: Coordinate
    direction: WordDirection
    clue: str
    in_help: bool
    order: int


def normalize_secret_text(text: str) -> tuple[str, ...]:
    """Převede text tajenky na velká slova bez mezer a interpunkce."""

    normalized = unicodedata.normalize("NFC", text).upper()
    supported = frozenset(SUPPORTED_SINGLE_LETTERS)
    words = []
    current = []
    for character in normalized:
        if character in supported:
            current.append(character)
            continue
        if character.isspace() or unicodedata.category(character).startswith("P"):
            if current:
                words.append("".join(current))
                current = []
            continue
        raise GenerationError(
            f"tajenka obsahuje nepodporovaný znak {character!r}"
        )
    if current:
        words.append("".join(current))
    if not words:
        raise GenerationError("tajenka musí obsahovat alespoň jedno slovo")
    return tuple(words)


def _validate_secret_requirement(requirement: SecretRequirement) -> None:
    modes = sum(
        (
            requirement.total_length is not None,
            bool(requirement.part_lengths),
            bool(requirement.words),
        )
    )
    if modes != 1:
        raise GenerationError(
            "tajenka musí určit právě jednu z možností: "
            "celkovou délku, délky částí, nebo konkrétní slova"
        )
    if requirement.total_length is not None and requirement.total_length < 1:
        raise GenerationError("délka tajenky musí být kladná")
    if requirement.part_lengths and any(
        length < 1 for length in requirement.part_lengths
    ):
        raise GenerationError("délky částí tajenky musí být kladné")
    if requirement.part_word_counts and not requirement.words:
        raise GenerationError(
            "počty slov částí lze uvést jen u konkrétní tajenky"
        )
    for word in requirement.words:
        try:
            split_answer_letters(word)
        except ValueError as error:
            raise GenerationError(str(error)) from error
    if requirement.words and requirement.part_word_counts:
        if any(count < 1 for count in requirement.part_word_counts):
            raise GenerationError("každá část tajenky musí obsahovat celé slovo")
        if sum(requirement.part_word_counts) != len(requirement.words):
            raise GenerationError(
                "součet počtů slov částí neodpovídá počtu slov tajenky"
            )


def _specification_secret_parts(
    secret: SecretPart | SecretParts,
) -> tuple[tuple[SecretPart, ...], SecretPrompt | None]:
    if isinstance(secret, SecretParts):
        return secret.parts, secret.prompt
    return (secret,), secret.prompt


def _specified_slot_coordinates(
    slot: _SpecificationSlot,
) -> tuple[GridCoordinate, ...]:
    row_step = 1 if slot.direction == "vertical" else 0
    column_step = 1 if slot.direction == "horizontal" else 0
    return tuple(
        (
            slot.start.row - 1 + offset * row_step,
            slot.start.column - 1 + offset * column_step,
        )
        for offset in range(len(split_answer_letters(slot.answer)))
    )


def create_template_from_specification(
    specification: CrosswordSpecification,
    *,
    layout: SpecificationLayout = "swedish",
) -> CrosswordDocument:
    """Rozvrhne umístěné zadání do šablony křížovky."""

    if layout not in {"swedish", "numbered"}:
        raise GenerationError(f"nepodporované rozvržení {layout!r}")
    if specification.grid is None:
        raise GenerationError("zadání neobsahuje rozměr mřížky")
    width = specification.grid.width
    height = specification.grid.height
    if width < 1 or height < 1:
        raise GenerationError("rozměry mřížky musí být kladné")

    specified_slots: list[_SpecificationSlot] = []
    order = 0
    for word_index, word in enumerate(specification.words):
        specified_slots.append(
            _SpecificationSlot(
                token=("word", word_index, 0),
                answer=word.answer,
                start=word.start,
                direction=word.direction,
                clue=word.legend,
                in_help=word.in_help,
                order=order,
            )
        )
        order += 1

    for secret_index, secret in enumerate(specification.secrets):
        parts, _ = _specification_secret_parts(secret)
        for part_index, part in enumerate(parts):
            if not isinstance(part, SecretWord):
                continue
            specified_slots.append(
                _SpecificationSlot(
                    token=("secret", secret_index, part_index),
                    answer=part.answer,
                    start=part.start,
                    direction=part.direction,
                    clue=part.legend,
                    in_help=False,
                    order=order,
                )
            )
            order += 1

    if not specified_slots:
        raise GenerationError("zadání neobsahuje žádné umístěné heslo")

    letter_values: dict[GridCoordinate, tuple[str, str]] = {}
    occupied_directions: dict[
        tuple[GridCoordinate, WordDirection], str
    ] = {}
    for slot in specified_slots:
        try:
            letters = split_answer_letters(slot.answer)
        except ValueError as error:
            raise GenerationError(str(error)) from error
        coordinates = _specified_slot_coordinates(slot)
        for coordinate, letter in zip(coordinates, letters):
            row, column = coordinate
            if row < 0 or column < 0 or row >= height or column >= width:
                raise GenerationError(
                    f"heslo {slot.answer!r} přesahuje mřížku "
                    f"{width} × {height}"
                )
            direction_key = (coordinate, slot.direction)
            previous_slot = occupied_directions.get(direction_key)
            if previous_slot is not None:
                raise GenerationError(
                    f"heslo {slot.answer!r} se ve stejném směru překrývá "
                    f"s heslem {previous_slot!r}"
                )
            occupied_directions[direction_key] = slot.answer

            previous_letter = letter_values.get(coordinate)
            if previous_letter is not None and previous_letter[0] != letter:
                raise GenerationError(
                    f"písmeno {letter!r} hesla {slot.answer!r} je v rozporu "
                    f"s písmenem {previous_letter[0]!r} hesla "
                    f"{previous_letter[1]!r}"
                )
            letter_values.setdefault(coordinate, (letter, slot.answer))

    direction_order = {"horizontal": 0, "vertical": 1}
    ordered_slots = sorted(
        specified_slots,
        key=lambda slot: (
            direction_order[slot.direction],
            slot.start.row,
            slot.start.column,
            slot.order,
        ),
    )
    identifiers: dict[tuple[str, int, int], str] = {}
    direction_counts: dict[WordDirection, int] = {
        "horizontal": 0,
        "vertical": 0,
    }
    for slot in ordered_slots:
        direction_counts[slot.direction] += 1
        prefix = "h" if slot.direction == "horizontal" else "v"
        identifiers[slot.token] = f"{prefix}{direction_counts[slot.direction]}"

    legend_coordinates: set[GridCoordinate] = set()
    if layout == "swedish":
        for slot in specified_slots:
            legend = (
                Coordinate(
                    row=slot.start.row,
                    column=slot.start.column - 1,
                )
                if slot.direction == "horizontal"
                else Coordinate(
                    row=slot.start.row - 1,
                    column=slot.start.column,
                )
            )
            legend_coordinate = (legend.row - 1, legend.column - 1)
            if legend.row < 1 or legend.column < 1:
                raise GenerationError(
                    f"před heslo {slot.answer!r} se do mřížky nevejde "
                    "vepsaná legenda"
                )
            if legend_coordinate in letter_values:
                raise GenerationError(
                    f"vepsaná legenda hesla {slot.answer!r} by překryla "
                    "písmennou buňku"
                )
            legend_coordinates.add(legend_coordinate)

    help_coordinate: GridCoordinate | None = None
    if any(slot.in_help for slot in specified_slots):
        unavailable = set(letter_values) | legend_coordinates
        if specification.help_position is not None:
            help_coordinate = (
                specification.help_position.row - 1,
                specification.help_position.column - 1,
            )
            row, column = help_coordinate
            if row < 0 or column < 0 or row >= height or column >= width:
                raise GenerationError("poloha pomůcky leží mimo mřížku")
            if help_coordinate in unavailable:
                raise GenerationError(
                    "zadaná poloha pomůcky koliduje s písmenem nebo legendou"
                )
        else:
            help_coordinate = next(
                (
                    (row, column)
                    for row in range(height)
                    for column in range(width)
                    if (row, column) not in unavailable
                ),
                None,
            )
            if help_coordinate is None:
                raise GenerationError(
                    "pomůcku nelze umístit, protože rozvržení nemá volnou "
                    "buňku"
                )

    cells = []
    for row in range(height):
        cell_row = []
        for column in range(width):
            coordinate = (row, column)
            if coordinate in letter_values:
                cell_row.append(LetterCellRole())
            elif coordinate in legend_coordinates:
                cell_row.append(LegendCellRole())
            elif coordinate == help_coordinate:
                cell_row.append(HelpCellRole())
            else:
                cell_row.append(EmptyCellRole())
        cells.append(tuple(cell_row))

    slots = tuple(
        WordSlot(
            identifier=identifiers[slot.token],
            start=slot.start,
            direction=slot.direction,
            length=len(split_answer_letters(slot.answer)),
            clue_placement="inline" if layout == "swedish" else "external",
            answer=slot.answer,
            clue=slot.clue,
            in_help=slot.in_help,
        )
        for slot in specified_slots
    )

    crossword_secrets = []
    for secret_index, secret in enumerate(specification.secrets):
        secret_parts, prompt = _specification_secret_parts(secret)
        parts: list[CrosswordSecretSlotPart | CrosswordSecretCellsPart] = []
        words = []
        for part_index, part in enumerate(secret_parts):
            if isinstance(part, SecretWord):
                parts.append(
                    CrosswordSecretSlotPart(
                        slot_identifier=identifiers[
                            ("secret", secret_index, part_index)
                        ],
                        word_count=1,
                    )
                )
                words.append(part.answer)
            else:
                parts.append(
                    CrosswordSecretCellsPart(
                        cells=part.cells,
                        arrows=part.arrows,
                    )
                )
        crossword_secrets.append(
            CrosswordSecret(
                parts=tuple(parts),
                words=tuple(words),
                prompt=prompt,
            )
        )

    return CrosswordDocument(
        format_name="krizovkar",
        kind="crossword",
        version=1,
        grid=CrosswordLayout(
            width=width,
            height=height,
            cells=tuple(cells),
        ),
        slots=slots,
        secrets=tuple(crossword_secrets),
    )


def generate_swedish_template(
    *,
    width: int = DEFAULT_GRID_WIDTH,
    height: int = DEFAULT_GRID_HEIGHT,
    seed: int = DEFAULT_SEED,
    secret: SecretRequirement | None = None,
) -> CrosswordDocument:
    """Vytvoří nevyplněnou šablonu s vepsanými legendami."""

    if secret is None:
        try:
            return _swedish_template_from_layout(
                create_dense_swedish_layout(width, height)
            )
        except LayoutError as error:
            raise GenerationError(str(error)) from error

    _validate_secret_requirement(secret)
    last_error: Exception | None = None
    for part_lengths in _secret_length_options(secret):
        try:
            layouts = create_dense_swedish_layout_candidates(
                width,
                height,
                required_lengths=part_lengths,
            )
        except LayoutError as error:
            last_error = error
            continue
        for layout in layouts:
            try:
                return place_secret_in_template(
                    _swedish_template_from_layout(layout),
                    secret,
                    seed=seed,
                )
            except GenerationError as error:
                last_error = error

    detail = f": {last_error}" if last_error is not None else ""
    raise GenerationError(
        f"pro rozměr {width} × {height} nelze rozvrhnout tajenku{detail}"
    )


def generate_numbered_template(
    *,
    width: int = DEFAULT_GRID_WIDTH,
    height: int = DEFAULT_GRID_HEIGHT,
    seed: int = DEFAULT_SEED,
    secret: SecretRequirement | None = None,
) -> CrosswordDocument:
    """Vytvoří nevyplněnou šablonu s vnějšími legendami."""

    if secret is None:
        try:
            return _numbered_template_from_layout(
                create_dense_numbered_layout(width, height)
            )
        except LayoutError as error:
            raise GenerationError(str(error)) from error

    _validate_secret_requirement(secret)
    last_error: Exception | None = None
    for part_lengths in _secret_length_options(secret):
        try:
            layouts = create_dense_numbered_layout_candidates(
                width,
                height,
                required_lengths=part_lengths,
            )
        except LayoutError as error:
            last_error = error
            continue
        for layout in layouts:
            try:
                return place_secret_in_template(
                    _numbered_template_from_layout(layout),
                    secret,
                    seed=seed,
                )
            except GenerationError as error:
                last_error = error

    detail = f": {last_error}" if last_error is not None else ""
    raise GenerationError(
        f"pro rozměr {width} × {height} nelze rozvrhnout tajenku{detail}"
    )


def _swedish_template_from_layout(layout: SwedishLayout) -> CrosswordDocument:

    cells = []
    for row in range(layout.height):
        cell_row = []
        for column in range(layout.width):
            role = layout.role(row, column)
            if role == "empty":
                cell_row.append(EmptyCellRole())
            elif role in {"horizontal_legend", "vertical_legend"}:
                cell_row.append(LegendCellRole())
            else:
                cell_row.append(LetterCellRole())
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
                        clue_placement="inline",
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
                        clue_placement="inline",
                    )
                )
                vertical_number += 1

    return CrosswordDocument(
        format_name="krizovkar",
        kind="crossword",
        version=1,
        grid=CrosswordLayout(
            width=layout.width,
            height=layout.height,
            cells=tuple(cells),
        ),
        slots=tuple(slots),
    )


def _numbered_template_from_layout(
    layout: NumberedLayout,
) -> CrosswordDocument:
    cells = tuple(
        tuple(LetterCellRole() for _ in range(layout.width))
        for _ in range(layout.height)
    )

    slots = []
    horizontal_number = 1
    for row in range(layout.height):
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
                )
            )
            horizontal_number += 1

    vertical_number = 1
    for row_segment in layout.row_segments:
        for column in range(layout.width):
            slots.append(
                WordSlot(
                    identifier=f"v{vertical_number}",
                    start=Coordinate(
                        row=row_segment.start + 1,
                        column=column + 1,
                    ),
                    direction="vertical",
                    length=row_segment.length,
                )
            )
            vertical_number += 1

    return CrosswordDocument(
        format_name="krizovkar",
        kind="crossword",
        version=1,
        grid=CrosswordLayout(
            width=layout.width,
            height=layout.height,
            cells=cells,
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


def _part_lengths_from_word_counts(
    words: tuple[str, ...],
    counts: tuple[int, ...],
) -> tuple[int, ...]:
    lengths = []
    offset = 0
    for count in counts:
        part_words = words[offset : offset + count]
        offset += count
        lengths.append(len(split_answer_letters("".join(part_words))))
    return tuple(lengths)


def _word_partitions(
    words: tuple[str, ...],
    available_lengths: frozenset[int],
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    results: list[tuple[tuple[int, ...], tuple[int, ...]]] = []

    def search(
        word_index: int,
        lengths: tuple[int, ...],
        counts: tuple[int, ...],
    ) -> None:
        if word_index == len(words):
            results.append((lengths, counts))
            return
        for following_index in range(word_index + 1, len(words) + 1):
            part = "".join(words[word_index:following_index])
            length = len(split_answer_letters(part))
            if length in available_lengths:
                search(
                    following_index,
                    (*lengths, length),
                    (*counts, following_index - word_index),
                )

    search(0, (), ())
    return tuple(sorted(results, key=lambda partition: len(partition[0])))


def _total_length_partitions(total_length: int) -> tuple[tuple[int, ...], ...]:
    results = []

    def search(
        remaining: int,
        minimum: int,
        lengths: tuple[int, ...],
    ) -> None:
        if remaining == 0:
            results.append(lengths)
            return
        for length in range(
            minimum,
            min(MAX_SEGMENT_LENGTH, remaining) + 1,
        ):
            search(remaining - length, length, (*lengths, length))

    search(total_length, MIN_SEGMENT_LENGTH, ())
    return tuple(
        sorted(
            results,
            key=lambda lengths: (
                len(lengths),
                sum(
                    abs(length - PREFERRED_SECRET_PART_LENGTH)
                    for length in lengths
                ),
                lengths,
            ),
        )
    )


def _secret_length_options(
    requirement: SecretRequirement,
) -> tuple[tuple[int, ...], ...]:
    if requirement.total_length is not None:
        return _total_length_partitions(requirement.total_length)
    if requirement.part_lengths:
        return (requirement.part_lengths,)
    if requirement.part_word_counts:
        return (
            _part_lengths_from_word_counts(
                requirement.words,
                requirement.part_word_counts,
            ),
        )
    partitions = _word_partitions(
        requirement.words,
        frozenset(range(MIN_SEGMENT_LENGTH, MAX_SEGMENT_LENGTH + 1)),
    )
    return tuple(lengths for lengths, _ in partitions)


def _select_slots_for_lengths(
    slots: list[WordSlot],
    lengths: tuple[int, ...],
) -> tuple[WordSlot, ...] | None:
    selected: list[WordSlot] = []
    used_identifiers: set[str] = set()
    used_coordinates: set[GridCoordinate] = set()

    def search(part_index: int) -> bool:
        if part_index == len(lengths):
            return True
        for slot in slots:
            if (
                slot.identifier in used_identifiers
                or slot.length != lengths[part_index]
            ):
                continue
            coordinates = set(_slot_coordinates(slot))
            if coordinates & used_coordinates:
                continue
            selected.append(slot)
            used_identifiers.add(slot.identifier)
            used_coordinates.update(coordinates)
            if search(part_index + 1):
                return True
            used_coordinates.difference_update(coordinates)
            used_identifiers.remove(slot.identifier)
            selected.pop()
        return False

    return tuple(selected) if search(0) else None


def _select_slot_count_for_total_length(
    slots: list[WordSlot],
    total_length: int,
    part_count: int,
) -> tuple[WordSlot, ...] | None:
    selected: list[WordSlot] = []
    used_coordinates: set[GridCoordinate] = set()

    def search(start_index: int, remaining: int) -> bool:
        if len(selected) == part_count:
            return remaining == 0
        if remaining <= 0:
            return False
        for slot_index in range(start_index, len(slots)):
            slot = slots[slot_index]
            if slot.length > remaining:
                continue
            coordinates = set(_slot_coordinates(slot))
            if coordinates & used_coordinates:
                continue
            selected.append(slot)
            used_coordinates.update(coordinates)
            if search(slot_index + 1, remaining - slot.length):
                return True
            used_coordinates.difference_update(coordinates)
            selected.pop()
        return False

    return tuple(selected) if search(0, total_length) else None


def _select_slots_for_total_length(
    slots: list[WordSlot],
    total_length: int,
) -> tuple[WordSlot, ...] | None:
    minimum_length = min(slot.length for slot in slots)
    maximum_parts = min(len(slots), total_length // minimum_length)
    for part_count in range(1, maximum_parts + 1):
        selected = _select_slot_count_for_total_length(
            slots,
            total_length,
            part_count,
        )
        if selected is not None:
            return selected
    return None


def place_secret_in_template(
    template: CrosswordDocument,
    requirement: SecretRequirement,
    *,
    seed: int = DEFAULT_SEED,
) -> CrosswordDocument:
    """Rezervuje v šabloně nepřekrývající se sloty pro tajenku."""

    if template.secrets:
        raise GenerationError("šablona už obsahuje připravenou tajenku")
    _validate_secret_requirement(requirement)
    slots = list(template.slots)
    random.Random(seed).shuffle(slots)

    selected: tuple[WordSlot, ...] | None = None
    word_counts: tuple[int, ...] = ()
    if requirement.total_length is not None:
        selected = _select_slots_for_total_length(
            slots,
            requirement.total_length,
        )
    elif requirement.part_lengths:
        selected = _select_slots_for_lengths(slots, requirement.part_lengths)
    elif requirement.part_word_counts:
        lengths = _part_lengths_from_word_counts(
            requirement.words,
            requirement.part_word_counts,
        )
        selected = _select_slots_for_lengths(slots, lengths)
        word_counts = requirement.part_word_counts
    else:
        available_lengths = frozenset(slot.length for slot in slots)
        for lengths, counts in _word_partitions(
            requirement.words,
            available_lengths,
        ):
            selected = _select_slots_for_lengths(slots, lengths)
            if selected is not None:
                word_counts = counts
                break

    if selected is None:
        raise GenerationError(
            "v šabloně nelze pro požadovanou tajenku najít "
            "vhodné nepřekrývající se sloty"
        )
    parts = tuple(
        CrosswordSecretSlotPart(
            slot_identifier=slot.identifier,
            word_count=(word_counts[index] if word_counts else None),
        )
        for index, slot in enumerate(selected)
    )
    return replace(
        template,
        secrets=(
            CrosswordSecret(
                parts=parts,
                words=requirement.words,
                prompt=requirement.prompt,
            ),
        ),
    )


def _word_counts_for_exact_lengths(
    words: tuple[str, ...],
    lengths: tuple[int, ...],
) -> tuple[int, ...] | None:
    for partition_lengths, counts in _word_partitions(
        words,
        frozenset(lengths),
    ):
        if partition_lengths == lengths:
            return counts
    return None


def _resolve_crossword_secrets(
    crossword: CrosswordDocument,
    requirement: SecretRequirement | None,
    seed: int,
) -> CrosswordDocument:
    unknown_indices = tuple(
        index
        for index, secret in enumerate(crossword.secrets)
        if not secret.words
        and any(
            isinstance(part, CrosswordSecretSlotPart)
            for part in secret.parts
        )
    )
    if requirement is None:
        if unknown_indices:
            raise FillingError(
                "dokument rezervuje tajenku bez známého znění; "
                "při plnění je nutné zadat konkrétní tajenku"
            )
        return crossword

    try:
        _validate_secret_requirement(requirement)
    except GenerationError as error:
        raise FillingError(str(error)) from error
    if not requirement.words:
        raise FillingError(
            "při plnění je nutné zadat konkrétní slova tajenky"
        )
    if not crossword.secrets:
        try:
            return place_secret_in_template(crossword, requirement, seed=seed)
        except GenerationError as error:
            raise FillingError(str(error)) from error
    if not unknown_indices:
        raise FillingError("dokument už obsahuje konkrétní tajenku")
    if len(unknown_indices) > 1:
        raise FillingError(
            "dokument obsahuje více neznámých tajenek; "
            "jedním zadáním je nelze jednoznačně doplnit"
        )

    secret_index = unknown_indices[0]
    reserved = crossword.secrets[secret_index]
    slots_by_identifier = {slot.identifier: slot for slot in crossword.slots}
    reserved_slot_parts = tuple(
        part
        for part in reserved.parts
        if isinstance(part, CrosswordSecretSlotPart)
    )
    lengths = tuple(
        slots_by_identifier[part.slot_identifier].length
        for part in reserved_slot_parts
    )
    if requirement.part_word_counts:
        counts = requirement.part_word_counts
        if _part_lengths_from_word_counts(requirement.words, counts) != lengths:
            raise FillingError(
                "pevné rozdělení tajenky neodpovídá délkám "
                "připravených slotů"
            )
    else:
        counts = _word_counts_for_exact_lengths(requirement.words, lengths)
        if counts is None:
            raise FillingError(
                "tajenku nelze rozdělit na hranicích slov podle délek "
                "připravených slotů"
            )

    secrets = list(crossword.secrets)
    count_offset = 0
    resolved_parts = []
    for part in reserved.parts:
        if isinstance(part, CrosswordSecretCellsPart):
            resolved_parts.append(part)
            continue
        resolved_parts.append(
            CrosswordSecretSlotPart(
                slot_identifier=part.slot_identifier,
                word_count=counts[count_offset],
            )
        )
        count_offset += 1
    secrets[secret_index] = CrosswordSecret(
        parts=tuple(resolved_parts),
        words=requirement.words,
        prompt=requirement.prompt or reserved.prompt,
    )
    return replace(crossword, secrets=tuple(secrets))


def _secret_assignments(
    crossword: CrosswordDocument,
) -> dict[str, _Entry]:
    assignments: dict[str, _Entry] = {}
    for secret in crossword.secrets:
        word_offset = 0
        multipart = len(secret.parts) > 1
        for part_index, part in enumerate(secret.parts):
            if isinstance(part, CrosswordSecretCellsPart):
                continue
            assert part.word_count is not None
            part_words = secret.words[
                word_offset : word_offset + part.word_count
            ]
            word_offset += part.word_count
            answer = "".join(part_words)
            clue = (
                DEFAULT_SECRET_PART_LEGEND.format(number=part_index + 1)
                if multipart
                else DEFAULT_SECRET_LEGEND
            )
            assignments[part.slot_identifier] = _Entry(
                answer=answer,
                clue=clue,
                letters=split_answer_letters(answer),
            )
    return assignments


def _fixed_crossword_assignments(
    crossword: CrosswordDocument,
) -> dict[str, _Entry]:
    return {
        slot.identifier: _Entry(
            answer=slot.answer,
            clue=slot.clue,
            letters=split_answer_letters(slot.answer),
        )
        for slot in crossword.slots
        if slot.answer is not None and slot.clue is not None
    }


def _fill_crossword_slots(
    crossword: CrosswordDocument,
    entries_by_length: dict[int, tuple[_Entry, ...]],
    randomizer: random.Random,
    fixed_assignments: dict[str, _Entry] | None = None,
) -> dict[str, _Entry]:
    candidates_by_length = {
        length: list(entries)
        for length, entries in entries_by_length.items()
    }
    for candidates in candidates_by_length.values():
        randomizer.shuffle(candidates)

    coordinates = {
        slot.identifier: _slot_coordinates(slot) for slot in crossword.slots
    }
    assigned: dict[str, _Entry] = dict(fixed_assignments or {})
    letters: dict[GridCoordinate, str] = {}
    used_answers: set[str] = {
        entry.answer for entry in assigned.values()
    }
    search_nodes = 0

    slots_by_identifier = {slot.identifier: slot for slot in crossword.slots}
    for identifier, entry in assigned.items():
        slot = slots_by_identifier[identifier]
        if len(entry.letters) != slot.length:
            raise _SearchFailed
        for coordinate, letter in zip(_slot_coordinates(slot), entry.letters):
            previous = letters.get(coordinate)
            if previous is not None and previous != letter:
                raise _SearchFailed
            letters[coordinate] = letter

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
        if len(assigned) == len(crossword.slots):
            return dict(assigned)

        selected_slot: WordSlot | None = None
        selected_candidates: list[_Entry] | None = None
        for slot in crossword.slots:
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


def crossword_external_slot_numbers(
    crossword: CrosswordDocument,
) -> dict[str, int]:
    """Očísluje nelegendované sloty po polích a pak podle směru."""

    direction_order = {"horizontal": 0, "vertical": 1}
    external_slots = sorted(
        (
            slot
            for slot in crossword.slots
            if slot.clue_placement == "external"
        ),
        key=lambda slot: (
            slot.start.row,
            slot.start.column,
            direction_order[slot.direction],
        ),
    )
    return {
        slot.identifier: number
        for number, slot in enumerate(external_slots, start=1)
    }


def _crossword_grid_annotations(
    crossword: CrosswordDocument,
) -> tuple[
    dict[GridCoordinate, tuple[int, ...]],
    dict[str, int],
    dict[GridCoordinate, set[str]],
]:
    slot_numbers = crossword_external_slot_numbers(crossword)
    numbers: dict[GridCoordinate, list[int]] = defaultdict(list)
    for slot in crossword.slots:
        if slot.identifier not in slot_numbers:
            continue
        coordinate = (slot.start.row - 1, slot.start.column - 1)
        numbers[coordinate].append(slot_numbers[slot.identifier])
    horizontal_connections: set[tuple[GridCoordinate, GridCoordinate]] = set()
    vertical_connections: set[tuple[GridCoordinate, GridCoordinate]] = set()
    external_horizontal_cells: set[GridCoordinate] = set()
    external_vertical_cells: set[GridCoordinate] = set()
    has_inline_legends = any(
        slot.clue_placement == "inline" for slot in crossword.slots
    )
    for slot in crossword.slots:
        coordinates = _slot_coordinates(slot)
        connections = (
            horizontal_connections
            if slot.direction == "horizontal"
            else vertical_connections
        )
        connections.update(pairwise(coordinates))
        if slot.clue_placement == "external":
            external_cells = (
                external_horizontal_cells
                if slot.direction == "horizontal"
                else external_vertical_cells
            )
            external_cells.update(coordinates)

    bars: dict[GridCoordinate, set[str]] = defaultdict(set)
    for row, cell_row in enumerate(crossword.grid.cells):
        for column, cell in enumerate(cell_row):
            if not isinstance(cell, LetterCellRole):
                continue
            coordinate = (row, column)
            right = (row, column + 1)
            if (
                column + 1 < crossword.grid.width
                and isinstance(cell_row[column + 1], LetterCellRole)
                and (coordinate, right) not in horizontal_connections
                and (
                    not has_inline_legends
                    or coordinate in external_horizontal_cells
                    or right in external_horizontal_cells
                )
            ):
                bars[coordinate].add("right")
            below = (row + 1, column)
            if (
                row + 1 < crossword.grid.height
                and isinstance(
                    crossword.grid.cells[row + 1][column],
                    LetterCellRole,
                )
                and (coordinate, below) not in vertical_connections
                and (
                    not has_inline_legends
                    or coordinate in external_vertical_cells
                    or below in external_vertical_cells
                )
            ):
                bars[coordinate].add("bottom")
    return (
        {
            coordinate: tuple(sorted(coordinate_numbers))
            for coordinate, coordinate_numbers in numbers.items()
        },
        slot_numbers,
        bars,
    )


def _crossword_secret_metadata(
    crossword: CrosswordDocument,
) -> tuple[
    frozenset[GridCoordinate],
    dict[GridCoordinate, SecretArrow],
    tuple[SecretPrompt, ...],
]:
    slots_by_identifier = {slot.identifier: slot for slot in crossword.slots}
    coordinates: set[GridCoordinate] = set()
    arrows: dict[GridCoordinate, SecretArrow] = {}
    prompts: list[SecretPrompt] = []
    for secret in crossword.secrets:
        for part in secret.parts:
            if isinstance(part, CrosswordSecretSlotPart):
                coordinates.update(
                    _slot_coordinates(slots_by_identifier[part.slot_identifier])
                )
                continue

            coordinates.update(
                (cell.row - 1, cell.column - 1) for cell in part.cells
            )
            if part.arrows:
                for cell, direction in secret_path_arrows(
                    SecretCells(cells=part.cells, arrows=True)
                ):
                    arrows.setdefault(
                        (cell.row - 1, cell.column - 1),
                        direction,
                    )
        if secret.prompt is not None:
            prompts.append(secret.prompt)
    return (
        frozenset(coordinates),
        arrows,
        tuple(prompts),
    )


def _crossword_grid_from_assignments(
    crossword: CrosswordDocument,
    assignments: dict[str, _Entry],
) -> CrosswordGrid:
    letters: dict[GridCoordinate, str] = {}
    slots_by_legend: dict[GridCoordinate, list[WordSlot]] = (
        defaultdict(list)
    )
    external_slots: list[WordSlot] = []
    numbers, slot_numbers, bars = _crossword_grid_annotations(crossword)
    secret_coordinates, secret_arrows, secret_prompts = (
        _crossword_secret_metadata(crossword)
    )

    for slot in crossword.slots:
        entry = assignments.get(slot.identifier)
        if entry is not None:
            for coordinate, letter in zip(
                _slot_coordinates(slot),
                entry.letters,
            ):
                letters[coordinate] = letter
        if slot.clue_placement == "external":
            external_slots.append(slot)
        else:
            inline_clue_position = slot.inline_clue_position
            assert inline_clue_position is not None
            legend_coordinate = (
                inline_clue_position.row - 1,
                inline_clue_position.column - 1,
            )
            slots_by_legend[legend_coordinate].append(slot)
    direction_order = {"horizontal": 0, "vertical": 1}
    clues = tuple(
        ExternalClue(
            number=slot_numbers[slot.identifier],
            direction=slot.direction,
            text=assignments[slot.identifier].clue,
        )
        for slot in sorted(
            external_slots,
            key=lambda item: slot_numbers[item.identifier],
        )
        if slot.identifier in assignments
    )
    help_words = tuple(
        assignments[slot.identifier].answer
        for slot in crossword.slots
        if slot.in_help and slot.identifier in assignments
    )

    cells = []
    for row_index, crossword_row in enumerate(crossword.grid.cells):
        row = []
        for column_index, crossword_cell in enumerate(crossword_row):
            coordinate = (row_index, column_index)
            if isinstance(crossword_cell, EmptyCellRole):
                row.append(EmptyCell())
            elif isinstance(crossword_cell, HelpCellRole):
                row.append(
                    HelpCell(words=help_words)
                    if help_words
                    else EmptyCell()
                )
            elif isinstance(crossword_cell, LegendCellRole):
                legend_slots = sorted(
                    slots_by_legend[coordinate],
                    key=lambda item: direction_order[item.direction],
                )
                row.append(
                    LegendCell(
                        texts=tuple(
                            assignments[slot.identifier].clue
                            if slot.identifier in assignments
                            else None
                            for slot in legend_slots
                        )
                    )
                )
            else:
                cell_bars = bars.get(coordinate, set())
                coordinate_numbers = numbers.get(coordinate, ())
                common_arguments = {
                    "value": letters.get(coordinate),
                    "number": (
                        coordinate_numbers[0]
                        if len(coordinate_numbers) == 1
                        else None
                    ),
                    "numbers": (
                        coordinate_numbers
                        if len(coordinate_numbers) > 1
                        else ()
                    ),
                    "bars": tuple(
                        bar
                        for bar in ("right", "bottom")
                        if bar in cell_bars
                    ),
                }
                if coordinate in secret_coordinates:
                    row.append(
                        SecretCell(
                            **common_arguments,
                            arrow=secret_arrows.get(coordinate),
                        )
                    )
                else:
                    row.append(
                        LetterCell(
                            **common_arguments,
                        )
                    )
        cells.append(tuple(row))

    return CrosswordGrid(
        format_name="krizovkar",
        kind="grid",
        version=1,
        grid=Grid(
            width=crossword.grid.width,
            height=crossword.grid.height,
            cells=tuple(cells),
        ),
        clues=clues,
        secret_prompts=secret_prompts,
    )


def create_grid_from_crossword(crossword: CrosswordDocument) -> CrosswordGrid:
    """Převede prázdnou, rozpracovanou nebo hotovou křížovku na mřížku."""

    return _crossword_grid_from_assignments(
        crossword,
        _fixed_crossword_assignments(crossword),
    )


def fill_crossword(
    crossword: CrosswordDocument,
    dictionary: CrosswordDictionary,
    *,
    seed: int = DEFAULT_SEED,
    secret: SecretRequirement | None = None,
) -> CrosswordDocument:
    """Doplní ze slovníku všechna prázdná místa křížovky."""

    crossword = _resolve_crossword_secrets(crossword, secret, seed)
    secret_assignments = _secret_assignments(crossword)
    fixed_assignments = _fixed_crossword_assignments(crossword)
    for identifier, assignment in secret_assignments.items():
        fixed = fixed_assignments.get(identifier)
        if fixed is not None:
            if fixed.answer != assignment.answer:
                raise FillingError(
                    f"pevné heslo {fixed.answer!r} ve slotu {identifier!r} "
                    f"neodpovídá tajence {assignment.answer!r}"
                )
            continue
        fixed_assignments[identifier] = assignment
    entries_by_length = _usable_entries(dictionary)
    required_lengths = {
        slot.length
        for slot in crossword.slots
        if slot.identifier not in fixed_assignments
    }
    missing_lengths = sorted(required_lengths - entries_by_length.keys())
    if missing_lengths:
        missing = ", ".join(str(length) for length in missing_lengths)
        raise FillingError(
            f"slovník neobsahuje použitelná hesla délky: {missing}"
        )

    for attempt in range(FILLING_ATTEMPTS):
        attempt_seed = seed + attempt * 1_000_003
        try:
            assignments = _fill_crossword_slots(
                crossword,
                entries_by_length,
                random.Random(attempt_seed),
                fixed_assignments,
            )
            return replace(
                crossword,
                slots=tuple(
                    replace(
                        slot,
                        answer=assignments[slot.identifier].answer,
                        clue=assignments[slot.identifier].clue,
                    )
                    for slot in crossword.slots
                )
            )
        except _SearchFailed:
            continue

    raise FillingError(
        "nepodařilo se vyplnit všechny sloty platnými křížícími se hesly"
    )

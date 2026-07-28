"""Deterministické plnění husté švédské křížovkové mřížky."""

from __future__ import annotations

import random
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace

from krizovkar.alphabet import SUPPORTED_SINGLE_LETTERS, split_answer_letters
from krizovkar.dictionary import CrosswordDictionary
from krizovkar.layout import (
    MAX_SEGMENT_LENGTH,
    MIN_SEGMENT_LENGTH,
    LayoutError,
    SwedishLayout,
    create_dense_swedish_layout,
    create_dense_swedish_layout_candidates,
)
from krizovkar.model import (
    Coordinate,
    CrosswordGrid,
    CrosswordTemplate,
    DEFAULT_SECRET_LEGEND,
    DEFAULT_SECRET_PART_LEGEND,
    EmptyCell,
    ExternalClue,
    Grid,
    LegendCell,
    LetterCell,
    SecretCell,
    SecretPrompt,
    TemplateEmptyCell,
    TemplateGrid,
    TemplateLegendCell,
    TemplateLetterCell,
    TemplateSecret,
    TemplateSecretPart,
    WordSlot,
)


DEFAULT_GRID_WIDTH = 15
DEFAULT_GRID_HEIGHT = 10
DEFAULT_SEED = 0
MAX_CLUE_LENGTH = 48
GENERATION_ATTEMPTS = 4
MAX_SEARCH_NODES = 250_000
PREFERRED_SECRET_PART_LENGTH = 4

GridCoordinate = tuple[int, int]


class GenerationError(RuntimeError):
    """Ze zadaného slovníku a rozměru se nepodařilo vytvořit mřížku."""


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


def generate_swedish_template(
    *,
    width: int = DEFAULT_GRID_WIDTH,
    height: int = DEFAULT_GRID_HEIGHT,
    seed: int = DEFAULT_SEED,
    secret: SecretRequirement | None = None,
) -> CrosswordTemplate:
    """Vytvoří nevyplněnou hustou švédskou šablonu."""

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


def _swedish_template_from_layout(layout: SwedishLayout) -> CrosswordTemplate:

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


def _select_slots_for_total_length(
    slots: list[WordSlot],
    total_length: int,
) -> tuple[WordSlot, ...] | None:
    minimum_length = min(slot.length for slot in slots)
    maximum_parts = min(len(slots), total_length // minimum_length)
    for part_count in range(1, maximum_parts + 1):
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

        if search(0, total_length):
            return tuple(selected)
    return None


def place_secret_in_template(
    template: CrosswordTemplate,
    requirement: SecretRequirement,
    *,
    seed: int = DEFAULT_SEED,
) -> CrosswordTemplate:
    """Rezervuje vhodné nepřekrývající se sloty pro jednu tajenku."""

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
        TemplateSecretPart(
            slot_identifier=slot.identifier,
            word_count=(word_counts[index] if word_counts else None),
        )
        for index, slot in enumerate(selected)
    )
    return replace(
        template,
        secrets=(
            TemplateSecret(
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


def _resolve_template_secrets(
    template: CrosswordTemplate,
    requirement: SecretRequirement | None,
    seed: int,
) -> CrosswordTemplate:
    unknown_indices = tuple(
        index
        for index, secret in enumerate(template.secrets)
        if not secret.words
    )
    if requirement is None:
        if unknown_indices:
            raise GenerationError(
                "šablona rezervuje tajenku bez známého znění; "
                "při plnění je nutné zadat konkrétní tajenku"
            )
        return template

    _validate_secret_requirement(requirement)
    if not requirement.words:
        raise GenerationError(
            "při plnění je nutné zadat konkrétní slova tajenky"
        )
    if not template.secrets:
        return place_secret_in_template(template, requirement, seed=seed)
    if not unknown_indices:
        raise GenerationError("šablona už obsahuje konkrétní tajenku")
    if len(unknown_indices) > 1:
        raise GenerationError(
            "šablona obsahuje více neznámých tajenek; "
            "jedním zadáním je nelze jednoznačně doplnit"
        )

    secret_index = unknown_indices[0]
    reserved = template.secrets[secret_index]
    slots_by_identifier = {slot.identifier: slot for slot in template.slots}
    lengths = tuple(
        slots_by_identifier[part.slot_identifier].length
        for part in reserved.parts
    )
    if requirement.part_word_counts:
        counts = requirement.part_word_counts
        if _part_lengths_from_word_counts(requirement.words, counts) != lengths:
            raise GenerationError(
                "pevné rozdělení tajenky neodpovídá délkám "
                "připravených slotů"
            )
    else:
        counts = _word_counts_for_exact_lengths(requirement.words, lengths)
        if counts is None:
            raise GenerationError(
                "tajenku nelze rozdělit na hranicích slov podle délek "
                "připravených slotů"
            )

    secrets = list(template.secrets)
    secrets[secret_index] = TemplateSecret(
        parts=tuple(
            TemplateSecretPart(
                slot_identifier=part.slot_identifier,
                word_count=counts[index],
            )
            for index, part in enumerate(reserved.parts)
        ),
        words=requirement.words,
        prompt=requirement.prompt or reserved.prompt,
    )
    return replace(template, secrets=tuple(secrets))


def _secret_assignments(
    template: CrosswordTemplate,
) -> tuple[dict[str, _Entry], frozenset[str], tuple[SecretPrompt, ...]]:
    assignments = {}
    secret_slot_identifiers = set()
    prompts = []
    for secret in template.secrets:
        word_offset = 0
        multipart = len(secret.parts) > 1
        for part_index, part in enumerate(secret.parts):
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
            secret_slot_identifiers.add(part.slot_identifier)
        if secret.prompt is not None:
            prompts.append(secret.prompt)
    return assignments, frozenset(secret_slot_identifiers), tuple(prompts)


def _fill_template_slots(
    template: CrosswordTemplate,
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
        slot.identifier: _slot_coordinates(slot) for slot in template.slots
    }
    assigned: dict[str, _Entry] = dict(fixed_assignments or {})
    letters: dict[GridCoordinate, str] = {}
    used_answers: set[str] = {
        entry.answer for entry in assigned.values()
    }
    search_nodes = 0

    slots_by_identifier = {slot.identifier: slot for slot in template.slots}
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
    secret_slot_identifiers: frozenset[str] = frozenset(),
    secret_prompts: tuple[SecretPrompt, ...] = (),
) -> CrosswordGrid:
    letters: dict[GridCoordinate, str] = {}
    slots_by_legend: dict[GridCoordinate, list[tuple[WordSlot, _Entry]]] = (
        defaultdict(list)
    )
    external_slots = []
    bars: dict[GridCoordinate, set[str]] = defaultdict(set)
    secret_coordinates = {
        coordinate
        for slot in template.slots
        if slot.identifier in secret_slot_identifiers
        for coordinate in _slot_coordinates(slot)
    }

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
                cell_type = (
                    SecretCell
                    if coordinate in secret_coordinates
                    else LetterCell
                )
                row.append(
                    cell_type(
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
        secret_prompts=secret_prompts,
    )


def fill_crossword_template(
    template: CrosswordTemplate,
    dictionary: CrosswordDictionary,
    *,
    seed: int = DEFAULT_SEED,
    secret: SecretRequirement | None = None,
) -> CrosswordGrid:
    """Vyplní všechny sloty šablony různými hesly ze slovníku."""

    template = _resolve_template_secrets(template, secret, seed)
    fixed_assignments, secret_slot_identifiers, secret_prompts = (
        _secret_assignments(template)
    )
    entries_by_length = _usable_entries(dictionary)
    required_lengths = {
        slot.length
        for slot in template.slots
        if slot.identifier not in secret_slot_identifiers
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
            assignments = _fill_template_slots(
                template,
                entries_by_length,
                random.Random(attempt_seed),
                fixed_assignments,
            )
            return _filled_template_grid(
                template,
                assignments,
                secret_slot_identifiers,
                secret_prompts,
            )
        except _SearchFailed:
            continue

    raise GenerationError(
        "nepodařilo se vyplnit všechny sloty platnými křížícími se hesly"
    )


def generate_swedish_grid(
    dictionary: CrosswordDictionary,
    *,
    width: int = DEFAULT_GRID_WIDTH,
    height: int = DEFAULT_GRID_HEIGHT,
    seed: int = DEFAULT_SEED,
    secret: SecretRequirement | None = None,
) -> CrosswordGrid:
    """Vyplní hustou švédskou mřížku platnými křížícími se hesly."""

    template = generate_swedish_template(
        width=width,
        height=height,
        seed=seed,
        secret=secret,
    )
    return fill_crossword_template(
        template,
        dictionary,
        seed=seed,
    )

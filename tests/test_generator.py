"""Testy generování šablon a plnění křížovek."""

from __future__ import annotations

import tempfile
import unittest
from itertools import product
from pathlib import Path

from krizovkar.dictionary import CrosswordDictionary, DictionaryEntry
from krizovkar.generator import (
    FillingError,
    GenerationError,
    SecretRequirement,
    create_grid_from_crossword,
    create_template_from_specification,
    fill_crossword,
    generate_numbered_template,
    generate_swedish_template,
    normalize_secret_text,
    place_secret_in_template,
)
from krizovkar.layout import create_dense_swedish_layout
from krizovkar.model import (
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
    GridDimensions,
    HelpCell,
    HelpCellRole,
    LegendCell,
    LegendCellRole,
    LetterCell,
    LetterCellRole,
    SecretCell,
    SecretPrompt,
    WordPlacement,
    WordSlot,
    cell_numbers,
    load_crossword_document,
    load_crossword_grid,
    load_crossword_specification,
    write_crossword_grid,
)
from krizovkar.validation import check_crossword_grid


def _complete_dictionary(*lengths: int) -> CrosswordDictionary:
    entries = []
    for length in lengths:
        for letters in product("ABCD", repeat=length):
            answer = "".join(letters)
            entries.append(
                DictionaryEntry(answer=answer, clues=(f"Legenda {answer}",))
            )
    return CrosswordDictionary(entries=tuple(entries))


def _filled_swedish_grid(
    dictionary: CrosswordDictionary,
    *,
    width: int,
    height: int,
    seed: int = 0,
    secret: SecretRequirement | None = None,
) -> CrosswordGrid:
    template = generate_swedish_template(
        width=width,
        height=height,
        seed=seed,
        secret=secret,
    )
    return create_grid_from_crossword(
        fill_crossword(template, dictionary, seed=seed)
    )


def _filled_numbered_grid(
    dictionary: CrosswordDictionary,
    *,
    width: int,
    height: int,
    seed: int = 0,
    secret: SecretRequirement | None = None,
) -> CrosswordGrid:
    template = generate_numbered_template(
        width=width,
        height=height,
        seed=seed,
        secret=secret,
    )
    return create_grid_from_crossword(
        fill_crossword(template, dictionary, seed=seed)
    )


TEST_DICTIONARY = _complete_dictionary(3, 4)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECIFICATION_PLACED_WORDS_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-placed-words.yaml"
)
SPECIFICATION_SECRETS_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-secrets.yaml"
)
SPECIFICATION_MULTIPART_SECRETS_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-multipart-secrets.yaml"
)
SPECIFICATION_SECRET_PROMPT_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-secret-prompt.yaml"
)
CROSSWORD_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "crossword-minimal.yaml"


class TemplateGenerationAndFillingTest(unittest.TestCase):
    def test_creates_swedish_template_from_specification(self) -> None:
        specification = load_crossword_specification(
            SPECIFICATION_PLACED_WORDS_EXAMPLE
        )

        template = create_template_from_specification(specification)

        self.assertEqual(("h1", "v1", "v2"), tuple(
            slot.identifier for slot in template.slots
        ))
        self.assertEqual(
            ("LABE", "LES", "EMU"),
            tuple(slot.answer for slot in template.slots),
        )
        self.assertEqual(
            ("2,1", "1,2", "1,5"),
            tuple(
                f"{slot.legend_position.row},{slot.legend_position.column}"
                for slot in template.slots
                if slot.legend_position is not None
            ),
        )
        self.assertEqual("crossword", template.kind)
        self.assertIsInstance(template, CrosswordDocument)
        self.assertIsInstance(template.grid.cells[0][0], HelpCellRole)

        grid = create_grid_from_crossword(template)
        assert grid.grid.cells is not None
        self.assertEqual(
            ("L", "A", "B", "E"),
            tuple(grid.grid.cells[1][column].value for column in range(1, 5)),
        )
        help_cell = grid.grid.cells[0][0]
        self.assertIsInstance(help_cell, HelpCell)
        assert isinstance(help_cell, HelpCell)
        self.assertEqual(("LES", "EMU"), help_cell.words)

    def test_preserves_specification_order_in_help(self) -> None:
        specification = CrosswordSpecification(
            format_name="krizovkar",
            kind="specification",
            version=1,
            grid=GridDimensions(width=4, height=4),
            words=(
                WordPlacement(
                    answer="LES",
                    start=Coordinate(row=1, column=1),
                    direction="vertical",
                    legend="Porost stromů",
                    in_help=True,
                ),
                WordPlacement(
                    answer="EMU",
                    start=Coordinate(row=4, column=2),
                    direction="horizontal",
                    legend="Australský nelétavý pták",
                    in_help=True,
                ),
            ),
        )

        template = create_template_from_specification(
            specification,
            layout="numbered",
        )
        grid = create_grid_from_crossword(template)

        self.assertEqual(
            ("v1", "h1"),
            tuple(slot.identifier for slot in template.slots),
        )
        assert grid.grid.cells is not None
        help_cell = grid.grid.cells[0][1]
        self.assertIsInstance(help_cell, HelpCell)
        assert isinstance(help_cell, HelpCell)
        self.assertEqual(("LES", "EMU"), help_cell.words)

    def test_creates_numbered_template_with_both_secret_forms(self) -> None:
        specification = load_crossword_specification(
            SPECIFICATION_SECRETS_EXAMPLE
        )

        template = create_template_from_specification(
            specification,
            layout="numbered",
        )
        grid = create_grid_from_crossword(template)

        self.assertTrue(
            all(slot.legend_position is None for slot in template.slots)
        )
        self.assertIsInstance(
            template.secrets[0].parts[0],
            CrosswordSecretCellsPart,
        )
        self.assertEqual(("KŘÍŽOVKÁŘ",), template.secrets[1].words)
        assert grid.grid.cells is not None
        self.assertEqual("right", grid.grid.cells[1][1].arrow)
        self.assertEqual("down", grid.grid.cells[1][4].arrow)
        self.assertEqual(
            "KŘÍŽOVKÁŘ",
            "".join(
                grid.grid.cells[4][column].value
                for column in range(1, 10)
            ),
        )
        self.assertEqual(4, len(grid.clues))

    def test_swedish_specification_requires_room_for_legend(self) -> None:
        specification = load_crossword_specification(
            SPECIFICATION_SECRET_PROMPT_EXAMPLE
        )

        with self.assertRaisesRegex(
            GenerationError,
            "nevejde vepsaná legenda",
        ):
            create_template_from_specification(specification)

    def test_separates_adjacent_letters_not_joined_by_a_slot(self) -> None:
        specification = load_crossword_specification(
            SPECIFICATION_MULTIPART_SECRETS_EXAMPLE
        )
        template = create_template_from_specification(
            specification,
            layout="numbered",
        )

        grid = create_grid_from_crossword(template)

        assert grid.grid.cells is not None
        self.assertTrue(
            all(
                "bottom" in grid.grid.cells[4][column].bars
                for column in range(5)
            )
        )

    def test_fills_unfixed_slots_around_fixed_answer(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=3,
                height=3,
                cells=(
                    (
                        EmptyCellRole(),
                        LetterCellRole(),
                        EmptyCellRole(),
                    ),
                    (
                        LetterCellRole(),
                        LetterCellRole(),
                        LetterCellRole(),
                    ),
                    (
                        EmptyCellRole(),
                        LetterCellRole(),
                        EmptyCellRole(),
                    ),
                ),
            ),
            slots=(
                WordSlot(
                    identifier="h1",
                    start=Coordinate(row=2, column=1),
                    direction="horizontal",
                    length=3,
                    answer="ABC",
                    clue="Pevné heslo",
                ),
                WordSlot(
                    identifier="v1",
                    start=Coordinate(row=1, column=2),
                    direction="vertical",
                    length=3,
                ),
            ),
        )
        dictionary = CrosswordDictionary(
            entries=(
                DictionaryEntry(answer="XBX", clues=("Doplněné heslo",)),
            )
        )

        filled = fill_crossword(crossword, dictionary)

        self.assertEqual("crossword", filled.kind)
        self.assertEqual(
            ("ABC", "XBX"),
            tuple(slot.answer for slot in filled.slots),
        )
        self.assertEqual(
            ("Pevné heslo", "Doplněné heslo"),
            tuple(slot.clue for slot in filled.slots),
        )
        grid = create_grid_from_crossword(filled)
        assert grid.grid.cells is not None
        self.assertEqual(
            ("A", "B", "C"),
            tuple(cell.value for cell in grid.grid.cells[1]),
        )
        self.assertEqual(
            ("X", "B", "X"),
            tuple(grid.grid.cells[row][1].value for row in range(3)),
        )

    def test_normalizes_secret_words_and_discards_punctuation(self) -> None:
        self.assertEqual(
            ("KOMU", "SE", "NELENÍ", "TOMU", "SE", "ZELENÍ"),
            normalize_secret_text(
                'Komu se nelení, tomu se „Zelení!“'
            ),
        )

    def test_secret_normalization_rejects_nonletter_content(self) -> None:
        with self.assertRaisesRegex(GenerationError, "nepodporovaný znak '1'"):
            normalize_secret_text("TAJENKA 1")

    def test_places_secret_by_total_and_part_lengths(self) -> None:
        template = generate_swedish_template(width=5, height=5)

        single = place_secret_in_template(
            template,
            SecretRequirement(total_length=4),
            seed=7,
        )
        multipart = place_secret_in_template(
            template,
            SecretRequirement(part_lengths=(4, 4)),
            seed=7,
        )

        self.assertEqual(1, len(single.secrets[0].parts))
        self.assertEqual(2, len(multipart.secrets[0].parts))
        slots = {slot.identifier: slot for slot in template.slots}
        self.assertEqual(
            (4, 4),
            tuple(
                slots[part.slot_identifier].length
                for part in multipart.secrets[0].parts
            ),
        )

    def test_secret_changes_dense_layout_to_include_required_lengths(self) -> None:
        single = generate_swedish_template(
            secret=SecretRequirement(words=("ZELENÍ",)),
        )
        multipart = generate_swedish_template(
            secret=SecretRequirement(part_lengths=(5, 6)),
        )

        single_slots = {slot.identifier: slot for slot in single.slots}
        multipart_slots = {slot.identifier: slot for slot in multipart.slots}
        self.assertEqual(
            (6,),
            tuple(
                single_slots[part.slot_identifier].length
                for part in single.secrets[0].parts
            ),
        )
        self.assertEqual(
            (5, 6),
            tuple(
                multipart_slots[part.slot_identifier].length
                for part in multipart.secrets[0].parts
            ),
        )

    def test_dense_template_rejects_secret_part_shorter_than_words(self) -> None:
        with self.assertRaisesRegex(GenerationError, "nelze rozvrhnout tajenku"):
            generate_swedish_template(
                secret=SecretRequirement(words=("SE",)),
            )

    def test_places_known_secret_with_automatic_word_split(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=6,
                height=1,
                cells=((LetterCellRole(),) * 6,),
            ),
            slots=(
                WordSlot(
                    identifier="h1",
                    start=Coordinate(row=1, column=1),
                    direction="horizontal",
                    length=4,
                ),
                WordSlot(
                    identifier="h2",
                    start=Coordinate(row=1, column=5),
                    direction="horizontal",
                    length=2,
                ),
            ),
        )

        prepared = place_secret_in_template(
            crossword,
            SecretRequirement(words=("KOMU", "SE")),
        )

        self.assertEqual(
            (1, 1),
            tuple(part.word_count for part in prepared.secrets[0].parts),
        )

    def test_fills_known_secret_and_propagates_prompt(self) -> None:
        prompt = SecretPrompt(text="Dokončete rčení")
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=6,
                height=1,
                cells=((LetterCellRole(),) * 6,),
            ),
            slots=(
                WordSlot(
                    identifier="h1",
                    start=Coordinate(row=1, column=1),
                    direction="horizontal",
                    length=6,
                ),
            ),
            secrets=(
                CrosswordSecret(
                    words=("ZELENÍ",),
                    parts=(
                        CrosswordSecretSlotPart(
                            slot_identifier="h1",
                            word_count=1,
                        ),
                    ),
                    prompt=prompt,
                ),
            ),
        )

        filled = fill_crossword(crossword, TEST_DICTIONARY)

        self.assertEqual("ZELENÍ", filled.slots[0].answer)
        self.assertEqual("Tajenka", filled.slots[0].clue)
        self.assertEqual(prompt, filled.secrets[0].prompt)
        grid = create_grid_from_crossword(filled)
        assert grid.grid.cells is not None
        self.assertEqual(
            ("Z", "E", "L", "E", "N", "Í"),
            tuple(cell.value for cell in grid.grid.cells[0]),
        )
        self.assertTrue(
            all(isinstance(cell, SecretCell) for cell in grid.grid.cells[0])
        )
        self.assertEqual((prompt,), grid.secret_prompts)
        self.assertEqual("Tajenka", grid.clues[0].text)

    def test_fills_secret_into_reserved_slots_at_word_seams(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=6,
                height=1,
                cells=((LetterCellRole(),) * 6,),
            ),
            slots=(
                WordSlot("h1", Coordinate(1, 1), "horizontal", 4),
                WordSlot("h2", Coordinate(1, 5), "horizontal", 2),
            ),
            secrets=(
                CrosswordSecret(
                    parts=(
                        CrosswordSecretSlotPart("h1"),
                        CrosswordSecretSlotPart("h2"),
                    )
                ),
            ),
        )

        filled = fill_crossword(
            crossword,
            TEST_DICTIONARY,
            secret=SecretRequirement(words=("KOMU", "SE")),
        )

        self.assertEqual(
            ("KOMU", "SE"),
            tuple(slot.answer for slot in filled.slots),
        )
        self.assertEqual(
            ("1. část tajenky", "2. část tajenky"),
            tuple(slot.clue for slot in filled.slots),
        )
        grid = create_grid_from_crossword(filled)
        assert grid.grid.cells is not None
        self.assertEqual(
            "KOMUSE",
            "".join(cell.value for cell in grid.grid.cells[0]),
        )
        self.assertEqual(
            ("1. část tajenky", "2. část tajenky"),
            tuple(clue.text for clue in grid.clues),
        )

    def test_never_splits_secret_inside_word(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=6,
                height=1,
                cells=((LetterCellRole(),) * 6,),
            ),
            slots=(
                WordSlot("h1", Coordinate(1, 1), "horizontal", 3),
                WordSlot("h2", Coordinate(1, 4), "horizontal", 3),
            ),
            secrets=(
                CrosswordSecret(
                    parts=(
                        CrosswordSecretSlotPart("h1"),
                        CrosswordSecretSlotPart("h2"),
                    )
                ),
            ),
        )

        with self.assertRaisesRegex(FillingError, "na hranicích slov"):
            fill_crossword(
                crossword,
                TEST_DICTIONARY,
                secret=SecretRequirement(words=("ZELENÍ",)),
            )

    def test_auto_places_secret_when_crossword_has_no_reservation(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=6,
                height=1,
                cells=((LetterCellRole(),) * 6,),
            ),
            slots=(
                WordSlot("h1", Coordinate(1, 1), "horizontal", 6),
            ),
        )

        filled = fill_crossword(
            crossword,
            TEST_DICTIONARY,
            secret=SecretRequirement(words=("ZELENÍ",)),
        )

        self.assertEqual("ZELENÍ", filled.slots[0].answer)
        self.assertEqual(("ZELENÍ",), filled.secrets[0].words)
        grid = create_grid_from_crossword(filled)
        assert grid.grid.cells is not None
        self.assertTrue(
            all(isinstance(cell, SecretCell) for cell in grid.grid.cells[0])
        )

    def test_fills_generated_template_deterministically(self) -> None:
        template = generate_swedish_template(width=5, height=5)

        first = fill_crossword(template, TEST_DICTIONARY, seed=42)
        second = fill_crossword(template, TEST_DICTIONARY, seed=42)

        self.assertEqual(first, second)
        self.assertEqual("crossword", first.kind)
        self.assertEqual(5, first.grid.width)
        self.assertEqual(5, first.grid.height)
        self.assertTrue(
            all(
                slot.answer is not None and slot.clue is not None
                for slot in first.slots
            )
        )
        grid = create_grid_from_crossword(first)
        assert grid.grid.cells is not None
        cells = tuple(cell for row in grid.grid.cells for cell in row)
        self.assertEqual(16, sum(isinstance(cell, LetterCell) for cell in cells))
        self.assertEqual(8, sum(isinstance(cell, LegendCell) for cell in cells))
        self.assertEqual(1, sum(isinstance(cell, EmptyCell) for cell in cells))
        self.assertFalse(grid.clues)
        self.assertFalse(check_crossword_grid(grid).warnings)

    def test_filling_complete_crossword_keeps_it_unchanged(self) -> None:
        crossword = load_crossword_document(CROSSWORD_MINIMAL_EXAMPLE)

        filled = fill_crossword(crossword, CrosswordDictionary(entries=()))

        self.assertEqual(crossword, filled)
        self.assertEqual("crossword", filled.kind)

    def test_pipeline_creates_complete_grid_with_fixed_secret(self) -> None:
        prompt = SecretPrompt(text="Doplňte tajenku", placement="below")

        crossword = _filled_swedish_grid(
            TEST_DICTIONARY,
            width=5,
            height=5,
            seed=42,
            secret=SecretRequirement(
                words=("ABCD",),
                part_word_counts=(1,),
                prompt=prompt,
            ),
        )

        assert crossword.grid.cells is not None
        secret_cells = tuple(
            cell
            for row in crossword.grid.cells
            for cell in row
            if isinstance(cell, SecretCell)
        )
        self.assertEqual(4, len(secret_cells))
        self.assertEqual("ABCD", "".join(cell.value for cell in secret_cells))
        self.assertEqual((prompt,), crossword.secret_prompts)
        self.assertFalse(check_crossword_grid(crossword).warnings)

    def test_fills_external_slots_with_numbers_clues_and_bar(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=6,
                height=1,
                cells=((LetterCellRole(),) * 6,),
            ),
            slots=(
                WordSlot(
                    identifier="h1",
                    start=Coordinate(row=1, column=1),
                    direction="horizontal",
                    length=3,
                ),
                WordSlot(
                    identifier="h2",
                    start=Coordinate(row=1, column=4),
                    direction="horizontal",
                    length=3,
                ),
            ),
        )

        filled = fill_crossword(crossword, TEST_DICTIONARY, seed=3)

        self.assertTrue(all(slot.answer is not None for slot in filled.slots))
        grid = create_grid_from_crossword(filled)
        assert grid.grid.cells is not None
        row = grid.grid.cells[0]
        self.assertEqual(1, row[0].number)
        self.assertEqual(("right",), row[2].bars)
        self.assertEqual(2, row[3].number)
        self.assertEqual((1, 2), tuple(clue.number for clue in grid.clues))
        self.assertEqual(
            ("horizontal", "horizontal"),
            tuple(clue.direction for clue in grid.clues),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "external.yaml"
            write_crossword_grid(grid, output)
            self.assertEqual(grid, load_crossword_grid(output))

    def test_shared_external_start_has_two_directional_numbers(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=3,
                height=1,
                cells=((LetterCellRole(),) * 3,),
            ),
            slots=(
                WordSlot(
                    identifier="v1",
                    start=Coordinate(row=1, column=1),
                    direction="vertical",
                    length=1,
                    answer="A",
                    clue="Svislá legenda",
                ),
                WordSlot(
                    identifier="h1",
                    start=Coordinate(row=1, column=1),
                    direction="horizontal",
                    length=3,
                    answer="ABC",
                    clue="Vodorovná legenda",
                ),
            ),
        )

        grid = create_grid_from_crossword(crossword)

        assert grid.grid.cells is not None
        start = grid.grid.cells[0][0]
        self.assertIsInstance(start, LetterCell)
        assert isinstance(start, LetterCell)
        self.assertIsNone(start.number)
        self.assertEqual((1, 2), start.numbers)
        self.assertEqual((1, 2), cell_numbers(start))
        self.assertEqual((1, 2), tuple(clue.number for clue in grid.clues))
        self.assertEqual(
            ("horizontal", "vertical"),
            tuple(clue.direction for clue in grid.clues),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sdileny-zacatek.yaml"
            write_crossword_grid(grid, output)
            self.assertEqual(grid, load_crossword_grid(output))

    def test_fills_double_internal_legend_in_direction_order(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=2,
                height=2,
                cells=(
                    (LegendCellRole(), LetterCellRole()),
                    (LetterCellRole(), EmptyCellRole()),
                ),
            ),
            slots=(
                WordSlot(
                    identifier="h1",
                    start=Coordinate(row=1, column=2),
                    direction="horizontal",
                    length=1,
                    legend_position=Coordinate(row=1, column=1),
                ),
                WordSlot(
                    identifier="v1",
                    start=Coordinate(row=2, column=1),
                    direction="vertical",
                    length=1,
                    legend_position=Coordinate(row=1, column=1),
                ),
            ),
        )
        dictionary = CrosswordDictionary(
            entries=(
                DictionaryEntry(answer="A", clues=("První",)),
                DictionaryEntry(answer="B", clues=("Druhá",)),
            )
        )

        filled = fill_crossword(crossword, dictionary, seed=1)

        self.assertTrue(all(slot.clue is not None for slot in filled.slots))
        grid = create_grid_from_crossword(filled)
        assert grid.grid.cells is not None
        legend = grid.grid.cells[0][0]
        self.assertIsInstance(legend, LegendCell)
        self.assertEqual(2, len(legend.texts))
        self.assertFalse(legend.arrows)

    def test_crossword_fill_rejects_missing_length(self) -> None:
        template = generate_swedish_template(width=5, height=5)
        dictionary = _complete_dictionary(3)

        with self.assertRaisesRegex(FillingError, "délky: 4"):
            fill_crossword(template, dictionary)

    def test_crossword_fill_rejects_unsatisfiable_crossing(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=2,
                height=2,
                cells=(
                    (LetterCellRole(), LetterCellRole()),
                    (LetterCellRole(), EmptyCellRole()),
                ),
            ),
            slots=(
                WordSlot(
                    identifier="h1",
                    start=Coordinate(row=1, column=1),
                    direction="horizontal",
                    length=2,
                ),
                WordSlot(
                    identifier="v1",
                    start=Coordinate(row=1, column=1),
                    direction="vertical",
                    length=2,
                ),
            ),
        )
        dictionary = CrosswordDictionary(
            entries=(
                DictionaryEntry(answer="AB", clues=("První",)),
                DictionaryEntry(answer="CD", clues=("Druhá",)),
            )
        )

        with self.assertRaisesRegex(FillingError, "nepodařilo se vyplnit"):
            fill_crossword(crossword, dictionary)

    def test_generates_dense_template_without_dictionary(self) -> None:
        first = generate_swedish_template(width=9, height=9)
        second = generate_swedish_template(width=9, height=9)

        self.assertEqual(first, second)
        self.assertEqual("crossword", first.kind)
        self.assertEqual(9, first.grid.width)
        self.assertEqual(9, first.grid.height)
        cells = tuple(cell for row in first.grid.cells for cell in row)
        self.assertEqual(
            49,
            sum(isinstance(cell, LetterCellRole) for cell in cells),
        )
        self.assertEqual(
            28,
            sum(isinstance(cell, LegendCellRole) for cell in cells),
        )
        self.assertEqual(
            4,
            sum(isinstance(cell, EmptyCellRole) for cell in cells),
        )
        self.assertEqual(28, len(first.slots))
        self.assertEqual(
            tuple(f"h{number}" for number in range(1, 15)),
            tuple(
                slot.identifier
                for slot in first.slots
                if slot.direction == "horizontal"
            ),
        )
        self.assertEqual(
            tuple(f"v{number}" for number in range(1, 15)),
            tuple(
                slot.identifier
                for slot in first.slots
                if slot.direction == "vertical"
            ),
        )
        first_slot = first.slots[0]
        self.assertEqual((2, 2), (first_slot.start.row, first_slot.start.column))
        self.assertEqual(4, first_slot.length)
        assert first_slot.legend_position is not None
        self.assertEqual(
            (2, 1),
            (first_slot.legend_position.row, first_slot.legend_position.column),
        )

    def test_generates_numbered_template_without_dictionary(self) -> None:
        first = generate_numbered_template(width=7, height=7)
        second = generate_numbered_template(width=7, height=7)

        self.assertEqual(first, second)
        self.assertEqual("crossword", first.kind)
        self.assertEqual(7, first.grid.width)
        self.assertEqual(7, first.grid.height)
        self.assertTrue(
            all(
                isinstance(cell, LetterCellRole)
                for row in first.grid.cells
                for cell in row
            )
        )
        self.assertEqual(28, len(first.slots))
        self.assertTrue(
            all(slot.legend_position is None for slot in first.slots)
        )
        self.assertEqual(
            (
                ("h1", 1, 1, 4),
                ("h2", 1, 5, 3),
                ("h3", 2, 1, 4),
            ),
            tuple(
                (
                    slot.identifier,
                    slot.start.row,
                    slot.start.column,
                    slot.length,
                )
                for slot in first.slots[:3]
            ),
        )

    def test_creates_unfilled_grid_from_swedish_template(self) -> None:
        template = generate_swedish_template(width=5, height=5)

        grid = create_grid_from_crossword(template)

        self.assertEqual("grid", grid.kind)
        self.assertEqual(5, grid.grid.width)
        self.assertEqual(5, grid.grid.height)
        assert grid.grid.cells is not None
        for template_row, grid_row in zip(
            template.grid.cells,
            grid.grid.cells,
        ):
            for template_cell, grid_cell in zip(template_row, grid_row):
                if isinstance(template_cell, LetterCellRole):
                    self.assertIsInstance(grid_cell, LetterCell)
                    self.assertIsNone(grid_cell.value)
                elif isinstance(template_cell, LegendCellRole):
                    self.assertIsInstance(grid_cell, LegendCell)
                    self.assertTrue(grid_cell.texts)
                    self.assertTrue(
                        all(text is None for text in grid_cell.texts)
                    )
                else:
                    self.assertIsInstance(grid_cell, EmptyCell)
        self.assertEqual(
            ("grid.unfinished",),
            tuple(issue.code for issue in check_crossword_grid(grid).warnings),
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "unfilled.yaml"
            write_crossword_grid(grid, output)
            self.assertEqual(grid, load_crossword_grid(output))
            self.assertIn("- null", output.read_text(encoding="utf-8"))

    def test_unfilled_numbered_grid_keeps_numbers_and_bars(self) -> None:
        template = generate_numbered_template(width=7, height=7)

        grid = create_grid_from_crossword(template)

        assert grid.grid.cells is not None
        cells = tuple(cell for row in grid.grid.cells for cell in row)
        self.assertTrue(all(isinstance(cell, LetterCell) for cell in cells))
        self.assertTrue(all(cell.value is None for cell in cells))
        self.assertEqual(
            tuple(range(1, 29)),
            tuple(
                number
                for cell in cells
                for number in cell_numbers(cell)
            ),
        )
        self.assertEqual(14, sum(len(cell.bars) for cell in cells))
        self.assertFalse(grid.clues)

    def test_unfilled_grid_keeps_secret_cells_and_prompt(self) -> None:
        prompt = SecretPrompt(text="Doplňte tajenku")
        template = generate_numbered_template(
            width=7,
            height=7,
            secret=SecretRequirement(total_length=4, prompt=prompt),
        )

        grid = create_grid_from_crossword(template)

        assert grid.grid.cells is not None
        secret_cells = tuple(
            cell
            for row in grid.grid.cells
            for cell in row
            if isinstance(cell, SecretCell)
        )
        self.assertEqual(4, len(secret_cells))
        self.assertTrue(all(cell.value is None for cell in secret_cells))
        self.assertEqual((prompt,), grid.secret_prompts)

    def test_unfilled_grid_keeps_double_legend_sections(self) -> None:
        crossword = CrosswordDocument(
            format_name="krizovkar",
            kind="crossword",
            version=1,
            grid=CrosswordLayout(
                width=2,
                height=2,
                cells=(
                    (LegendCellRole(), LetterCellRole()),
                    (LetterCellRole(), EmptyCellRole()),
                ),
            ),
            slots=(
                WordSlot(
                    identifier="h1",
                    start=Coordinate(row=1, column=2),
                    direction="horizontal",
                    length=1,
                    legend_position=Coordinate(row=1, column=1),
                ),
                WordSlot(
                    identifier="v1",
                    start=Coordinate(row=2, column=1),
                    direction="vertical",
                    length=1,
                    legend_position=Coordinate(row=1, column=1),
                ),
            ),
        )

        grid = create_grid_from_crossword(crossword)

        assert grid.grid.cells is not None
        legend = grid.grid.cells[0][0]
        self.assertIsInstance(legend, LegendCell)
        self.assertEqual((None, None), legend.texts)

    def test_crossword_rejects_too_small_grid(self) -> None:
        with self.assertRaisesRegex(GenerationError, "nelze rozdělit"):
            generate_swedish_template(width=3, height=9)

    def test_swedish_pipeline_is_deterministic(self) -> None:
        first = _filled_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=42)
        second = _filled_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=42)
        composed = create_grid_from_crossword(
            fill_crossword(
                generate_swedish_template(width=9, height=9),
                TEST_DICTIONARY,
                seed=42,
            )
        )

        self.assertEqual(first, second)
        self.assertEqual(first, composed)
        self.assertEqual(9, first.grid.width)
        self.assertEqual(9, first.grid.height)
        assert first.grid.cells is not None
        self.assertEqual(9, len(first.grid.cells))
        self.assertTrue(all(len(row) == 9 for row in first.grid.cells))

        cells = tuple(cell for row in first.grid.cells for cell in row)
        self.assertEqual(49, sum(isinstance(cell, LetterCell) for cell in cells))
        self.assertEqual(28, sum(isinstance(cell, LegendCell) for cell in cells))
        self.assertEqual(4, sum(isinstance(cell, EmptyCell) for cell in cells))
        self.assertEqual(
            ("layout.disconnected-letters",),
            tuple(
                issue.code
                for issue in check_crossword_grid(first).warnings
            ),
        )

        for row_index, row in enumerate(first.grid.cells):
            for column_index, cell in enumerate(row):
                if not isinstance(cell, LegendCell):
                    continue
                self.assertEqual(1, len(cell.texts))
                right_is_letter = (
                    column_index + 1 < first.grid.width
                    and isinstance(
                        first.grid.cells[row_index][column_index + 1],
                        LetterCell,
                    )
                )
                down_is_letter = (
                    row_index + 1 < first.grid.height
                    and isinstance(
                        first.grid.cells[row_index + 1][column_index],
                        LetterCell,
                    )
                )
                self.assertNotEqual(right_is_letter, down_is_letter)

    def test_numbered_pipeline_is_deterministic(self) -> None:
        first = _filled_numbered_grid(
            TEST_DICTIONARY,
            width=7,
            height=7,
            seed=42,
        )
        second = _filled_numbered_grid(
            TEST_DICTIONARY,
            width=7,
            height=7,
            seed=42,
        )
        composed = create_grid_from_crossword(
            fill_crossword(
                generate_numbered_template(width=7, height=7),
                TEST_DICTIONARY,
                seed=42,
            )
        )

        self.assertEqual(first, second)
        self.assertEqual(first, composed)
        self.assertEqual(28, len(first.clues))
        assert first.grid.cells is not None
        cells = tuple(cell for row in first.grid.cells for cell in row)
        self.assertTrue(all(isinstance(cell, LetterCell) for cell in cells))
        self.assertEqual(
            tuple(range(1, 29)),
            tuple(
                number
                for cell in cells
                for number in cell_numbers(cell)
            ),
        )
        self.assertEqual(14, sum(len(cell.bars) for cell in cells))
        self.assertFalse(check_crossword_grid(first).warnings)

    def test_numbered_pipeline_keeps_secret(self) -> None:
        crossword = _filled_numbered_grid(
            TEST_DICTIONARY,
            width=7,
            height=7,
            seed=42,
            secret=SecretRequirement(words=("ABCD",)),
        )

        assert crossword.grid.cells is not None
        secret_cells = tuple(
            cell
            for row in crossword.grid.cells
            for cell in row
            if isinstance(cell, SecretCell)
        )
        self.assertEqual(4, len(secret_cells))
        self.assertEqual("ABCD", "".join(cell.value for cell in secret_cells))
        self.assertIn("Tajenka", tuple(clue.text for clue in crossword.clues))
        self.assertFalse(check_crossword_grid(crossword).warnings)

    def test_every_letter_run_is_a_dictionary_entry(self) -> None:
        crossword = _filled_swedish_grid(
            TEST_DICTIONARY,
            width=9,
            height=9,
            seed=42,
        )
        layout = create_dense_swedish_layout(9, 9)
        assert crossword.grid.cells is not None
        answers = {entry.answer for entry in TEST_DICTIONARY.entries}
        used_answers = []

        for row_segment in layout.row_segments:
            for column_segment in layout.column_segments:
                for row in range(row_segment.start, row_segment.stop):
                    answer = "".join(
                        crossword.grid.cells[row][column].value
                        for column in range(
                            column_segment.start,
                            column_segment.stop,
                        )
                    )
                    self.assertIn(answer, answers)
                    used_answers.append(answer)

                for column in range(column_segment.start, column_segment.stop):
                    answer = "".join(
                        crossword.grid.cells[row][column].value
                        for row in range(row_segment.start, row_segment.stop)
                    )
                    self.assertIn(answer, answers)
                    used_answers.append(answer)

        self.assertEqual(len(used_answers), len(set(used_answers)))

    def test_seed_can_change_filled_grid(self) -> None:
        first = _filled_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=1)
        second = _filled_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=2)

        self.assertNotEqual(first, second)

    def test_rejects_too_small_grid(self) -> None:
        with self.assertRaisesRegex(GenerationError, "nelze rozdělit"):
            _filled_swedish_grid(TEST_DICTIONARY, width=3, height=9)

    def test_rejects_dictionary_without_required_length(self) -> None:
        dictionary = _complete_dictionary(3)

        with self.assertRaisesRegex(FillingError, "délky: 4"):
            _filled_swedish_grid(dictionary, width=5, height=5)


if __name__ == "__main__":
    unittest.main()

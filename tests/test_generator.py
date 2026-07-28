"""Testy hustého generátoru švédské křížovky."""

from __future__ import annotations

import tempfile
import unittest
from itertools import product
from pathlib import Path

from krizovkar.dictionary import CrosswordDictionary, DictionaryEntry
from krizovkar.generator import (
    GenerationError,
    fill_crossword_template,
    generate_swedish_grid,
    generate_swedish_template,
)
from krizovkar.layout import create_dense_swedish_layout
from krizovkar.model import (
    Coordinate,
    CrosswordTemplate,
    EmptyCell,
    LegendCell,
    LetterCell,
    TemplateEmptyCell,
    TemplateLegendCell,
    TemplateLetterCell,
    TemplateGrid,
    WordSlot,
    load_crossword_grid,
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


TEST_DICTIONARY = _complete_dictionary(3, 4)


class GeneratorTest(unittest.TestCase):
    def test_fills_generated_template_deterministically(self) -> None:
        template = generate_swedish_template(width=5, height=5)

        first = fill_crossword_template(template, TEST_DICTIONARY, seed=42)
        second = fill_crossword_template(template, TEST_DICTIONARY, seed=42)

        self.assertEqual(first, second)
        self.assertEqual("grid", first.kind)
        self.assertEqual(5, first.grid.width)
        self.assertEqual(5, first.grid.height)
        assert first.grid.cells is not None
        cells = tuple(cell for row in first.grid.cells for cell in row)
        self.assertEqual(16, sum(isinstance(cell, LetterCell) for cell in cells))
        self.assertEqual(8, sum(isinstance(cell, LegendCell) for cell in cells))
        self.assertEqual(1, sum(isinstance(cell, EmptyCell) for cell in cells))
        self.assertFalse(first.clues)
        self.assertFalse(check_crossword_grid(first).warnings)

    def test_fills_external_slots_with_numbers_clues_and_bar(self) -> None:
        template = CrosswordTemplate(
            format_name="krizovkar",
            kind="template",
            version=1,
            grid=TemplateGrid(
                width=6,
                height=1,
                cells=((TemplateLetterCell(),) * 6,),
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

        crossword = fill_crossword_template(template, TEST_DICTIONARY, seed=3)

        assert crossword.grid.cells is not None
        row = crossword.grid.cells[0]
        self.assertEqual(1, row[0].number)
        self.assertEqual(("right",), row[2].bars)
        self.assertEqual(2, row[3].number)
        self.assertEqual((1, 2), tuple(clue.number for clue in crossword.clues))
        self.assertEqual(
            ("horizontal", "horizontal"),
            tuple(clue.direction for clue in crossword.clues),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "external.yaml"
            write_crossword_grid(crossword, output)
            self.assertEqual(crossword, load_crossword_grid(output))

    def test_fills_double_internal_legend_in_direction_order(self) -> None:
        template = CrosswordTemplate(
            format_name="krizovkar",
            kind="template",
            version=1,
            grid=TemplateGrid(
                width=2,
                height=2,
                cells=(
                    (TemplateLegendCell(), TemplateLetterCell()),
                    (TemplateLetterCell(), TemplateEmptyCell()),
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

        crossword = fill_crossword_template(template, dictionary, seed=1)

        assert crossword.grid.cells is not None
        legend = crossword.grid.cells[0][0]
        self.assertIsInstance(legend, LegendCell)
        self.assertEqual(2, len(legend.texts))
        self.assertFalse(legend.arrows)

    def test_template_fill_rejects_missing_length(self) -> None:
        template = generate_swedish_template(width=5, height=5)
        dictionary = _complete_dictionary(3)

        with self.assertRaisesRegex(GenerationError, "délky: 4"):
            fill_crossword_template(template, dictionary)

    def test_template_fill_rejects_unsatisfiable_crossing(self) -> None:
        template = CrosswordTemplate(
            format_name="krizovkar",
            kind="template",
            version=1,
            grid=TemplateGrid(
                width=2,
                height=2,
                cells=(
                    (TemplateLetterCell(), TemplateLetterCell()),
                    (TemplateLetterCell(), TemplateEmptyCell()),
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

        with self.assertRaisesRegex(GenerationError, "nepodařilo se vyplnit"):
            fill_crossword_template(template, dictionary)

    def test_generates_dense_template_without_dictionary(self) -> None:
        first = generate_swedish_template(width=9, height=9)
        second = generate_swedish_template(width=9, height=9)

        self.assertEqual(first, second)
        self.assertEqual("template", first.kind)
        self.assertEqual(9, first.grid.width)
        self.assertEqual(9, first.grid.height)
        cells = tuple(cell for row in first.grid.cells for cell in row)
        self.assertEqual(
            49,
            sum(isinstance(cell, TemplateLetterCell) for cell in cells),
        )
        self.assertEqual(
            28,
            sum(isinstance(cell, TemplateLegendCell) for cell in cells),
        )
        self.assertEqual(
            4,
            sum(isinstance(cell, TemplateEmptyCell) for cell in cells),
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

    def test_template_rejects_too_small_grid(self) -> None:
        with self.assertRaisesRegex(GenerationError, "nelze rozdělit"):
            generate_swedish_template(width=3, height=9)

    def test_generates_deterministic_dense_grid(self) -> None:
        first = generate_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=42)
        second = generate_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=42)

        self.assertEqual(first, second)
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

    def test_every_letter_run_is_a_dictionary_entry(self) -> None:
        crossword = generate_swedish_grid(
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

    def test_seed_can_change_generated_grid(self) -> None:
        first = generate_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=1)
        second = generate_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=2)

        self.assertNotEqual(first, second)

    def test_rejects_too_small_grid(self) -> None:
        with self.assertRaisesRegex(GenerationError, "nelze rozdělit"):
            generate_swedish_grid(TEST_DICTIONARY, width=3, height=9)

    def test_rejects_dictionary_without_required_length(self) -> None:
        dictionary = _complete_dictionary(3)

        with self.assertRaisesRegex(GenerationError, "délky: 4"):
            generate_swedish_grid(dictionary, width=5, height=5)


if __name__ == "__main__":
    unittest.main()

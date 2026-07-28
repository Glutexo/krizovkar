"""Testy hustého generátoru švédské křížovky."""

from __future__ import annotations

import unittest
from itertools import product

from krizovkar.dictionary import CrosswordDictionary, DictionaryEntry
from krizovkar.generator import (
    GenerationError,
    generate_swedish_grid,
    generate_swedish_template,
)
from krizovkar.layout import create_dense_swedish_layout
from krizovkar.model import (
    EmptyCell,
    LegendCell,
    LetterCell,
    TemplateEmptyCell,
    TemplateLegendCell,
    TemplateLetterCell,
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

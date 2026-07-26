"""Testy prvního generátoru švédské křížovky."""

from __future__ import annotations

import unittest

from krizovkar.dictionary import CrosswordDictionary, DictionaryEntry
from krizovkar.generator import GenerationError, generate_swedish_grid
from krizovkar.model import EmptyCell, LegendCell, LetterCell


def _dictionary(*answers: str) -> CrosswordDictionary:
    return CrosswordDictionary(
        entries=tuple(
            DictionaryEntry(answer=answer, clues=(f"Legenda {answer}",))
            for answer in answers
        )
    )


TEST_DICTIONARY = _dictionary(
    "KAREL",
    "REKA",
    "LAVKA",
    "KAVA",
    "RASA",
    "SOVA",
    "VLAK",
    "KOLO",
    "OKO",
    "LES",
    "PES",
    "ESO",
    "MRAK",
    "RAK",
    "LAK",
    "MAK",
    "MASO",
    "SELE",
    "LAMA",
    "MELA",
)


class GeneratorTest(unittest.TestCase):
    def test_generates_deterministic_connected_grid(self) -> None:
        first = generate_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=42)
        second = generate_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=42)

        self.assertEqual(first, second)
        self.assertEqual(9, first.grid.width)
        self.assertEqual(9, first.grid.height)
        assert first.grid.cells is not None
        self.assertEqual(9, len(first.grid.cells))
        self.assertTrue(all(len(row) == 9 for row in first.grid.cells))

        cells = tuple(cell for row in first.grid.cells for cell in row)
        legends = tuple(cell for cell in cells if isinstance(cell, LegendCell))
        self.assertGreaterEqual(sum(len(cell.texts) for cell in legends), 3)
        self.assertTrue(any(isinstance(cell, LetterCell) for cell in cells))
        self.assertTrue(any(isinstance(cell, EmptyCell) for cell in cells))
        for legend in legends:
            self.assertEqual(len(legend.texts), len(legend.arrows))
            self.assertEqual(len(legend.arrows), len(set(legend.arrows)))
        for row_index, row in enumerate(first.grid.cells):
            for column_index, cell in enumerate(row):
                if not isinstance(cell, LegendCell):
                    continue
                if "right" in cell.arrows:
                    self.assertIsInstance(
                        first.grid.cells[row_index][column_index + 1],
                        LetterCell,
                    )
                if "down" in cell.arrows:
                    self.assertIsInstance(
                        first.grid.cells[row_index + 1][column_index],
                        LetterCell,
                    )

    def test_seed_can_change_generated_grid(self) -> None:
        first = generate_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=1)
        second = generate_swedish_grid(TEST_DICTIONARY, width=9, height=9, seed=2)

        self.assertNotEqual(first, second)

    def test_rejects_too_small_grid(self) -> None:
        with self.assertRaisesRegex(GenerationError, "alespoň 3"):
            generate_swedish_grid(TEST_DICTIONARY, width=2, height=9)

    def test_rejects_dictionary_without_fitting_entries(self) -> None:
        dictionary = _dictionary("PRILISDLOUHE")

        with self.assertRaisesRegex(GenerationError, "použitelná hesla"):
            generate_swedish_grid(dictionary, width=5, height=5)

    def test_rejects_dictionary_without_enough_crossings(self) -> None:
        dictionary = _dictionary("ABC", "DEF", "GHI")

        with self.assertRaisesRegex(GenerationError, "propojená hesla"):
            generate_swedish_grid(dictionary, width=7, height=7)


if __name__ == "__main__":
    unittest.main()

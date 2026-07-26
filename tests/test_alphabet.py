"""Testy českých písmenných buněk."""

from __future__ import annotations

import unittest

from krizovkar.alphabet import split_answer_letters


class AlphabetTest(unittest.TestCase):
    def test_splits_ch_into_one_cell_and_preserves_diacritics(self) -> None:
        self.assertEqual(
            ("O", "CH", "O", "Č", "E", "N", "Á"),
            split_answer_letters("OCHOČENÁ"),
        )

    def test_rejects_lowercase_and_punctuation(self) -> None:
        for answer in ("Řeka", "DVA-TŘI", "123"):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                split_answer_letters(answer)


if __name__ == "__main__":
    unittest.main()

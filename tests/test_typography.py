"""Testy českých typografických pravidel."""

from __future__ import annotations

import unittest

from krizovkar.typography import NON_BREAKING_SPACE, protect_czech_prepositions


class TypographyTest(unittest.TestCase):
    def test_protects_lowercase_consonant_prepositions(self) -> None:
        self.assertEqual(
            f"v{NON_BREAKING_SPACE}Praze, k{NON_BREAKING_SPACE}řece, "
            f"s{NON_BREAKING_SPACE}přáteli a z{NON_BREAKING_SPACE}domu",
            protect_czech_prepositions("v Praze, k řece, s přáteli a z domu"),
        )

    def test_protects_uppercase_prepositions_and_opening_punctuation(self) -> None:
        self.assertEqual(
            f"V{NON_BREAKING_SPACE}lese. K{NON_BREAKING_SPACE}„domu“; "
            f"S{NON_BREAKING_SPACE}nimi; Z{NON_BREAKING_SPACE}hor",
            protect_czech_prepositions("V lese. K „domu“; S nimi; Z hor"),
        )

    def test_does_not_change_one_letter_vowel_words(self) -> None:
        text = "a také i potom o řece u domu"

        self.assertEqual(text, protect_czech_prepositions(text))

    def test_is_idempotent(self) -> None:
        protected = f"v{NON_BREAKING_SPACE}Praze"

        self.assertEqual(protected, protect_czech_prepositions(protected))


if __name__ == "__main__":
    unittest.main()

"""Testy české lokalizace."""

from __future__ import annotations

import unittest

from krizovkar.localization import ngettext


class LocalizationTest(unittest.TestCase):
    def test_gettext_uses_all_czech_plural_forms(self) -> None:
        cases = (
            ("heslo", "hesel", 0, "hesel"),
            ("heslo", "hesel", 1, "heslo"),
            ("heslo", "hesel", 2, "hesla"),
            ("heslo", "hesel", 4, "hesla"),
            ("heslo", "hesel", 5, "hesel"),
            ("heslo", "hesel", 11, "hesel"),
            ("slot", "slotů", 1, "slot"),
            ("slot", "slotů", 3, "sloty"),
            ("slot", "slotů", 8, "slotů"),
        )

        for singular, plural, count, expected in cases:
            with self.subTest(singular=singular, count=count):
                self.assertEqual(
                    expected,
                    ngettext(singular, plural, count),
                )

"""Testy načítání slovníku pro plnění křížovek."""

from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path

from krizovkar.dictionary import DictionaryError, load_dictionary


class DictionaryTest(unittest.TestCase):
    def _source(self, directory: str, content: str) -> Path:
        source = Path(directory) / "dictionary.json"
        source.write_text(content, encoding="utf-8")
        return source

    def test_loads_entries_in_deterministic_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(
                directory,
                '{"ŘEKA": ["Vodní tok", "Říčka"], "CHATA": ["Stavení"]}',
            )

            dictionary = load_dictionary(source)

        self.assertEqual(2, len(dictionary))
        self.assertEqual(
            ("CHATA", "ŘEKA"),
            tuple(entry.answer for entry in dictionary.entries),
        )
        self.assertEqual(("Vodní tok", "Říčka"), dictionary.entries[1].clues)

    def test_loads_dictionary_from_text_stream(self) -> None:
        dictionary = load_dictionary(StringIO('{"LES": ["Porost stromů"]}'))

        self.assertEqual(1, len(dictionary))
        self.assertEqual("LES", dictionary.entries[0].answer)

    def test_stream_error_names_standard_input(self) -> None:
        with self.assertRaises(DictionaryError) as caught:
            load_dictionary(StringIO("{"))

        self.assertIn("standardní vstup", str(caught.exception))

    def test_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(directory, "{")

            with self.assertRaises(DictionaryError) as caught:
                load_dictionary(source)

        message = str(caught.exception)
        self.assertIn("není platný JSON", message)
        self.assertIn("řádek 1, sloupec 2", message)
        self.assertNotIn("Expecting", message)

    def test_rejects_duplicate_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(
                directory,
                '{"LES": ["Porost"], "LES": ["Hvozd"]}',
            )

            with self.assertRaisesRegex(DictionaryError, "duplicitní klíč"):
                load_dictionary(source)

    def test_rejects_invalid_dictionary_shape(self) -> None:
        invalid_contents = {
            "pole místo objektu": "[]",
            "prázdný objekt": "{}",
            "neplatné heslo": '{"Řeka": ["Vodní tok"]}',
            "legenda místo seznamu": '{"REKA": "Vodní tok"}',
            "prázdný seznam": '{"REKA": []}',
            "prázdná legenda": '{"REKA": ["   "]}',
            "ne-textová legenda": '{"REKA": [1]}',
            "duplicitní legenda": '{"REKA": ["Tok", "Tok"]}',
        }
        for description, content in invalid_contents.items():
            with (
                self.subTest(description=description),
                tempfile.TemporaryDirectory() as directory,
            ):
                source = self._source(directory, content)

                with self.assertRaises(DictionaryError):
                    load_dictionary(source)

    def test_reports_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.json"

            with self.assertRaises(DictionaryError) as caught:
                load_dictionary(source)

        message = str(caught.exception)
        self.assertIn("nelze načíst", message)
        self.assertIn("soubor nebo adresář neexistuje", message)
        self.assertNotIn("No such file or directory", message)


if __name__ == "__main__":
    unittest.main()

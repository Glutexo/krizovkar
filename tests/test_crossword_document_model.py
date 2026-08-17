"""Testy datového modelu editovatelné křížovky."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from io import StringIO
from pathlib import Path

from krizovkar.model import (
    CrosswordDocument,
    ModelError,
    dump_crossword_document,
    load_crossword_document,
    write_crossword_document,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CROSSWORD_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "crossword-minimal.yaml"


class CrosswordDocumentModelTest(unittest.TestCase):
    def test_public_crossword_examples_use_current_document_kind(self) -> None:
        sources = sorted((PROJECT_ROOT / "examples").glob("crossword-*.yaml"))

        self.assertTrue(sources)
        for source in sources:
            with self.subTest(source=source.name):
                crossword = load_crossword_document(source)
                self.assertEqual("crossword", crossword.kind)

    def test_loads_and_writes_crossword_document(self) -> None:
        crossword = load_crossword_document(CROSSWORD_MINIMAL_EXAMPLE)

        self.assertIsInstance(crossword, CrosswordDocument)
        self.assertEqual("crossword", crossword.kind)
        self.assertEqual("LES", crossword.slots[0].answer)
        self.assertEqual("Porost stromů", crossword.slots[0].clue)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "krizovka.yaml"
            write_crossword_document(crossword, output)
            self.assertEqual(crossword, load_crossword_document(output))

    def test_dumps_crossword_document_to_text_stream(self) -> None:
        crossword = load_crossword_document(CROSSWORD_MINIMAL_EXAMPLE)
        output = StringIO()

        dump_crossword_document(crossword, output)

        self.assertIn("kind: crossword\n", output.getvalue())
        self.assertEqual(
            crossword,
            load_crossword_document(StringIO(output.getvalue())),
        )

    def test_writer_rejects_wrong_document_kind(self) -> None:
        crossword = load_crossword_document(CROSSWORD_MINIMAL_EXAMPLE)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "document.yaml"

            with self.assertRaisesRegex(ModelError, "hodnota 'crossword'"):
                write_crossword_document(
                    replace(crossword, kind="grid"),
                    output,
                )


if __name__ == "__main__":
    unittest.main()

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
    create_crossword_document,
    dump_crossword_document,
    load_crossword_document,
    load_crossword_template,
    write_crossword_document,
    write_crossword_template,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CROSSWORD_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "crossword-minimal.yaml"
TEMPLATE_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "template-minimal.yaml"


class CrosswordDocumentModelTest(unittest.TestCase):
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

    def test_creates_independent_crossword_document_from_template(self) -> None:
        template = load_crossword_template(TEMPLATE_MINIMAL_EXAMPLE)

        crossword = create_crossword_document(template)

        self.assertIsInstance(crossword, CrosswordDocument)
        self.assertEqual("crossword", crossword.kind)
        self.assertEqual(template.grid, crossword.grid)
        self.assertEqual(template.slots, crossword.slots)
        self.assertEqual("template", template.kind)

    def test_dumps_crossword_document_to_text_stream(self) -> None:
        crossword = load_crossword_document(CROSSWORD_MINIMAL_EXAMPLE)
        output = StringIO()

        dump_crossword_document(crossword, output)

        self.assertIn("kind: crossword\n", output.getvalue())
        self.assertEqual(
            crossword,
            load_crossword_document(StringIO(output.getvalue())),
        )

    def test_legacy_template_is_loaded_as_crossword_document(self) -> None:
        crossword = load_crossword_document(TEMPLATE_MINIMAL_EXAMPLE)

        self.assertIsInstance(crossword, CrosswordDocument)
        self.assertEqual("crossword", crossword.kind)
        self.assertIsNone(crossword.slots[0].answer)

        output = StringIO()
        dump_crossword_document(crossword, output)

        self.assertIn("kind: crossword\n", output.getvalue())
        self.assertNotIn("kind: template\n", output.getvalue())

    def test_legacy_template_loader_rejects_crossword_document(self) -> None:
        with self.assertRaisesRegex(ModelError, "očekává se hodnota 'template'"):
            load_crossword_template(CROSSWORD_MINIMAL_EXAMPLE)

    def test_writers_reject_wrong_document_kind(self) -> None:
        template = load_crossword_template(TEMPLATE_MINIMAL_EXAMPLE)
        crossword = load_crossword_document(CROSSWORD_MINIMAL_EXAMPLE)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "document.yaml"

            with self.assertRaisesRegex(ModelError, "hodnota 'template'"):
                write_crossword_template(crossword, output)
            with self.assertRaisesRegex(ModelError, "hodnota 'crossword'"):
                write_crossword_document(
                    replace(create_crossword_document(template), kind="template"),
                    output,
                )


if __name__ == "__main__":
    unittest.main()

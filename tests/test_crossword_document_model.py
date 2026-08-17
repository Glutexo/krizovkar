"""Testy datového modelu editovatelné křížovky."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from io import StringIO
from pathlib import Path

from krizovkar.model import (
    CrosswordDocument,
    CrosswordTemplate,
    ModelError,
    create_crossword_document,
    dump_crossword_document,
    dump_crossword_template,
    load_crossword_document,
    load_crossword_template,
    write_crossword_document,
    write_crossword_template,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CROSSWORD_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "crossword-minimal.yaml"
TEMPLATE_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "template-unfilled.yaml"


class CrosswordDocumentModelTest(unittest.TestCase):
    def test_public_template_examples_use_template_document_kind(self) -> None:
        sources = sorted((PROJECT_ROOT / "examples").glob("template-*.yaml"))

        self.assertTrue(sources)
        for source in sources:
            with self.subTest(source=source.name):
                template = load_crossword_template(source)
                self.assertIsInstance(template, CrosswordTemplate)
                self.assertNotIsInstance(template, CrosswordDocument)
                self.assertEqual("template", template.kind)

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

    def test_loads_and_writes_crossword_template(self) -> None:
        template = load_crossword_template(TEMPLATE_MINIMAL_EXAMPLE)

        self.assertIsInstance(template, CrosswordTemplate)
        self.assertNotIsInstance(template, CrosswordDocument)
        self.assertEqual("template", template.kind)
        self.assertIsNone(template.slots[0].answer)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sablona.yaml"
            write_crossword_template(template, output)
            self.assertEqual(template, load_crossword_template(output))

    def test_creates_crossword_document_from_template(self) -> None:
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

    def test_dumps_crossword_template_to_text_stream(self) -> None:
        template = load_crossword_template(TEMPLATE_MINIMAL_EXAMPLE)
        output = StringIO()

        dump_crossword_template(template, output)

        self.assertIn("kind: template\n", output.getvalue())
        self.assertEqual(
            template,
            load_crossword_template(StringIO(output.getvalue())),
        )

    def test_loaders_reject_other_structural_document_kind(self) -> None:
        with self.assertRaisesRegex(ModelError, "hodnota 'crossword'"):
            load_crossword_document(TEMPLATE_MINIMAL_EXAMPLE)
        with self.assertRaisesRegex(ModelError, "hodnota 'template'"):
            load_crossword_template(CROSSWORD_MINIMAL_EXAMPLE)

    def test_writer_rejects_wrong_document_kind(self) -> None:
        template = load_crossword_template(TEMPLATE_MINIMAL_EXAMPLE)
        crossword = load_crossword_document(CROSSWORD_MINIMAL_EXAMPLE)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "document.yaml"

            with self.assertRaisesRegex(ModelError, "hodnota 'template'"):
                write_crossword_template(crossword, output)
            with self.assertRaisesRegex(ModelError, "hodnota 'crossword'"):
                write_crossword_document(template, output)
            with self.assertRaisesRegex(ModelError, "hodnota 'crossword'"):
                write_crossword_document(
                    replace(crossword, kind="grid"),
                    output,
                )


if __name__ == "__main__":
    unittest.main()

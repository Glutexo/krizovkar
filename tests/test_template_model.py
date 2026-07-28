"""Testy datového modelu strukturální šablony."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from krizovkar.model import (
    ModelError,
    TemplateLetterCell,
    load_crossword_template,
    write_crossword_template,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "template-minimal.yaml"


class TemplateModelTest(unittest.TestCase):
    def _load(self, content: str):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        source = Path(directory.name) / "template.yaml"
        source.write_text(content, encoding="utf-8")
        return load_crossword_template(source)

    def test_loads_and_writes_minimal_template(self) -> None:
        template = load_crossword_template(TEMPLATE_MINIMAL_EXAMPLE)

        self.assertEqual("krizovkar", template.format_name)
        self.assertEqual("template", template.kind)
        self.assertEqual(1, template.version)
        self.assertEqual(3, template.grid.width)
        self.assertEqual(1, template.grid.height)
        self.assertTrue(
            all(isinstance(cell, TemplateLetterCell) for cell in template.grid.cells[0])
        )
        self.assertEqual("h1", template.slots[0].identifier)
        self.assertEqual(3, template.slots[0].length)
        self.assertIsNone(template.slots[0].legend_position)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "written.yaml"
            write_crossword_template(template, output)
            self.assertEqual(template, load_crossword_template(output))

    def test_accepts_crossing_slots(self) -> None:
        template = self._load(
            "format: krizovkar\n"
            "kind: template\n"
            "version: 1\n"
            "grid:\n"
            "  width: 3\n"
            "  height: 3\n"
            "  cells:\n"
            "    - [{type: empty}, {type: letter}, {type: empty}]\n"
            "    - [{type: letter}, {type: letter}, {type: letter}]\n"
            "    - [{type: empty}, {type: letter}, {type: empty}]\n"
            "slots:\n"
            "  - id: h1\n"
            "    start: {row: 2, column: 1}\n"
            "    direction: horizontal\n"
            "    length: 3\n"
            "  - id: v1\n"
            "    start: {row: 1, column: 2}\n"
            "    direction: vertical\n"
            "    length: 3\n"
        )

        self.assertEqual(("h1", "v1"), tuple(slot.identifier for slot in template.slots))

    def test_accepts_internal_legend_before_slot(self) -> None:
        template = self._load(
            "format: krizovkar\n"
            "kind: template\n"
            "version: 1\n"
            "grid:\n"
            "  width: 2\n"
            "  height: 1\n"
            "  cells:\n"
            "    - [{type: legend}, {type: letter}]\n"
            "slots:\n"
            "  - id: h1\n"
            "    start: {row: 1, column: 2}\n"
            "    direction: horizontal\n"
            "    length: 1\n"
            "    legend: {row: 1, column: 1}\n"
        )

        self.assertEqual(1, template.slots[0].legend_position.column)

    def test_rejects_wrong_number_of_rows(self) -> None:
        with self.assertRaisesRegex(ModelError, "počet řádků"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 2\n"
                "  cells:\n"
                "    - [{type: letter}]\n"
                "slots:\n"
                "  - id: h1\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    length: 1\n"
            )

    def test_rejects_duplicate_slot_identifier(self) -> None:
        with self.assertRaisesRegex(ModelError, "identifikátor 'h1' už používá"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 2\n"
                "  height: 2\n"
                "  cells:\n"
                "    - [{type: letter}, {type: letter}]\n"
                "    - [{type: letter}, {type: letter}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 2}\n"
                "  - {id: h1, start: {row: 2, column: 1}, direction: horizontal, length: 2}\n"
            )

    def test_rejects_slot_over_nonletter_cell(self) -> None:
        with self.assertRaisesRegex(ModelError, "vede přes nepísmennou buňku"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 2\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter}, {type: empty}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 2}\n"
            )

    def test_rejects_overlapping_slots_in_same_direction(self) -> None:
        with self.assertRaisesRegex(ModelError, "ve stejném směru překrývá"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 3\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter}, {type: letter}, {type: letter}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 2}\n"
                "  - {id: h2, start: {row: 1, column: 2}, direction: horizontal, length: 2}\n"
            )

    def test_rejects_orphan_letter_cell(self) -> None:
        with self.assertRaisesRegex(ModelError, "písmenná buňka nepatří"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 2\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter}, {type: letter}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 1}\n"
            )

    def test_rejects_unused_legend_cell(self) -> None:
        with self.assertRaisesRegex(ModelError, "legendovou buňku nepoužívá"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 2\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: legend}, {type: letter}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 2}, direction: horizontal, length: 1}\n"
            )

    def test_rejects_nonadjacent_legend(self) -> None:
        with self.assertRaisesRegex(ModelError, "musí bezprostředně předcházet"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 3\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: legend}, {type: empty}, {type: letter}]\n"
                "slots:\n"
                "  - id: h1\n"
                "    start: {row: 1, column: 3}\n"
                "    direction: horizontal\n"
                "    length: 1\n"
                "    legend: {row: 1, column: 1}\n"
            )


if __name__ == "__main__":
    unittest.main()

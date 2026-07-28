"""Testy datového modelu strukturální šablony."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from krizovkar.model import (
    ModelError,
    SecretPrompt,
    TemplateLetterCell,
    load_crossword_template,
    write_crossword_template,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "template-minimal.yaml"
TEMPLATE_SECRET_EXAMPLE = PROJECT_ROOT / "examples" / "template-secret.yaml"


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

    def test_loads_and_writes_template_with_known_secret(self) -> None:
        template = load_crossword_template(TEMPLATE_SECRET_EXAMPLE)

        self.assertEqual(1, len(template.secrets))
        secret = template.secrets[0]
        self.assertEqual(("ZELENÍ",), secret.words)
        self.assertEqual("h1", secret.parts[0].slot_identifier)
        self.assertEqual(1, secret.parts[0].word_count)
        self.assertEqual(
            SecretPrompt(
                text='Lidové rčení: „Komu se nelení, tomu se …“',
                placement="above",
                alignment="left",
            ),
            secret.prompt,
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "secret.yaml"
            write_crossword_template(template, output)
            self.assertEqual(template, load_crossword_template(output))

    def test_accepts_reserved_secret_without_known_words(self) -> None:
        template = self._load(
            "format: krizovkar\n"
            "kind: template\n"
            "version: 1\n"
            "grid:\n"
            "  width: 3\n"
            "  height: 1\n"
            "  cells:\n"
            "    - [{type: letter}, {type: letter}, {type: letter}]\n"
            "slots:\n"
            "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 3}\n"
            "secrets:\n"
            "  - parts: [{slot: h1}]\n"
        )

        self.assertFalse(template.secrets[0].words)
        self.assertIsNone(template.secrets[0].parts[0].word_count)

    def test_accepts_ch_as_one_secret_cell(self) -> None:
        template = self._load(
            "format: krizovkar\n"
            "kind: template\n"
            "version: 1\n"
            "grid:\n"
            "  width: 1\n"
            "  height: 1\n"
            "  cells:\n"
            "    - [{type: letter}]\n"
            "slots:\n"
            "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 1}\n"
            "secrets:\n"
            "  - words: [CH]\n"
            "    parts: [{slot: h1, word_count: 1}]\n"
        )

        self.assertEqual(("CH",), template.secrets[0].words)

    def test_rejects_secret_part_with_unknown_slot(self) -> None:
        with self.assertRaisesRegex(ModelError, "slot 'h2' v šabloně neexistuje"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 1}\n"
                "secrets:\n"
                "  - parts: [{slot: h2}]\n"
            )

    def test_rejects_slot_shared_by_secret_parts(self) -> None:
        with self.assertRaisesRegex(ModelError, "slot 'h1' už používá"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 1}\n"
                "secrets:\n"
                "  - parts: [{slot: h1}, {slot: h1}]\n"
            )

    def test_rejects_known_secret_without_word_counts(self) -> None:
        with self.assertRaisesRegex(ModelError, "musí u každé části uvést word_count"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 1}\n"
                "secrets:\n"
                "  - words: [A]\n"
                "    parts: [{slot: h1}]\n"
            )

    def test_rejects_word_count_without_known_words(self) -> None:
        with self.assertRaisesRegex(ModelError, "word_count lze uvést jen"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 1}\n"
                "secrets:\n"
                "  - parts: [{slot: h1, word_count: 1}]\n"
            )

    def test_rejects_secret_word_count_sum_mismatch(self) -> None:
        with self.assertRaisesRegex(ModelError, "součet word_count neodpovídá"):
            self._load(
                "format: krizovkar\n"
                "kind: template\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter}]\n"
                "slots:\n"
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 1}\n"
                "secrets:\n"
                "  - words: [A, B]\n"
                "    parts: [{slot: h1, word_count: 1}]\n"
            )

    def test_rejects_secret_part_with_wrong_slot_length(self) -> None:
        with self.assertRaisesRegex(ModelError, "má 2 polí, ale slot 'h1' má délku 3"):
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
                "  - {id: h1, start: {row: 1, column: 1}, direction: horizontal, length: 3}\n"
                "secrets:\n"
                "  - words: [AB]\n"
                "    parts: [{slot: h1, word_count: 1}]\n"
            )

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

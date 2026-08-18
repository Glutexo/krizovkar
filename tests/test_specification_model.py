"""Testy zápisu datového modelu zadání."""

from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path

from krizovkar.model import (
    Coordinate,
    CrosswordSpecification,
    GridDimensions,
    ModelError,
    WordPlacement,
    dump_crossword_specification,
    load_crossword_specification,
    write_crossword_specification,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECIFICATION_EXAMPLES = tuple(
    sorted((PROJECT_ROOT / "examples").glob("specification-*.yaml"))
)


class SpecificationModelTest(unittest.TestCase):
    def test_loads_and_writes_all_examples(self) -> None:
        for source in SPECIFICATION_EXAMPLES:
            with self.subTest(source=source.name):
                specification = load_crossword_specification(source)
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / source.name

                    write_crossword_specification(specification, output)

                    self.assertEqual(
                        specification,
                        load_crossword_specification(output),
                    )

    def test_rejects_version_key(self) -> None:
        source = StringIO(
            "format: krizovkar\n"
            "kind: specification\n"
            "version: 1\n"
        )

        with self.assertRaisesRegex(ModelError, "nepovolený klíč 'version'"):
            load_crossword_specification(source)

    def test_dumps_specification_to_text_stream(self) -> None:
        specification = load_crossword_specification(
            PROJECT_ROOT / "examples" / "specification-placed-words.yaml"
        )
        output = StringIO()

        dump_crossword_specification(specification, output)

        self.assertNotIn("\nversion:", output.getvalue())
        output.seek(0)
        self.assertEqual(specification, load_crossword_specification(output))

    def test_writes_explicit_help_position(self) -> None:
        specification = CrosswordSpecification(
            format_name="krizovkar",
            kind="specification",
            grid=GridDimensions(width=3, height=2),
            words=(
                WordPlacement(
                    answer="ABC",
                    start=Coordinate(row=1, column=1),
                    direction="horizontal",
                    legend="Abeceda",
                    in_help=True,
                ),
            ),
            help_position=Coordinate(row=2, column=1),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "help.yaml"

            write_crossword_specification(specification, output)

            self.assertEqual(specification, load_crossword_specification(output))

    def test_refuses_grid_without_content(self) -> None:
        specification = CrosswordSpecification(
            format_name="krizovkar",
            kind="specification",
            grid=GridDimensions(width=15, height=10),
        )

        with self.assertRaisesRegex(ModelError, "neplatný datový model"):
            dump_crossword_specification(specification, StringIO())


if __name__ == "__main__":
    unittest.main()

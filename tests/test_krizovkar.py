"""Integrační testy prvního příkazu Křížovkáře."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from itertools import product
from pathlib import Path
from unittest.mock import patch

from krizovkar.cli import main
from krizovkar.model import (
    DEFAULT_SECRET_LEGEND,
    DEFAULT_SECRET_PART_LEGEND,
    Coordinate,
    EmptyCell,
    ExternalClue,
    GridDimensions,
    HelpCell,
    LegendCell,
    LetterCell,
    LetterCellRole,
    ModelError,
    SecretCell,
    SecretCells,
    SecretParts,
    SecretPrompt,
    SecretWord,
    WordPlacement,
    dump_crossword_grid,
    load_crossword_document,
    load_crossword_grid,
    load_crossword_specification,
    secret_path_arrows,
    write_crossword_grid,
)
from krizovkar.renderer import RenderError, resolve_page_size

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CROSSWORD_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "crossword-minimal.yaml"
GRID_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "grid-minimal.yaml"
GRID_CLASSIC_EXAMPLE = PROJECT_ROOT / "examples" / "grid-classic.yaml"
GRID_CZECH_LETTERS_EXAMPLE = PROJECT_ROOT / "examples" / "grid-czech-letters.yaml"
GRID_EMPTY_EXAMPLE = PROJECT_ROOT / "examples" / "grid-empty.yaml"
GRID_HELP_EXAMPLE = PROJECT_ROOT / "examples" / "grid-help.yaml"
GRID_LEGEND_EXAMPLE = PROJECT_ROOT / "examples" / "grid-legend.yaml"
GRID_MIXED_CLUES_EXAMPLE = PROJECT_ROOT / "examples" / "grid-mixed-clues.yaml"
GRID_RANDOM_LETTERS_EXAMPLE = PROJECT_ROOT / "examples" / "grid-random-letters.yaml"
GRID_SECRET_EXAMPLE = PROJECT_ROOT / "examples" / "grid-secret.yaml"
GRID_SECRET_ARROWS_EXAMPLE = PROJECT_ROOT / "examples" / "grid-secret-arrows.yaml"
GRID_SECRET_PROMPT_EXAMPLE = PROJECT_ROOT / "examples" / "grid-secret-prompt.yaml"
SPECIFICATION_MINIMAL_EXAMPLE = PROJECT_ROOT / "examples" / "specification-minimal.yaml"
SPECIFICATION_MULTIPART_SECRETS_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-multipart-secrets.yaml"
)
SPECIFICATION_SCATTERED_SECRET_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-scattered-secret.yaml"
)
SPECIFICATION_PLACED_WORDS_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-placed-words.yaml"
)
SPECIFICATION_SECRETS_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-secrets.yaml"
)
SPECIFICATION_SECRET_PROMPT_EXAMPLE = (
    PROJECT_ROOT / "examples" / "specification-secret-prompt.yaml"
)
CROSSWORD_SECRET_EXAMPLE = PROJECT_ROOT / "examples" / "crossword-secret.yaml"
PDF_BYTES = b"%PDF-1.7\n%%EOF\n"


def _fake_lualatex(source: Path, output_directory: Path) -> Path:
    output = output_directory / f"{source.stem}.pdf"
    output.write_bytes(PDF_BYTES)
    return output


class _BinaryStdout(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.buffer = io.BytesIO()


class ModelTest(unittest.TestCase):
    def test_loads_minimal_example(self) -> None:
        crossword = load_crossword_grid(GRID_MINIMAL_EXAMPLE)

        self.assertEqual("krizovkar", crossword.format_name)
        self.assertEqual("grid", crossword.kind)
        self.assertEqual(1, crossword.version)
        self.assertEqual(15, crossword.grid.width)
        self.assertEqual(10, crossword.grid.height)
        self.assertIsNone(crossword.grid.cells)

    def test_loads_grid_filled_with_letter_cells(self) -> None:
        crossword = load_crossword_grid(GRID_RANDOM_LETTERS_EXAMPLE)

        self.assertIsNotNone(crossword.grid.cells)
        assert crossword.grid.cells is not None
        self.assertEqual(10, len(crossword.grid.cells))
        self.assertTrue(all(len(row) == 15 for row in crossword.grid.cells))
        self.assertEqual("W", crossword.grid.cells[0][0].value)
        self.assertEqual("I", crossword.grid.cells[-1][-1].value)

    def test_loads_czech_letters_and_ch_in_one_cell(self) -> None:
        crossword = load_crossword_grid(GRID_CZECH_LETTERS_EXAMPLE)

        assert crossword.grid.cells is not None
        self.assertEqual(
            ("O", "CH", "O", "Č", "E", "N", "Á"),
            tuple(cell.value for cell in crossword.grid.cells[0]),
        )

    def test_loads_and_writes_numbered_grid_annotations(self) -> None:
        crossword = load_crossword_grid(GRID_CLASSIC_EXAMPLE)

        assert crossword.grid.cells is not None
        first = crossword.grid.cells[0][0]
        divided = crossword.grid.cells[2][2]
        secret_start = crossword.grid.cells[5][0]
        self.assertIsInstance(first, LetterCell)
        self.assertEqual(1, first.number)
        self.assertEqual(("right", "bottom"), divided.bars)
        self.assertIsInstance(secret_start, SecretCell)
        self.assertEqual(19, secret_start.number)
        self.assertEqual("right", secret_start.arrow)
        self.assertEqual(23, len(crossword.clues))
        self.assertEqual(
            ExternalClue(
                number=1,
                direction="horizontal",
                text="Prudký hod",
            ),
            crossword.clues[0],
        )
        self.assertEqual(
            ("horizontal", "vertical"),
            tuple(
                clue.direction for clue in crossword.clues if clue.number == 1
            ),
        )
        self.assertFalse(
            any(
                clue.number == 19 and clue.direction == "horizontal"
                for clue in crossword.clues
            )
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "classic.yaml"
            write_crossword_grid(crossword, output)
            self.assertEqual(crossword, load_crossword_grid(output))

    def test_loads_inline_and_numbered_clues_in_one_grid(self) -> None:
        crossword = load_crossword_grid(GRID_MIXED_CLUES_EXAMPLE)

        assert crossword.grid.cells is not None
        self.assertTrue(
            any(
                isinstance(cell, LegendCell)
                for row in crossword.grid.cells
                for cell in row
            )
        )
        self.assertEqual(1, crossword.grid.cells[2][2].number)
        self.assertEqual(
            (
                ExternalClue(
                    number=1,
                    direction="horizontal",
                    text="Operační systém (zkr.)",
                ),
            ),
            crossword.clues,
        )

    def test_loads_and_writes_secret_prompts(self) -> None:
        crossword = load_crossword_grid(GRID_SECRET_PROMPT_EXAMPLE)

        self.assertEqual(
            (
                SecretPrompt(
                    text='Lidové rčení: „Komu se nelení, tomu se …“',
                    placement="above",
                    alignment="left",
                ),
            ),
            crossword.secret_prompts,
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "secret-prompt.yaml"
            write_crossword_grid(crossword, output)
            self.assertEqual(crossword, load_crossword_grid(output))

    def test_secret_prompt_uses_default_placement_and_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "secret-prompt-defaults.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid: {width: 1, height: 1}\n"
                "secret_prompts:\n"
                "  - text: Zadání tajenky\n",
                encoding="utf-8",
            )

            crossword = load_crossword_grid(source)

        self.assertEqual(
            (SecretPrompt(text="Zadání tajenky"),),
            crossword.secret_prompts,
        )

    def test_rejects_invalid_secret_prompt(self) -> None:
        invalid_properties = (
            ("text", "'   '"),
            ("placement", "beside"),
            ("alignment", "center"),
        )
        for property_name, value in invalid_properties:
            with self.subTest(property_name=property_name):
                with tempfile.TemporaryDirectory() as directory:
                    source = Path(directory) / "invalid-secret-prompt.yaml"
                    prompt = (
                        f"  - text: {value}\n"
                        if property_name == "text"
                        else (
                            "  - text: Zadání tajenky\n"
                            f"    {property_name}: {value}\n"
                        )
                    )
                    source.write_text(
                        "format: krizovkar\n"
                        "kind: grid\n"
                        "version: 1\n"
                        "grid: {width: 1, height: 1}\n"
                        "secret_prompts:\n"
                        f"{prompt}",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(
                        ModelError,
                        rf"\$\.secret_prompts\[0\]\.{property_name}",
                    ):
                        load_crossword_grid(source)

    def test_rejects_duplicate_grid_cell_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "duplicate-number.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 2\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: A, number: 1}, "
                "{type: letter, value: B, number: 1}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ModelError,
                r"\$\.grid\.cells\[0\]\[1\]\.number.*už používá",
            ):
                load_crossword_grid(source)

    def test_rejects_external_clue_without_numbered_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "orphan-clue.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: A, number: 1}]\n"
                "clues:\n"
                "  - {number: 2, direction: horizontal, text: Legenda}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ModelError,
                r"\$\.clues\[0\]\.number.*nemá odpovídající",
            ):
                load_crossword_grid(source)

    def test_rejects_duplicate_external_clue_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "duplicate-clue.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: A, number: 1}]\n"
                "clues:\n"
                "  - {number: 1, direction: vertical, text: První}\n"
                "  - {number: 1, direction: vertical, text: Druhá}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ModelError,
                r"\$\.clues\[1\].*uvedená vícekrát",
            ):
                load_crossword_grid(source)

    def test_rejects_external_clue_start_without_word_bar(self) -> None:
        cases = (
            (
                "horizontal",
                "grid:\n"
                "  width: 2\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: A}, "
                "{type: letter, value: B, number: 2}]\n",
                "pravý předěl",
            ),
            (
                "vertical",
                "grid:\n"
                "  width: 1\n"
                "  height: 2\n"
                "  cells:\n"
                "    - [{type: letter, value: A}]\n"
                "    - [{type: letter, value: B, number: 2}]\n",
                "dolní předěl",
            ),
        )
        for direction, grid, expected in cases:
            with (
                self.subTest(direction=direction),
                tempfile.TemporaryDirectory() as directory,
            ):
                source = Path(directory) / "missing-word-bar.yaml"
                source.write_text(
                    "format: krizovkar\n"
                    "kind: grid\n"
                    "version: 1\n"
                    f"{grid}"
                    "clues:\n"
                    f"  - {{number: 2, direction: {direction}, "
                    "text: Legenda}\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ModelError, expected):
                    load_crossword_grid(source)

    def test_rejects_word_bar_on_outer_grid_edge(self) -> None:
        for bar in ("right", "bottom"):
            with (
                self.subTest(bar=bar),
                tempfile.TemporaryDirectory() as directory,
            ):
                source = Path(directory) / "outer-bar.yaml"
                source.write_text(
                    "format: krizovkar\n"
                    "kind: grid\n"
                    "version: 1\n"
                    "grid:\n"
                    "  width: 1\n"
                    "  height: 1\n"
                    "  cells:\n"
                    f"    - [{{type: letter, value: A, bars: [{bar}]}}]\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ModelError, r"\.bars:.*uvnitř"):
                    load_crossword_grid(source)

    def test_loads_minimal_specification(self) -> None:
        specification = load_crossword_specification(SPECIFICATION_MINIMAL_EXAMPLE)

        self.assertEqual("krizovkar", specification.format_name)
        self.assertEqual("specification", specification.kind)
        self.assertEqual(1, specification.version)
        self.assertIsNone(specification.grid)
        self.assertEqual((), specification.words)
        self.assertEqual((), specification.secrets)
        self.assertIsNone(specification.help_position)

    def test_loads_specification_with_placed_words(self) -> None:
        specification = load_crossword_specification(SPECIFICATION_PLACED_WORDS_EXAMPLE)

        self.assertEqual(GridDimensions(width=7, height=6), specification.grid)
        self.assertEqual(3, len(specification.words))
        first = specification.words[0]
        self.assertIsInstance(first, WordPlacement)
        self.assertEqual("LABE", first.answer)
        self.assertEqual(Coordinate(row=2, column=2), first.start)
        self.assertEqual("horizontal", first.direction)
        self.assertEqual("Česká řeka", first.legend)
        self.assertFalse(first.in_help)
        self.assertEqual(
            ("LES", "EMU"),
            tuple(word.answer for word in specification.words if word.in_help),
        )
        self.assertIsNone(specification.help_position)

    def test_loads_cell_and_word_secrets(self) -> None:
        specification = load_crossword_specification(SPECIFICATION_SECRETS_EXAMPLE)

        self.assertEqual(2, len(specification.secrets))
        selected, word = specification.secrets
        self.assertIsInstance(selected, SecretCells)
        assert isinstance(selected, SecretCells)
        self.assertEqual(
            (
                Coordinate(row=2, column=2),
                Coordinate(row=2, column=3),
                Coordinate(row=2, column=4),
                Coordinate(row=2, column=5),
                Coordinate(row=3, column=5),
                Coordinate(row=4, column=5),
            ),
            selected.cells,
        )
        self.assertTrue(selected.arrows)
        self.assertEqual(selected.cells, selected.reading_cells)
        self.assertEqual(
            (
                (Coordinate(row=2, column=2), "right"),
                (Coordinate(row=2, column=5), "down"),
            ),
            secret_path_arrows(selected),
        )
        self.assertIsInstance(word, SecretWord)
        assert isinstance(word, SecretWord)
        self.assertEqual("KŘÍŽOVKÁŘ", word.answer)
        self.assertEqual(Coordinate(row=5, column=2), word.start)
        self.assertEqual("horizontal", word.direction)
        self.assertEqual(DEFAULT_SECRET_LEGEND, word.legend)

    def test_loads_secret_prompt_from_specification(self) -> None:
        specification = load_crossword_specification(
            SPECIFICATION_SECRET_PROMPT_EXAMPLE
        )

        self.assertEqual(1, len(specification.secrets))
        secret = specification.secrets[0]
        self.assertIsInstance(secret, SecretWord)
        assert isinstance(secret, SecretWord)
        self.assertEqual("ZELENÍ", secret.answer)
        self.assertEqual(
            SecretPrompt(
                text='Lidové rčení: „Komu se nelení, tomu se …“',
                placement="above",
                alignment="left",
            ),
            secret.prompt,
        )

    def test_all_secret_types_accept_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "all-secret-prompts.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 2, height: 1}\n"
                "words:\n"
                "  - answer: AB\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "secrets:\n"
                "  - type: cells\n"
                "    cells: [{row: 1, column: 1}]\n"
                "    prompt: {text: První zadání}\n"
                "  - type: parts\n"
                "    prompt:\n"
                "      text: Druhé zadání\n"
                "      placement: below\n"
                "      alignment: right\n"
                "    parts:\n"
                "      - type: cells\n"
                "        cells: [{row: 1, column: 1}]\n"
                "      - type: cells\n"
                "        cells: [{row: 1, column: 2}]\n",
                encoding="utf-8",
            )

            specification = load_crossword_specification(source)

        cells, parts = specification.secrets
        self.assertIsInstance(cells, SecretCells)
        self.assertIsInstance(parts, SecretParts)
        assert isinstance(cells, SecretCells)
        assert isinstance(parts, SecretParts)
        self.assertEqual(SecretPrompt(text="První zadání"), cells.prompt)
        self.assertEqual(
            SecretPrompt(
                text="Druhé zadání",
                placement="below",
                alignment="right",
            ),
            parts.prompt,
        )

    def test_reads_scattered_secret_cells_by_rows(self) -> None:
        specification = load_crossword_specification(
            SPECIFICATION_SCATTERED_SECRET_EXAMPLE
        )

        selected = specification.secrets[0]
        self.assertIsInstance(selected, SecretCells)
        assert isinstance(selected, SecretCells)
        self.assertFalse(selected.arrows)
        self.assertEqual(
            (
                Coordinate(row=1, column=1),
                Coordinate(row=1, column=3),
                Coordinate(row=1, column=5),
                Coordinate(row=2, column=2),
                Coordinate(row=2, column=4),
                Coordinate(row=3, column=1),
                Coordinate(row=3, column=5),
            ),
            selected.reading_cells,
        )
        self.assertNotEqual(selected.cells, selected.reading_cells)

    def test_arrowed_secret_keeps_explicit_path_order(self) -> None:
        selected = SecretCells(
            cells=(
                Coordinate(row=2, column=2),
                Coordinate(row=2, column=1),
                Coordinate(row=1, column=1),
            ),
            arrows=True,
        )

        self.assertEqual(selected.cells, selected.reading_cells)
        self.assertEqual(
            (
                (Coordinate(row=2, column=2), "left"),
                (Coordinate(row=2, column=1), "up"),
            ),
            secret_path_arrows(selected),
        )

    def test_loads_arbitrary_secret_word_without_dictionary_or_legend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "word-secret-only.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 7, height: 1}\n"
                "secrets:\n"
                "  - type: word\n"
                "    answer: GLUTEXO\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n",
                encoding="utf-8",
            )

            specification = load_crossword_specification(source)

            self.assertEqual((), specification.words)
            self.assertEqual(1, len(specification.secrets))
            secret = specification.secrets[0]
            self.assertIsInstance(secret, SecretWord)
            assert isinstance(secret, SecretWord)
            self.assertEqual("GLUTEXO", secret.answer)
            self.assertEqual(DEFAULT_SECRET_LEGEND, secret.legend)

    def test_loads_multipart_cell_and_word_secrets(self) -> None:
        specification = load_crossword_specification(
            SPECIFICATION_MULTIPART_SECRETS_EXAMPLE
        )

        self.assertEqual(2, len(specification.secrets))
        cell_secret, word_secret = specification.secrets
        self.assertIsInstance(cell_secret, SecretParts)
        assert isinstance(cell_secret, SecretParts)
        self.assertEqual(2, len(cell_secret.parts))
        first_block, second_block = cell_secret.parts
        self.assertIsInstance(first_block, SecretCells)
        self.assertIsInstance(second_block, SecretCells)
        assert isinstance(first_block, SecretCells)
        assert isinstance(second_block, SecretCells)
        self.assertEqual(
            ((Coordinate(row=2, column=2), "right"),),
            secret_path_arrows(first_block),
        )
        self.assertEqual(
            ((Coordinate(row=2, column=5), "down"),),
            secret_path_arrows(second_block),
        )

        self.assertIsInstance(word_secret, SecretParts)
        assert isinstance(word_secret, SecretParts)
        first_part, second_part, third_part = word_secret.parts
        self.assertTrue(
            all(
                isinstance(part, SecretWord)
                for part in (first_part, second_part, third_part)
            )
        )
        assert isinstance(first_part, SecretWord)
        assert isinstance(second_part, SecretWord)
        assert isinstance(third_part, SecretWord)
        self.assertEqual("{number}. část tajenky", DEFAULT_SECRET_PART_LEGEND)
        self.assertEqual("1. část tajenky", first_part.legend)
        self.assertEqual("2. část tajenky", second_part.legend)
        self.assertEqual("3. díl tajenky", third_part.legend)

    def test_allows_gap_in_unarrowed_multipart_secret_part(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "multipart-secret-gap.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 2}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "secrets:\n"
                "  - type: parts\n"
                "    parts:\n"
                "      - type: cells\n"
                "        cells:\n"
                "          - {row: 1, column: 1}\n"
                "          - {row: 1, column: 3}\n"
                "      - type: word\n"
                "        answer: DE\n"
                "        start: {row: 2, column: 1}\n"
                "        direction: horizontal\n",
                encoding="utf-8",
            )

            specification = load_crossword_specification(source)

            secret = specification.secrets[0]
            self.assertIsInstance(secret, SecretParts)
            assert isinstance(secret, SecretParts)
            selected = secret.parts[0]
            self.assertIsInstance(selected, SecretCells)
            assert isinstance(selected, SecretCells)
            self.assertEqual(
                (
                    Coordinate(row=1, column=1),
                    Coordinate(row=1, column=3),
                ),
                selected.reading_cells,
            )

    def test_rejects_secret_cell_outside_grid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "secret-cell-outside.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 1}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "secrets:\n"
                "  - type: cells\n"
                "    cells: [{row: 1, column: 4}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ModelError, r"\$\.secrets\[0\]\.cells\[0\].*mimo mřížku"
            ):
                load_crossword_specification(source)

    def test_rejects_secret_cell_without_letter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unoccupied-secret-cell.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 2}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "secrets:\n"
                "  - type: cells\n"
                "    cells: [{row: 2, column: 1}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, "obsazenou písmenem"):
                load_crossword_specification(source)

    def test_rejects_gap_in_arrowed_secret_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "secret-path-gap.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 1}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "secrets:\n"
                "  - type: cells\n"
                "    arrows: true\n"
                "    cells:\n"
                "      - {row: 1, column: 1}\n"
                "      - {row: 1, column: 3}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ModelError, r"\$\.secrets\[0\]\.cells\[1\].*společnou hranou"
            ):
                load_crossword_specification(source)

    def test_allows_gap_in_unarrowed_secret_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unarrowed-secret-gap.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 1}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "secrets:\n"
                "  - type: cells\n"
                "    cells:\n"
                "      - {row: 1, column: 1}\n"
                "      - {row: 1, column: 3}\n",
                encoding="utf-8",
            )

            specification = load_crossword_specification(source)
            selected = specification.secrets[0]

            self.assertIsInstance(selected, SecretCells)
            assert isinstance(selected, SecretCells)
            self.assertFalse(selected.arrows)
            self.assertEqual((), secret_path_arrows(selected))

    def test_rejects_single_cell_arrowed_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "single-cell-secret.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 1, height: 1}\n"
                "words:\n"
                "  - answer: A\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Písmeno\n"
                "secrets:\n"
                "  - type: cells\n"
                "    arrows: true\n"
                "    cells: [{row: 1, column: 1}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ModelError, r"\$\.secrets\[0\]\.arrows.*alespoň dvě"
            ):
                load_crossword_specification(source)

    def test_rejects_conflicting_secret_word_intersection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "conflicting-secret-word.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 3}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 2, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "secrets:\n"
                "  - type: word\n"
                "    answer: AX\n"
                "    start: {row: 1, column: 2}\n"
                "    direction: vertical\n"
                "    legend: Tajenka\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.secrets\[0\].*v rozporu"):
                load_crossword_specification(source)

    def test_rejects_empty_explicit_secret_word_legend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "secret-word-without-legend.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 2}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "secrets:\n"
                "  - type: word\n"
                "    answer: AB\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: '   '\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.secrets\[0\]\.legend"):
                load_crossword_specification(source)

    def test_loads_explicit_help_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "explicit-help.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 3}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "    in_help: true\n"
                "help:\n"
                "  position: {row: 3, column: 3}\n",
                encoding="utf-8",
            )

            specification = load_crossword_specification(source)

            self.assertEqual(Coordinate(row=3, column=3), specification.help_position)

    def test_specification_counts_ch_as_one_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "czech-answer.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 7, height: 1}\n"
                "words:\n"
                "  - answer: OCHOČENÁ\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Zkrocená\n",
                encoding="utf-8",
            )

            specification = load_crossword_specification(source)

            self.assertEqual("OCHOČENÁ", specification.words[0].answer)

    def test_rejects_word_outside_specification_grid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "word-outside-grid.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 3}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 2, column: 2}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.words\[0\].*přesahuje"):
                load_crossword_specification(source)

    def test_rejects_conflicting_word_intersection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "conflicting-intersection.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 3}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 2, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "  - answer: AX\n"
                "    start: {row: 2, column: 2}\n"
                "    direction: vertical\n"
                "    legend: Zkratka\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.words\[1\].*v rozporu"):
                load_crossword_specification(source)

    def test_rejects_help_position_occupied_by_word(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "occupied-help.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 3, height: 3}\n"
                "words:\n"
                "  - answer: ABC\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Abeceda\n"
                "    in_help: true\n"
                "help:\n"
                "  position: {row: 1, column: 2}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.help\.position"):
                load_crossword_specification(source)

    def test_rejects_automatic_help_without_empty_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "full-grid.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: specification\n"
                "version: 1\n"
                "grid: {width: 1, height: 1}\n"
                "words:\n"
                "  - answer: A\n"
                "    start: {row: 1, column: 1}\n"
                "    direction: horizontal\n"
                "    legend: Písmeno\n"
                "    in_help: true\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, "nemá prázdnou buňku"):
                load_crossword_specification(source)

    def test_loads_secret_cells(self) -> None:
        crossword = load_crossword_grid(GRID_SECRET_EXAMPLE)

        assert crossword.grid.cells is not None
        secret_cells = crossword.grid.cells[3][2:9]
        self.assertTrue(all(isinstance(cell, SecretCell) for cell in secret_cells))
        self.assertEqual("TAJENKA", "".join(cell.value for cell in secret_cells))

    def test_loads_and_writes_secret_cell_arrows(self) -> None:
        crossword = load_crossword_grid(GRID_SECRET_ARROWS_EXAMPLE)

        assert crossword.grid.cells is not None
        self.assertEqual("right", crossword.grid.cells[1][1].arrow)
        self.assertEqual("down", crossword.grid.cells[1][3].arrow)
        self.assertEqual("left", crossword.grid.cells[3][3].arrow)
        self.assertIsNone(crossword.grid.cells[3][2].arrow)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "secret-arrows.yaml"
            write_crossword_grid(crossword, output)
            self.assertEqual(crossword, load_crossword_grid(output))

    def test_rejects_secret_arrow_on_regular_letter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "letter-arrow.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: A, arrow: right}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.grid\.cells\[0\]\[0\]"):
                load_crossword_grid(source)

    def test_loads_single_and_double_legend(self) -> None:
        crossword = load_crossword_grid(GRID_LEGEND_EXAMPLE)

        assert crossword.grid.cells is not None
        single = crossword.grid.cells[0][0]
        double = crossword.grid.cells[2][3]
        self.assertIsInstance(single, LegendCell)
        self.assertIsInstance(double, LegendCell)
        assert isinstance(single, LegendCell)
        assert isinstance(double, LegendCell)
        self.assertEqual(("Nejzajímavější v Československu",), single.texts)
        self.assertEqual(("Savec", "Pohoří"), double.texts)

    def test_loads_legend_with_arrows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legend-arrow.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: legend, texts: [Legenda], arrows: [right]}]\n",
                encoding="utf-8",
            )

            crossword = load_crossword_grid(source)

            assert crossword.grid.cells is not None
            legend = crossword.grid.cells[0][0]
            self.assertIsInstance(legend, LegendCell)
            assert isinstance(legend, LegendCell)
            self.assertEqual(("right",), legend.arrows)

    def test_loads_and_writes_unfilled_grid_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unfilled.yaml"
            output = Path(directory) / "written.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 3\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter}, {type: secret}, {type: legend}]\n",
                encoding="utf-8",
            )

            crossword = load_crossword_grid(source)
            write_crossword_grid(crossword, output)

            assert crossword.grid.cells is not None
            letter, secret, legend = crossword.grid.cells[0]
            self.assertIsNone(letter.value)
            self.assertIsNone(secret.value)
            self.assertFalse(legend.texts)
            self.assertEqual(crossword, load_crossword_grid(output))
            written = output.read_text(encoding="utf-8")
            self.assertNotIn("value:", written)
            self.assertNotIn("texts:", written)

    def test_unfilled_legend_rejects_arrows_without_texts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unfilled-legend-arrow.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: legend, arrows: [right]}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, "vyžaduje také klíč 'texts'"):
                load_crossword_grid(source)

    def test_rejects_unknown_legend_arrow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unknown-legend-arrow.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: legend, texts: [Legenda], arrows: [left]}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\.arrows\[0\]"):
                load_crossword_grid(source)

    def test_loads_empty_cells(self) -> None:
        crossword = load_crossword_grid(GRID_EMPTY_EXAMPLE)

        assert crossword.grid.cells is not None
        empty_cells = [
            cell
            for row in crossword.grid.cells
            for cell in row
            if isinstance(cell, EmptyCell)
        ]
        self.assertEqual(10, len(empty_cells))

    def test_writes_grid_that_can_be_loaded_again(self) -> None:
        crossword = load_crossword_grid(GRID_LEGEND_EXAMPLE)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "round-trip.yaml"

            written = write_crossword_grid(crossword, output)
            loaded = load_crossword_grid(written)

            self.assertEqual(crossword, loaded)
            with self.assertRaisesRegex(ModelError, "již existuje"):
                write_crossword_grid(crossword, output)
            write_crossword_grid(crossword, output, overwrite=True)

    def test_dumps_grid_to_text_stream(self) -> None:
        crossword = load_crossword_grid(GRID_LEGEND_EXAMPLE)
        output = io.StringIO()

        dump_crossword_grid(crossword, output)

        self.assertTrue(output.getvalue().startswith("format: krizovkar\n"))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "stream.yaml"
            source.write_text(output.getvalue(), encoding="utf-8")
            self.assertEqual(crossword, load_crossword_grid(source))

    def test_loads_help_cell(self) -> None:
        crossword = load_crossword_grid(GRID_HELP_EXAMPLE)

        assert crossword.grid.cells is not None
        help_cell = crossword.grid.cells[2][3]
        self.assertIsInstance(help_cell, HelpCell)
        assert isinstance(help_cell, HelpCell)
        self.assertEqual(("ARA", "EMU", "ÍRÁN"), help_cell.words)

    def test_grid_loader_rejects_specification(self) -> None:
        with self.assertRaises(ModelError) as caught:
            load_crossword_grid(SPECIFICATION_MINIMAL_EXAMPLE)

        message = str(caught.exception)
        self.assertIn("chybí povinný klíč 'grid'", message)
        self.assertIn("$.kind: očekává se hodnota 'grid'", message)
        self.assertNotIn("required property", message)
        self.assertNotIn("was expected", message)

    def test_rejects_non_positive_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 0\n"
                "  height: 10\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.grid\.width"):
                load_crossword_grid(source)

    def test_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "duplicate.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 15\n"
                "  width: 20\n"
                "  height: 10\n",
                encoding="utf-8",
            )

            with self.assertRaises(ModelError) as caught:
                load_crossword_grid(source)

        message = str(caught.exception)
        self.assertIn("řádek 6, sloupec 3", message)
        self.assertIn("duplicitní klíč", message)
        self.assertNotIn("duplicate key", message)

    def test_rejects_row_with_wrong_number_of_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "short-row.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 2\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: A}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"grid\.width"):
                load_crossword_grid(source)

    def test_rejects_invalid_letter_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid-letter.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: letter, value: AA}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ModelError, r"\$\.grid\.cells\[0\]\[0\]\.value"
            ):
                load_crossword_grid(source)

    def test_rejects_unknown_cell_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unknown-cell.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: unknown, value: A}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.grid\.cells\[0\]\[0\]\.type"):
                load_crossword_grid(source)

    def test_loads_legend_with_three_texts_and_mismatched_arrows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "long-legend.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: legend, texts: [První, Druhý, Třetí], "
                "arrows: [right]}]\n",
                encoding="utf-8",
            )

            crossword = load_crossword_grid(source)

            assert crossword.grid.cells is not None
            legend = crossword.grid.cells[0][0]
            self.assertIsInstance(legend, LegendCell)
            assert isinstance(legend, LegendCell)
            self.assertEqual(("První", "Druhý", "Třetí"), legend.texts)
            self.assertEqual(("right",), legend.arrows)

            output = Path(directory) / "round-trip.yaml"
            write_crossword_grid(crossword, output)
            self.assertEqual(crossword, load_crossword_grid(output))

    def test_rejects_content_in_empty_cell(self) -> None:
        invalid_contents = (
            "value: A",
            "texts: [Legenda]",
            "words: [Pomůcka]",
            "arrows: [right]",
            "number: 1",
            "bars: [right]",
        )
        for content in invalid_contents:
            with (
                self.subTest(content=content),
                tempfile.TemporaryDirectory() as directory,
            ):
                source = Path(directory) / "nonempty-empty-cell.yaml"
                source.write_text(
                    "format: krizovkar\n"
                    "kind: grid\n"
                    "version: 1\n"
                    "grid:\n"
                    "  width: 1\n"
                    "  height: 1\n"
                    "  cells:\n"
                    f"    - [{{type: empty, {content}}}]\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ModelError, r"\$\.grid\.cells\[0\]\[0\]"):
                    load_crossword_grid(source)

    def test_rejects_invalid_help_words(self) -> None:
        invalid_words = ("[]", '["   "]')
        for words in invalid_words:
            with (
                self.subTest(words=words),
                tempfile.TemporaryDirectory() as directory,
            ):
                source = Path(directory) / "invalid-help.yaml"
                source.write_text(
                    "format: krizovkar\n"
                    "kind: grid\n"
                    "version: 1\n"
                    "grid:\n"
                    "  width: 1\n"
                    "  height: 1\n"
                    "  cells:\n"
                    f"    - [{{type: help, words: {words}}}]\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    ModelError, r"\$\.grid\.cells\[0\]\[0\]\.words"
                ):
                    load_crossword_grid(source)

    def test_rejects_help_without_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "help-without-words.yaml"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: help}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ModelError, r"\$\.grid\.cells\[0\]\[0\]"):
                load_crossword_grid(source)


class CommandTest(unittest.TestCase):
    def setUp(self) -> None:
        compiler = patch(
            "krizovkar.renderer._run_lualatex",
            side_effect=_fake_lualatex,
        )
        compiler.start()
        self.addCleanup(compiler.stop)

    def test_help_is_in_czech(self) -> None:
        cases = (
            (["--help"], ("volby:", "příkazy:")),
            (["fill", "--help"], ("poziční argumenty:", "volby:")),
        )
        for arguments, expected_sections in cases:
            with self.subTest(arguments=arguments):
                stdout = io.StringIO()

                with (
                    redirect_stdout(stdout),
                    self.assertRaises(SystemExit) as caught,
                ):
                    main(arguments)

                self.assertEqual(0, caught.exception.code)
                help_text = stdout.getvalue()
                self.assertTrue(help_text.startswith("použití: krizovkar"))
                self.assertIn("zobrazí tuto nápovědu a skončí", help_text)
                for section in expected_sections:
                    self.assertIn(section, help_text)
                for english_text in (
                    "usage:",
                    "positional arguments:",
                    "options:",
                    "show this help message and exit",
                ):
                    self.assertNotIn(english_text, help_text)

    def test_help_uses_crossword_terminology(self) -> None:
        for command in (
            None,
            "crossword",
            "grid",
            "fill",
            "generate",
            "validate",
            "latex",
            "render",
        ):
            arguments = ["--help"] if command is None else [command, "--help"]
            with self.subTest(command=command):
                stdout = io.StringIO()

                with redirect_stdout(stdout), self.assertRaises(SystemExit):
                    main(arguments)

                self.assertNotIn("šablon", stdout.getvalue().lower())

    def test_argument_errors_are_in_czech(self) -> None:
        cases = (
            (["render"], "je nutné zadat: VSTUP.yaml"),
            (["latex"], "je nutné zadat: VSTUP.yaml"),
            (
                ["render", str(GRID_MINIMAL_EXAMPLE), "--page-format", "A7"],
                "neplatná volba: 'A7'",
            ),
            (["crossword", "--width", "slovo"], "neplatná hodnota typu int"),
            (
                ["crossword", "--secret", "ABC", "--secret-part", "DEF"],
                "nelze použít společně s argumentem --secret",
            ),
            (["crossword", "--neznamy"], "nerozpoznané argumenty: --neznamy"),
            (["neznamy"], "argument příkaz: neplatná volba: 'neznamy'"),
        )
        for arguments, expected_message in cases:
            with self.subTest(arguments=arguments):
                stderr = io.StringIO()

                with (
                    redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as caught,
                ):
                    main(arguments)

                self.assertEqual(2, caught.exception.code)
                error_text = stderr.getvalue()
                self.assertTrue(error_text.startswith("použití: krizovkar"))
                self.assertIn("chyba:", error_text)
                self.assertIn(expected_message, error_text)
                for english_text in (
                    "usage:",
                    "error:",
                    "required:",
                    "invalid choice:",
                    "invalid int value:",
                    "not allowed with argument",
                    "unrecognized arguments:",
                ):
                    self.assertNotIn(english_text, error_text)

    def test_missing_input_file_error_is_in_czech(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "neexistuje.yaml"
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                result = main(["render", str(source)])

        self.assertEqual(2, result)
        error_text = stderr.getvalue()
        self.assertIn("soubor nebo adresář neexistuje", error_text)
        self.assertNotIn("No such file or directory", error_text)

    def test_validate_reads_grid_from_stdin(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        grid_yaml = GRID_MINIMAL_EXAMPLE.read_text(encoding="utf-8")

        with (
            patch("sys.stdin", io.StringIO(grid_yaml)),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(["validate", "-"])

        self.assertEqual(0, result)
        self.assertIn("standardní vstup", stdout.getvalue())
        self.assertIn("varování [grid.unfinished]", stderr.getvalue())

    def test_crossword_writes_yaml_to_stdout_without_output(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "crossword",
                    "--width",
                    "5",
                    "--height",
                    "5",
                ]
            )

        self.assertEqual(0, result)
        self.assertTrue(stdout.getvalue().startswith("format: krizovkar\n"))
        self.assertIn("kind: crossword\n", stdout.getvalue())
        self.assertNotIn("Křížovka vytvořena", stdout.getvalue())
        self.assertIn("Křížovka vytvořena: standardní výstup", stderr.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "crossword.yaml"
            source.write_text(stdout.getvalue(), encoding="utf-8")
            crossword = load_crossword_document(source)
            self.assertEqual(5, crossword.grid.width)
            self.assertEqual(5, crossword.grid.height)

    def test_crossword_converts_swedish_specification(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "crossword",
                    str(SPECIFICATION_PLACED_WORDS_EXAMPLE),
                    "--layout",
                    "swedish",
                ]
            )

        self.assertEqual(0, result)
        crossword = load_crossword_document(io.StringIO(stdout.getvalue()))
        self.assertEqual(("LABE", "LES", "EMU"), tuple(
            slot.answer for slot in crossword.slots
        ))
        self.assertTrue(
            all(slot.legend_position is not None for slot in crossword.slots)
        )
        self.assertIn("(7 × 6, 3 hesla)", stderr.getvalue())

    def test_crossword_reads_numbered_specification_from_stdin(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        specification_yaml = SPECIFICATION_SECRET_PROMPT_EXAMPLE.read_text(
            encoding="utf-8"
        )

        with (
            patch("sys.stdin", io.StringIO(specification_yaml)),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(["crossword", "-", "--layout", "numbered"])

        self.assertEqual(0, result)
        crossword = load_crossword_document(io.StringIO(stdout.getvalue()))
        self.assertEqual("ZELENÍ", crossword.slots[0].answer)
        self.assertIsNone(crossword.slots[0].legend_position)
        self.assertIn("standardní výstup", stderr.getvalue())

    def test_crossword_rejects_dense_options_with_specification(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            result = main(
                [
                    "crossword",
                    str(SPECIFICATION_PLACED_WORDS_EXAMPLE),
                    "--width",
                    "7",
                ]
            )

        self.assertEqual(2, result)
        self.assertIn(
            "při převodu zadání nelze použít",
            stderr.getvalue(),
        )

    def test_grid_writes_unfilled_yaml_to_stdout(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["grid", str(CROSSWORD_SECRET_EXAMPLE)])

        self.assertEqual(0, result)
        self.assertTrue(stdout.getvalue().startswith("format: krizovkar\n"))
        self.assertNotIn("Mřížka z křížovky vytvořena", stdout.getvalue())
        self.assertIn(
            "Mřížka z křížovky vytvořena: standardní výstup",
            stderr.getvalue(),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "grid.yaml"
            source.write_text(stdout.getvalue(), encoding="utf-8")
            crossword = load_crossword_grid(source)

        assert crossword.grid.cells is not None
        self.assertTrue(
            all(isinstance(cell, SecretCell) for cell in crossword.grid.cells[0])
        )
        self.assertTrue(
            all(cell.value is None for cell in crossword.grid.cells[0])
        )
        self.assertEqual(1, crossword.grid.cells[0][0].number)
        self.assertEqual(1, len(crossword.secret_prompts))

    def test_pipes_crossword_through_grid_to_pdf(self) -> None:
        crossword_stdout = io.StringIO()
        crossword_stderr = io.StringIO()
        with redirect_stdout(crossword_stdout), redirect_stderr(crossword_stderr):
            crossword_result = main(
                ["crossword", "--width", "5", "--height", "5"]
            )

        grid_stdout = io.StringIO()
        grid_stderr = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(crossword_stdout.getvalue())),
            redirect_stdout(grid_stdout),
            redirect_stderr(grid_stderr),
        ):
            grid_result = main(["grid", "-"])

        pdf_stdout = _BinaryStdout()
        render_stderr = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(grid_stdout.getvalue())),
            redirect_stdout(pdf_stdout),
            redirect_stderr(render_stderr),
        ):
            render_result = main(["render", "-"])

        self.assertEqual(0, crossword_result)
        self.assertEqual(0, grid_result)
        self.assertEqual(0, render_result)
        self.assertTrue(pdf_stdout.buffer.getvalue().startswith(b"%PDF-"))
        self.assertIn("standardní výstup", crossword_stderr.getvalue())
        self.assertIn("standardní výstup", grid_stderr.getvalue())
        self.assertIn("standardní výstup", render_stderr.getvalue())

    def test_render_reads_crossword_directly_from_stdin(self) -> None:
        stdout = _BinaryStdout()
        stderr = io.StringIO()
        crossword_yaml = CROSSWORD_SECRET_EXAMPLE.read_text(encoding="utf-8")

        with (
            patch("sys.stdin", io.StringIO(crossword_yaml)),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(["render", "-"])

        self.assertEqual(0, result)
        self.assertTrue(stdout.buffer.getvalue().startswith(b"%PDF-"))
        self.assertIn("PDF vytvořeno: standardní výstup", stderr.getvalue())

    def test_fill_accepts_stdin_for_either_input(self) -> None:
        crossword_yaml = CROSSWORD_SECRET_EXAMPLE.read_text(encoding="utf-8")
        dictionary_json = json.dumps(
            {"LES": ["Porost stromů"]},
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            dictionary = Path(directory) / "dictionary.json"
            dictionary.write_text(dictionary_json, encoding="utf-8")
            cases = (
                (["fill", "-", str(dictionary)], crossword_yaml),
                (["fill", str(CROSSWORD_SECRET_EXAMPLE), "-"], dictionary_json),
            )
            for arguments, standard_input in cases:
                with self.subTest(arguments=arguments):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        patch("sys.stdin", io.StringIO(standard_input)),
                        redirect_stdout(stdout),
                        redirect_stderr(stderr),
                    ):
                        result = main(arguments)

                    self.assertEqual(0, result)
                    self.assertTrue(
                        stdout.getvalue().startswith("format: krizovkar\n")
                    )

    def test_fill_rejects_stdin_for_both_inputs(self) -> None:
        stderr = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO()),
            redirect_stderr(stderr),
        ):
            result = main(["fill", "-", "-"])

        self.assertEqual(2, result)
        self.assertIn("zároveň pro křížovku i slovník", stderr.getvalue())

    def test_fill_writes_yaml_to_stdout_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dictionary = Path(directory) / "dictionary.json"
            dictionary.write_text(
                json.dumps({"LES": ["Porost stromů"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(
                    [
                        "fill",
                        str(CROSSWORD_SECRET_EXAMPLE),
                        str(dictionary),
                    ]
                )

            self.assertEqual(0, result)
            self.assertTrue(stdout.getvalue().startswith("format: krizovkar\n"))
            self.assertNotIn("Mřížka vytvořena", stdout.getvalue())
            self.assertIn(
                "Mřížka vytvořena: standardní výstup "
                "(6 × 1, 1 heslo, seed 0)",
                stderr.getvalue(),
            )
            source = Path(directory) / "grid.yaml"
            source.write_text(stdout.getvalue(), encoding="utf-8")
            crossword = load_crossword_grid(source)
            assert crossword.grid.cells is not None
            self.assertEqual(
                "ZELENÍ",
                "".join(cell.value for cell in crossword.grid.cells[0]),
            )

    def test_generate_writes_yaml_to_stdout_without_output(self) -> None:
        answers = tuple(
            "".join(letters) for letters in product("ABCD", repeat=4)
        )
        with tempfile.TemporaryDirectory() as directory:
            dictionary = Path(directory) / "dictionary.json"
            dictionary.write_text(
                json.dumps(
                    {
                        answer: [f"Legenda {answer}"]
                        for answer in answers
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(
                    [
                        "generate",
                        str(dictionary),
                        "--width",
                        "5",
                        "--height",
                        "5",
                    ]
                )

            self.assertEqual(0, result)
            self.assertTrue(stdout.getvalue().startswith("format: krizovkar\n"))
            self.assertNotIn("Mřížka vytvořena", stdout.getvalue())
            self.assertIn(
                "Mřížka vytvořena: standardní výstup "
                "(5 × 5, 8 hesel, seed 0)",
                stderr.getvalue(),
            )
            source = Path(directory) / "grid.yaml"
            source.write_text(stdout.getvalue(), encoding="utf-8")
            crossword = load_crossword_grid(source)
            self.assertEqual(5, crossword.grid.width)
            self.assertEqual(5, crossword.grid.height)

    def test_generate_reads_dictionary_from_stdin(self) -> None:
        answers = tuple(
            "".join(letters) for letters in product("ABCD", repeat=4)
        )
        dictionary_json = json.dumps(
            {answer: [f"Legenda {answer}"] for answer in answers}
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch("sys.stdin", io.StringIO(dictionary_json)),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(
                ["generate", "-", "--width", "5", "--height", "5"]
            )

        self.assertEqual(0, result)
        self.assertTrue(stdout.getvalue().startswith("format: krizovkar\n"))

    def test_generate_creates_complete_grid_with_secret(self) -> None:
        answers = tuple(
            "".join(letters) for letters in product("ABCD", repeat=4)
        )
        with tempfile.TemporaryDirectory() as directory:
            dictionary = Path(directory) / "dictionary.json"
            output = Path(directory) / "grid.yaml"
            dictionary.write_text(
                json.dumps(
                    {
                        answer: [f"Legenda {answer}"]
                        for answer in answers
                    }
                ),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "generate",
                        str(dictionary),
                        "--output",
                        str(output),
                        "--width",
                        "5",
                        "--height",
                        "5",
                        "--secret",
                        "ABCD",
                        "--secret-prompt",
                        "Doplňte tajenku",
                    ]
                )

            self.assertEqual(0, result)
            crossword = load_crossword_grid(output)
            assert crossword.grid.cells is not None
            self.assertEqual(
                4,
                sum(
                    isinstance(cell, SecretCell)
                    for row in crossword.grid.cells
                    for cell in row
                ),
            )
            self.assertEqual("Doplňte tajenku", crossword.secret_prompts[0].text)

    def test_crossword_reserves_known_secret_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossword.yaml"

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "crossword",
                        "--output",
                        str(output),
                        "--width",
                        "5",
                        "--height",
                        "5",
                        "--secret",
                        "ABCD",
                        "--secret-prompt",
                        "Doplňte tajenku",
                        "--secret-prompt-placement",
                        "below",
                        "--secret-prompt-alignment",
                        "right",
                        "--seed",
                        "8",
                    ]
                )

            self.assertEqual(0, result)
            crossword = load_crossword_document(output)
            self.assertEqual(1, len(crossword.secrets))
            self.assertEqual(("ABCD",), crossword.secrets[0].words)
            self.assertEqual(1, crossword.secrets[0].parts[0].word_count)
            assert crossword.secrets[0].prompt is not None
            self.assertEqual("below", crossword.secrets[0].prompt.placement)
            self.assertEqual("right", crossword.secrets[0].prompt.alignment)

    def test_fill_uses_secret_already_stored_in_crossword(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dictionary = Path(directory) / "dictionary.json"
            output = Path(directory) / "grid.yaml"
            dictionary.write_text(
                json.dumps({"LES": ["Porost stromů"]}, ensure_ascii=False),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "fill",
                        str(CROSSWORD_SECRET_EXAMPLE),
                        str(dictionary),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            crossword = load_crossword_grid(output)
            assert crossword.grid.cells is not None
            self.assertEqual(
                "ZELENÍ",
                "".join(cell.value for cell in crossword.grid.cells[0]),
            )
            self.assertTrue(
                all(isinstance(cell, SecretCell) for cell in crossword.grid.cells[0])
            )
            self.assertEqual(1, len(crossword.secret_prompts))

    def test_fill_creates_grid_from_crossword_and_dictionary(self) -> None:
        answers = tuple(
            "".join(letters) for letters in product("ABCD", repeat=4)
        )
        with tempfile.TemporaryDirectory() as directory:
            crossword_source = Path(directory) / "crossword.yaml"
            dictionary = Path(directory) / "dictionary.json"
            output = Path(directory) / "grid.yaml"
            dictionary.write_text(
                json.dumps(
                    {
                        answer: [f"Legenda {answer}"]
                        for answer in answers
                    }
                ),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "crossword",
                            "--output",
                            str(crossword_source),
                            "--width",
                            "5",
                            "--height",
                            "5",
                        ]
                    ),
                )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "fill",
                        str(crossword_source),
                        str(dictionary),
                        "--output",
                        str(output),
                        "--seed",
                        "42",
                    ]
                )

            self.assertEqual(0, result)
            self.assertIn("Mřížka vytvořena:", stdout.getvalue())
            crossword = load_crossword_grid(output)
            self.assertEqual(5, crossword.grid.width)
            self.assertEqual(5, crossword.grid.height)
            assert crossword.grid.cells is not None
            self.assertTrue(
                all(
                    isinstance(cell, (LetterCell, LegendCell, EmptyCell))
                    for row in crossword.grid.cells
                    for cell in row
                )
            )

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                second_result = main(
                    [
                        "fill",
                        str(crossword_source),
                        str(dictionary),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(2, second_result)
            self.assertIn("již existuje", stderr.getvalue())

    def test_crossword_creates_structure_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossword.yaml"
            command = [
                "crossword",
                "--output",
                str(output),
                "--width",
                "9",
                "--height",
                "9",
            ]

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(command)

            self.assertEqual(0, result)
            self.assertIn("Křížovka vytvořena:", stdout.getvalue())
            crossword = load_crossword_document(output)
            self.assertEqual(9, crossword.grid.width)
            self.assertEqual(9, crossword.grid.height)
            self.assertEqual(28, len(crossword.slots))

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                second_result = main(command)

            self.assertEqual(2, second_result)
            self.assertIn("již existuje", stderr.getvalue())

            with redirect_stdout(io.StringIO()):
                forced_result = main([*command, "--force"])

            self.assertEqual(0, forced_result)

    def test_crossword_creates_numbered_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "numbered-crossword.yaml"

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "crossword",
                        "--output",
                        str(output),
                        "--layout",
                        "numbered",
                        "--width",
                        "7",
                        "--height",
                        "7",
                    ]
                )

            self.assertEqual(0, result)
            crossword = load_crossword_document(output)
            self.assertEqual(28, len(crossword.slots))
            self.assertTrue(
                all(
                    isinstance(cell, LetterCellRole)
                    for row in crossword.grid.cells
                    for cell in row
                )
            )
            self.assertTrue(
                all(slot.legend_position is None for slot in crossword.slots)
            )

    def test_generate_creates_grid_and_refuses_accidental_overwrite(self) -> None:
        answers = tuple(
            "".join(letters) for letters in product("ABCD", repeat=4)
        )
        with tempfile.TemporaryDirectory() as directory:
            dictionary = Path(directory) / "dictionary.json"
            output = Path(directory) / "generated.yaml"
            dictionary.write_text(
                json.dumps(
                    {
                        answer: [f"Legenda {answer}"]
                        for answer in answers
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            command = [
                "generate",
                str(dictionary),
                "--output",
                str(output),
                "--width",
                "5",
                "--height",
                "5",
                "--seed",
                "42",
            ]

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(command)

            self.assertEqual(0, result)
            self.assertIn("Mřížka vytvořena:", stdout.getvalue())
            crossword = load_crossword_grid(output)
            self.assertEqual(5, crossword.grid.width)
            self.assertEqual(5, crossword.grid.height)
            self.assertNotIn("arrows:", output.read_text(encoding="utf-8"))

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                second_result = main(command)

            self.assertEqual(2, second_result)
            self.assertIn("již existuje", stderr.getvalue())

            with redirect_stdout(io.StringIO()):
                forced_result = main([*command, "--force"])

            self.assertEqual(0, forced_result)

    def test_generate_creates_numbered_grid(self) -> None:
        answers = tuple(
            "".join(letters)
            for length in (3, 4)
            for letters in product("ABCD", repeat=length)
        )
        with tempfile.TemporaryDirectory() as directory:
            dictionary = Path(directory) / "dictionary.json"
            output = Path(directory) / "numbered-grid.yaml"
            dictionary.write_text(
                json.dumps(
                    {
                        answer: [f"Legenda {answer}"]
                        for answer in answers
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "generate",
                        str(dictionary),
                        "--output",
                        str(output),
                        "--layout",
                        "numbered",
                        "--width",
                        "7",
                        "--height",
                        "7",
                        "--seed",
                        "42",
                        "--secret",
                        "ABCD",
                    ]
                )

            self.assertEqual(0, result)
            self.assertIn("28 hesel", stdout.getvalue())
            crossword = load_crossword_grid(output)
            self.assertEqual(28, len(crossword.clues))
            assert crossword.grid.cells is not None
            cells = tuple(
                cell for row in crossword.grid.cells for cell in row
            )
            self.assertTrue(
                all(isinstance(cell, (LetterCell, SecretCell)) for cell in cells)
            )
            self.assertEqual(
                4,
                sum(isinstance(cell, SecretCell) for cell in cells),
            )
            self.assertEqual(14, sum(len(cell.bars) for cell in cells))
            self.assertEqual(
                tuple(range(1, 25)),
                tuple(
                    cell.number
                    for cell in cells
                    if cell.number is not None
                ),
            )

    def test_page_format_names_are_case_insensitive(self) -> None:
        width, height = resolve_page_size("a5")

        self.assertAlmostEqual(148 * 72 / 25.4, width)
        self.assertAlmostEqual(210 * 72 / 25.4, height)

    def test_rejects_unsupported_page_format(self) -> None:
        with self.assertRaisesRegex(RenderError, "nepodporovaný formát stránky"):
            resolve_page_size("A7")

    def test_latex_writes_editable_source_to_stdout(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "latex",
                    str(GRID_CZECH_LETTERS_EXAMPLE),
                    "--page-format",
                    "A5",
                ]
            )

        self.assertEqual(0, result)
        source = stdout.getvalue()
        self.assertTrue(source.startswith("% Automaticky vytvořil Křížovkář."))
        self.assertIn(r"\documentclass[10pt]{article}", source)
        self.assertIn(r"\KrizovkarLetter{9.6mm}{CH}", source)
        self.assertIn("LaTeX vytvořen: standardní výstup", stderr.getvalue())

    def test_latex_accepts_editable_crossword_document(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["latex", str(CROSSWORD_MINIMAL_EXAMPLE)])

        self.assertEqual(0, result)
        self.assertIn(r"\KrizovkarLetter", stdout.getvalue())
        self.assertIn("LaTeX vytvořen: standardní výstup", stderr.getvalue())

    def test_latex_writes_file_and_refuses_accidental_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossword.tex"
            command = [
                "latex",
                str(GRID_SECRET_ARROWS_EXAMPLE),
                "--output",
                str(output),
                "--blank",
            ]

            with redirect_stdout(io.StringIO()):
                result = main(command)

            self.assertEqual(0, result)
            self.assertIn(r"\begin{tikzpicture}", output.read_text(encoding="utf-8"))
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                second_result = main(command)
            self.assertEqual(2, second_result)
            self.assertIn("již existuje", stderr.getvalue())
            with redirect_stdout(io.StringIO()):
                forced_result = main([*command, "--force"])
            self.assertEqual(0, forced_result)

    def test_render_creates_pdf_and_refuses_accidental_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossword.pdf"
            command = [
                "render",
                str(GRID_LEGEND_EXAMPLE),
                "--output",
                str(output),
                "--page-format",
                "A5",
            ]

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(command)

            self.assertEqual(0, result)
            self.assertIn("PDF vytvořeno:", stdout.getvalue())
            pdf = output.read_bytes()
            self.assertTrue(pdf.startswith(b"%PDF-"))
            self.assertIn(b"%%EOF", pdf[-1024:])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                second_result = main(command)

            self.assertEqual(2, second_result)
            self.assertIn("již existuje", stderr.getvalue())

            with redirect_stdout(io.StringIO()):
                forced_result = main([*command, "--force"])

            self.assertEqual(0, forced_result)

    def test_render_writes_pdf_to_stdout_without_output(self) -> None:
        stdout = _BinaryStdout()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "render",
                    str(GRID_LEGEND_EXAMPLE),
                    "--page-format",
                    "A5",
                ]
            )

        self.assertEqual(0, result)
        self.assertEqual("", stdout.getvalue())
        pdf = stdout.buffer.getvalue()
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf[-1024:])
        self.assertIn("PDF vytvořeno: standardní výstup", stderr.getvalue())

    def test_render_accepts_crossword_without_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossword.pdf"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = main(
                    [
                        "render",
                        str(CROSSWORD_SECRET_EXAMPLE),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            self.assertIn("PDF vytvořeno:", stdout.getvalue())
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))

    def test_render_handles_empty_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "empty-cells.pdf"

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "render",
                        str(GRID_EMPTY_EXAMPLE),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))

    def test_render_handles_help_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "help-cell.pdf"

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "render",
                        str(GRID_HELP_EXAMPLE),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))

    def test_render_handles_secret_cell_arrows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "secret-arrows.pdf"

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "render",
                        str(GRID_SECRET_ARROWS_EXAMPLE),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))

    def test_render_handles_secret_cell_arrows_in_blank_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "blank-secret-arrows.pdf"

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "render",
                        str(GRID_SECRET_ARROWS_EXAMPLE),
                        "--output",
                        str(output),
                        "--blank",
                    ]
                )

            self.assertEqual(0, result)
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))

    def test_render_handles_numbered_grid_filled_and_blank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for blank in (False, True):
                with self.subTest(blank=blank):
                    output = Path(directory) / f"classic-{blank}.pdf"
                    command = [
                        "render",
                        str(GRID_CLASSIC_EXAMPLE),
                        "--output",
                        str(output),
                    ]
                    if blank:
                        command.append("--blank")

                    with redirect_stdout(io.StringIO()):
                        result = main(command)

                    self.assertEqual(0, result)
                    self.assertTrue(output.read_bytes().startswith(b"%PDF-"))

    def test_render_handles_three_legend_texts_and_arrow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "three-legends.yaml"
            output = Path(directory) / "three-legends.pdf"
            source.write_text(
                "format: krizovkar\n"
                "kind: grid\n"
                "version: 1\n"
                "grid:\n"
                "  width: 1\n"
                "  height: 1\n"
                "  cells:\n"
                "    - [{type: legend, texts: [První, Druhý, Třetí], "
                "arrows: [right]}]\n",
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                result = main(["render", str(source), "--output", str(output)])

            self.assertEqual(0, result)
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))

    def test_render_handles_czech_letters_and_ch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "czech-letters.pdf"

            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "render",
                        str(GRID_CZECH_LETTERS_EXAMPLE),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()

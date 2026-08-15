"""Testy LaTeXové sazby a překladu PDF."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from krizovkar.model import (
    CrosswordGrid,
    Grid,
    LegendCell,
    LetterCell,
    SecretCell,
    SecretPrompt,
    load_crossword_grid,
)
from krizovkar.renderer import (
    RenderError,
    _run_lualatex,
    _secret_beak_points,
    _secret_letter_center,
    create_latex_source,
    render_latex,
    render_latex_stream,
    render_pdf,
    render_pdf_stream,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRID_CLASSIC_EXAMPLE = PROJECT_ROOT / "examples" / "grid-classic.yaml"
GRID_CZECH_LETTERS_EXAMPLE = PROJECT_ROOT / "examples" / "grid-czech-letters.yaml"
GRID_EMPTY_EXAMPLE = PROJECT_ROOT / "examples" / "grid-empty.yaml"
GRID_HELP_EXAMPLE = PROJECT_ROOT / "examples" / "grid-help.yaml"
GRID_LEGEND_EXAMPLE = PROJECT_ROOT / "examples" / "grid-legend.yaml"
GRID_MIXED_CLUES_EXAMPLE = PROJECT_ROOT / "examples" / "grid-mixed-clues.yaml"
GRID_SECRET_ARROWS_EXAMPLE = PROJECT_ROOT / "examples" / "grid-secret-arrows.yaml"
GRID_SECRET_PROMPT_EXAMPLE = PROJECT_ROOT / "examples" / "grid-secret-prompt.yaml"
PDF_BYTES = b"%PDF-1.7\n%%EOF\n"


def _fake_lualatex(source: Path, output_directory: Path) -> Path:
    assert source.read_text(encoding="utf-8").startswith(
        "% Automaticky vytvořil Křížovkář."
    )
    output = output_directory / f"{source.stem}.pdf"
    output.write_bytes(PDF_BYTES)
    return output


class LatexSourceTest(unittest.TestCase):
    def test_source_is_standalone_lualatex_document(self) -> None:
        crossword = load_crossword_grid(GRID_SECRET_PROMPT_EXAMPLE)

        source = create_latex_source(crossword, page_format="a5")

        self.assertIn(r"\documentclass[10pt]{article}", source)
        self.assertIn("paperwidth=148mm,paperheight=210mm", source)
        self.assertIn(r"\usepackage{fontspec}", source)
        self.assertIn("lmsans10-regular.otf", source)
        self.assertIn("lmsans10-bold.otf", source)
        self.assertIn(r"\usepackage{tikz}", source)
        self.assertIn(r"\begin{document}", source)
        self.assertTrue(source.endswith("\\end{document}\n"))
        self.assertIn("lualatex -interaction=nonstopmode", source)

    def test_filled_and_blank_sources_share_layout_but_not_letters(self) -> None:
        crossword = load_crossword_grid(GRID_SECRET_ARROWS_EXAMPLE)

        filled = create_latex_source(crossword)
        blank = create_latex_source(crossword, filled=False)

        self.assertEqual(25, filled.count(r"\KrizovkarLetter{"))
        self.assertNotIn(r"\KrizovkarLetter{9.6mm}", blank)
        for source in (filled, blank):
            self.assertEqual(7, source.count(r"\fill[black!15]"))
            self.assertIn(r"\fill (1,3.91) -- (1.28,3.5)", source)
            self.assertIn(r"line width=1.25pt", source)

    def test_source_contains_legend_help_and_empty_cell_sazba(self) -> None:
        legend = create_latex_source(load_crossword_grid(GRID_LEGEND_EXAMPLE))
        help_source = create_latex_source(load_crossword_grid(GRID_HELP_EXAMPLE))
        empty = create_latex_source(load_crossword_grid(GRID_EMPTY_EXAMPLE))

        self.assertIn(r"\fill[black!7]", legend)
        self.assertIn(r"\KrizovkarCellText", legend)
        self.assertIn(r"\textbf{Pomůcka:}", help_source)
        self.assertEqual(20, empty.count(r"\draw[gray!70,line width=0.65pt]"))

    def test_numbered_source_keeps_numbers_bars_and_both_clue_columns(self) -> None:
        crossword = load_crossword_grid(GRID_CLASSIC_EXAMPLE)

        source = create_latex_source(crossword, filled=False)

        self.assertIn(r"\textbf{Vodorovně}", source)
        self.assertIn(r"\textbf{Svisle}", source)
        self.assertIn(r"\textbf{20.}", source)
        self.assertIn("font=\\bfseries\\fontsize{7pt}{7pt}", source)
        self.assertEqual(12, source.count(r"line width=1.25pt] (") - 1)
        self.assertNotIn(r"\KrizovkarLetter{9.6mm}", source)

    def test_inline_and_numbered_clues_can_share_one_source(self) -> None:
        crossword = load_crossword_grid(GRID_MIXED_CLUES_EXAMPLE)

        source = create_latex_source(crossword, filled=False)

        self.assertEqual(6, source.count(r"\fill[black!7]"))
        self.assertIn("% Vnější číslované legendy", source)

    def test_prompt_order_placement_and_alignment_are_explicit(self) -> None:
        crossword = CrosswordGrid(
            format_name="krizovkar",
            kind="grid",
            version=1,
            grid=Grid(width=1, height=1, cells=((LetterCell(value="A"),),)),
            secret_prompts=(
                SecretPrompt("První nahoře", alignment="left"),
                SecretPrompt("Druhé nahoře", alignment="right"),
                SecretPrompt("Dole", placement="below", alignment="right"),
            ),
        )

        source = create_latex_source(crossword)

        first = source.index("Prv")
        second = source.index("Dru")
        grid = source.index("% Křížovková mřížka")
        below = source.index("% Zadání tajenky pod mřížkou")
        self.assertLess(first, second)
        self.assertLess(second, grid)
        self.assertLess(grid, below)
        self.assertIn(r"{\raggedright", source)
        self.assertIn(r"{\raggedleft", source)

    def test_user_text_is_escaped_instead_of_becoming_latex(self) -> None:
        crossword = CrosswordGrid(
            format_name="krizovkar",
            kind="grid",
            version=1,
            grid=Grid(
                width=2,
                height=1,
                cells=(
                    (
                        LegendCell(texts=(r'50%_# & \ {x} "citace" `',)),
                        LetterCell(),
                    ),
                ),
            ),
        )

        source = create_latex_source(crossword)

        self.assertIn(
            r"50\%\_\# \& \textbackslash{} \{x\}",
            source,
        )
        self.assertEqual(2, source.count(r"\textquotedbl{}"))
        self.assertIn(r"\textasciigrave{}", source)

    def test_czech_letters_and_ch_remain_unicode(self) -> None:
        crossword = load_crossword_grid(GRID_CZECH_LETTERS_EXAMPLE)

        source = create_latex_source(crossword)

        self.assertIn(r"\KrizovkarLetter{9.6mm}{CH}", source)
        self.assertIn(r"\KrizovkarLetter{9.6mm}{Č}", source)


class SecretBeakTest(unittest.TestCase):
    def test_beak_starts_on_opposite_edge_and_points_in_direction(self) -> None:
        cases = {
            "up": ((50, 28), 1, 0),
            "right": ((28, 50), 0, 0),
            "down": ((50, 72), 1, 100),
            "left": ((72, 50), 0, 100),
        }

        for direction, (expected_tip, edge_axis, edge_value) in cases.items():
            with self.subTest(direction=direction):
                base_start, tip, base_end = _secret_beak_points(
                    direction,
                    0,
                    0,
                    100,
                )

                for actual, expected in zip(tip, expected_tip, strict=True):
                    self.assertAlmostEqual(expected, actual)
                self.assertAlmostEqual(edge_value, base_start[edge_axis])
                self.assertAlmostEqual(edge_value, base_end[edge_axis])

    def test_numbered_beak_avoids_upper_left_number(self) -> None:
        right_points = _secret_beak_points(
            "right",
            0,
            0,
            100,
            numbered=True,
        )
        down_points = _secret_beak_points(
            "down",
            0,
            0,
            100,
            numbered=True,
        )

        self.assertLessEqual(max(point[1] for point in right_points), 55)
        self.assertGreaterEqual(min(point[0] for point in down_points), 45)

    def test_secret_letter_moves_away_from_beak_base(self) -> None:
        self.assertEqual((50, 60), _secret_letter_center("up", 50, 50, 100))
        self.assertEqual((60, 50), _secret_letter_center("right", 50, 50, 100))
        self.assertEqual((50, 40), _secret_letter_center("down", 50, 50, 100))
        self.assertEqual((40, 50), _secret_letter_center("left", 50, 50, 100))


class LatexOutputTest(unittest.TestCase):
    crossword = CrosswordGrid(
        format_name="krizovkar",
        kind="grid",
        version=1,
        grid=Grid(width=1, height=1, cells=((LetterCell(value="A"),),)),
    )

    def test_writes_latex_file_atomically_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossword.tex"

            returned = render_latex(self.crossword, output)

            self.assertEqual(output, returned)
            self.assertIn(r"\begin{document}", output.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(RenderError, "již existuje"):
                render_latex(self.crossword, output)
            render_latex(self.crossword, output, overwrite=True, filled=False)

    def test_writes_latex_to_text_stream_without_closing_it(self) -> None:
        output = StringIO()

        render_latex_stream(self.crossword, output)

        self.assertIn(r"\end{document}", output.getvalue())
        self.assertFalse(output.closed)

    def test_reports_text_stream_without_utf8_support(self) -> None:
        class AsciiStream:
            def write(self, content: str) -> None:
                content.encode("ascii")

        with self.assertRaisesRegex(RenderError, "UTF-8"):
            render_latex_stream(self.crossword, AsciiStream())  # type: ignore[arg-type]


class PdfCompilationTest(unittest.TestCase):
    crossword = CrosswordGrid(
        format_name="krizovkar",
        kind="grid",
        version=1,
        grid=Grid(width=1, height=1, cells=((SecretCell(value="A"),),)),
    )

    def test_render_pdf_compiles_generated_latex_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "crossword.pdf"
            with patch(
                "krizovkar.renderer._run_lualatex",
                side_effect=_fake_lualatex,
            ) as compiler:
                returned = render_pdf(self.crossword, output)

            self.assertEqual(output, returned)
            self.assertEqual(PDF_BYTES, output.read_bytes())
            compiler.assert_called_once()
            with self.assertRaisesRegex(RenderError, "již existuje"):
                render_pdf(self.crossword, output)

    def test_render_pdf_stream_keeps_binary_stream_open(self) -> None:
        output = BytesIO()
        with patch(
            "krizovkar.renderer._run_lualatex",
            side_effect=_fake_lualatex,
        ):
            render_pdf_stream(self.crossword, output)

        self.assertEqual(PDF_BYTES, output.getvalue())
        self.assertFalse(output.closed)

    def test_lualatex_is_called_without_shell_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tex"
            source.write_text(r"\documentclass{article}", encoding="utf-8")

            def fake_run(command, **kwargs):
                (root / "source.pdf").write_bytes(PDF_BYTES)
                return subprocess.CompletedProcess(command, 0, "hotovo")

            with patch(
                "krizovkar.renderer.subprocess.run",
                side_effect=fake_run,
            ) as run:
                output = _run_lualatex(source, root)

        self.assertEqual("source.pdf", output.name)
        command = run.call_args.args[0]
        self.assertEqual("lualatex", command[0])
        self.assertIn("-no-shell-escape", command)
        self.assertIn("-halt-on-error", command)
        self.assertEqual(root, run.call_args.kwargs["cwd"])
        self.assertEqual(subprocess.DEVNULL, run.call_args.kwargs["stdin"])

    def test_missing_lualatex_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tex"
            source.write_text("", encoding="utf-8")
            with (
                patch(
                    "krizovkar.renderer.subprocess.run",
                    side_effect=FileNotFoundError,
                ),
                self.assertRaisesRegex(RenderError, "nainstalujte TeX Live"),
            ):
                _run_lualatex(source, root)

    def test_lualatex_error_includes_compiler_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tex"
            source.write_text("", encoding="utf-8")
            failed = subprocess.CompletedProcess(
                ("lualatex",),
                1,
                "začátek\n! LaTeX Error: chybí balíček\nkonec",
            )
            with (
                patch("krizovkar.renderer.subprocess.run", return_value=failed),
                self.assertRaisesRegex(RenderError, "chybí balíček"),
            ):
                _run_lualatex(source, root)


if __name__ == "__main__":
    unittest.main()

"""Testy sazby a obsahových režimů PDF rendereru."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle

from krizovkar.model import (
    CrosswordGrid,
    EmptyCell,
    ExternalClue,
    Grid,
    LegendCell,
    LetterCell,
    SecretCell,
    SecretPrompt,
    load_crossword_grid,
)
from krizovkar.renderer import (
    INNER_LINE_WIDTH,
    MAX_CELL_SIZE,
    TEXT_CELL_FONT_STEP,
    TEXT_CELL_MAX_FONT_SIZE,
    TEXT_CELL_PADDING,
    STRONG_LINE_WIDTH,
    _draw_cell_number,
    _draw_external_clues,
    _draw_fitted_text,
    _draw_inner_grid_lines,
    _draw_legend_cell,
    _draw_letter_cell,
    _draw_secret_beak,
    _draw_secret_prompts,
    _draw_strong_grid_lines,
    _secret_beak_points,
    _secret_letter_center,
    render_pdf,
)
from krizovkar.typography import SOFT_HYPHEN

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRID_CLASSIC_EXAMPLE = PROJECT_ROOT / "examples" / "grid-classic.yaml"
GRID_MIXED_CLUES_EXAMPLE = PROJECT_ROOT / "examples" / "grid-mixed-clues.yaml"
GRID_SECRET_PROMPT_EXAMPLE = PROJECT_ROOT / "examples" / "grid-secret-prompt.yaml"


class FittedTextTest(unittest.TestCase):
    cell_text_size = MAX_CELL_SIZE - 2 * TEXT_CELL_PADDING

    def _rendered_content(self, text: str) -> tuple[str, ParagraphStyle]:
        with patch("krizovkar.renderer.Paragraph") as paragraph_type:
            paragraph = paragraph_type.return_value
            paragraph.wrap.return_value = (self.cell_text_size, 12.6)

            _draw_fitted_text(
                Mock(),
                text,
                0,
                0,
                self.cell_text_size,
                self.cell_text_size,
            )

        content, style = paragraph_type.call_args.args
        return content, style

    def test_keeps_words_that_fit_on_their_own_line_whole(self) -> None:
        for text in ("NÁŠ REŽISÉR", "RUSKY TEDY", "ANGL. KOPEC"):
            with self.subTest(text=text):
                content, style = self._rendered_content(text)

                self.assertNotIn(SOFT_HYPHEN, content)
                self.assertFalse(style.hyphenationLang)

    def test_keeps_dictionary_hyphenation_for_an_overlong_word(self) -> None:
        content, _ = self._rendered_content("NEJZAJÍMAVĚJŠÍ")

        self.assertIn(SOFT_HYPHEN, content)

    def test_slightly_shrinks_font_to_keep_words_whole(self) -> None:
        content, style = self._rendered_content("ODDĚLENÍ TECHNICKÉ KONTROLY")

        self.assertNotIn(SOFT_HYPHEN, content)
        self.assertEqual(
            TEXT_CELL_MAX_FONT_SIZE - TEXT_CELL_FONT_STEP,
            style.fontSize,
        )


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

    def test_beak_is_a_filled_closed_triangle(self) -> None:
        pdf = Mock()
        path = pdf.beginPath.return_value

        _draw_secret_beak(pdf, "right", 0, 0, 100)

        path.moveTo.assert_called_once()
        self.assertEqual(2, path.lineTo.call_count)
        path.close.assert_called_once_with()
        pdf.setFillColorRGB.assert_called_once_with(0, 0, 0)
        pdf.drawPath.assert_called_once_with(path, stroke=0, fill=1)

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


class RenderModeTest(unittest.TestCase):
    crossword = CrosswordGrid(
        format_name="krizovkar",
        kind="grid",
        version=1,
        grid=Grid(
            width=2,
            height=2,
            cells=(
                (
                    LegendCell(texts=("Tajenka",)),
                    SecretCell(value="A", arrow="right"),
                ),
                (LetterCell(value="B"), EmptyCell()),
            ),
        ),
    )

    def test_filled_pdf_draws_letters_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "filled.pdf"
            with patch(
                "krizovkar.renderer._draw_letter_cell",
                wraps=_draw_letter_cell,
            ) as draw_letter:
                render_pdf(self.crossword, output)

        self.assertEqual(2, draw_letter.call_count)

    def test_blank_pdf_keeps_legend_and_secret_arrow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "blank.pdf"
            with (
                patch(
                    "krizovkar.renderer._draw_letter_cell",
                    wraps=_draw_letter_cell,
                ) as draw_letter,
                patch(
                    "krizovkar.renderer._draw_legend_cell",
                    wraps=_draw_legend_cell,
                ) as draw_legend,
                patch(
                    "krizovkar.renderer._draw_secret_beak",
                    wraps=_draw_secret_beak,
                ) as draw_secret_beak,
            ):
                render_pdf(self.crossword, output, filled=False)

        draw_letter.assert_not_called()
        draw_legend.assert_called_once()
        draw_secret_beak.assert_called_once()


class SecretPromptRenderTest(unittest.TestCase):
    def test_multiple_prompts_keep_top_to_bottom_order(self) -> None:
        pdf = Mock()
        first = Mock()
        second = Mock()

        _draw_secret_prompts(
            pdf,
            ((first, 10), (second, 20)),
            left=5,
            bottom=10,
            height=40,
        )

        first_y = first.drawOn.call_args.args[2]
        second_y = second.drawOn.call_args.args[2]
        self.assertEqual(5, first.drawOn.call_args.args[1])
        self.assertEqual(5, second.drawOn.call_args.args[1])
        self.assertGreater(first_y, second_y)

    def test_example_prompt_is_drawn_in_blank_pdf(self) -> None:
        crossword = load_crossword_grid(GRID_SECRET_PROMPT_EXAMPLE)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "secret-prompt-blank.pdf"
            with patch(
                "krizovkar.renderer._draw_secret_prompts",
                wraps=_draw_secret_prompts,
            ) as draw_prompts:
                render_pdf(crossword, output, filled=False)

        draw_prompts.assert_called_once()
        layouts = draw_prompts.call_args.args[1]
        self.assertEqual(TA_LEFT, layouts[0][0].style.alignment)

    def test_places_prompts_around_grid_and_above_external_clues(self) -> None:
        crossword = CrosswordGrid(
            format_name="krizovkar",
            kind="grid",
            version=1,
            grid=Grid(
                width=2,
                height=1,
                cells=(
                    (
                        LetterCell(value="A", number=1),
                        LetterCell(value="B"),
                    ),
                ),
            ),
            clues=(
                ExternalClue(
                    number=1,
                    direction="horizontal",
                    text="Abeceda",
                ),
            ),
            secret_prompts=(
                SecretPrompt(
                    text="Zadání nahoře",
                    placement="above",
                    alignment="left",
                ),
                SecretPrompt(
                    text="Zadání dole",
                    placement="below",
                    alignment="right",
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "secret-prompts.pdf"
            with (
                patch(
                    "krizovkar.renderer._draw_inner_grid_lines",
                    wraps=_draw_inner_grid_lines,
                ) as draw_grid,
                patch(
                    "krizovkar.renderer._draw_external_clues",
                    wraps=_draw_external_clues,
                ) as draw_clues,
                patch(
                    "krizovkar.renderer._draw_secret_prompts",
                    wraps=_draw_secret_prompts,
                ) as draw_prompts,
            ):
                render_pdf(crossword, output, filled=False)

        _, _, grid_left, grid_bottom, cell_size = draw_grid.call_args.args
        grid_width = crossword.grid.width * cell_size
        grid_top = grid_bottom + crossword.grid.height * cell_size

        self.assertEqual(2, draw_prompts.call_count)
        prompt_calls = {
            call.args[1][0][0].style.alignment: call.args
            for call in draw_prompts.call_args_list
        }
        _, below_layouts, below_left, below_bottom, below_height = (
            prompt_calls[TA_RIGHT]
        )
        _, above_layouts, above_left, above_bottom, _ = prompt_calls[TA_LEFT]

        self.assertAlmostEqual(grid_left, below_left)
        self.assertAlmostEqual(grid_left, above_left)
        self.assertAlmostEqual(grid_width, below_layouts[0][0].width)
        self.assertAlmostEqual(grid_width, above_layouts[0][0].width)
        self.assertLess(below_bottom + below_height, grid_bottom)
        self.assertGreater(above_bottom, grid_top)

        _, _, _, clue_bottom, clue_height = draw_clues.call_args.args
        self.assertLess(clue_bottom + clue_height, below_bottom)


class GridLineRenderTest(unittest.TestCase):
    def test_all_inner_row_and_column_lines_are_visible(self) -> None:
        grid = Grid(width=5, height=5)
        pdf = Mock()

        _draw_inner_grid_lines(pdf, grid, 0, 0, 10)

        pdf.setStrokeColorRGB.assert_called_once_with(0, 0, 0)
        pdf.setLineWidth.assert_called_once_with(INNER_LINE_WIDTH)
        self.assertEqual(8, pdf.line.call_count)
        pdf.line.assert_any_call(10, 0, 10, 50)
        pdf.line.assert_any_call(40, 0, 40, 50)
        pdf.line.assert_any_call(0, 10, 50, 10)
        pdf.line.assert_any_call(0, 40, 50, 40)
        self.assertLess(INNER_LINE_WIDTH, STRONG_LINE_WIDTH)

    def test_word_bars_and_outer_frame_share_strong_line_width(self) -> None:
        crossword = load_crossword_grid(GRID_CLASSIC_EXAMPLE)
        pdf = Mock()

        _draw_strong_grid_lines(pdf, crossword.grid, 0, 0, 10)

        pdf.setLineWidth.assert_called_once_with(STRONG_LINE_WIDTH)
        self.assertEqual(12, pdf.line.call_count)
        pdf.rect.assert_called_once_with(0, 0, 60, 60, stroke=1, fill=0)


class NumberedClueRenderTest(unittest.TestCase):
    def test_blank_numbered_pdf_keeps_numbers_clues_and_secret_arrow(self) -> None:
        crossword = load_crossword_grid(GRID_CLASSIC_EXAMPLE)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "classic-blank.pdf"
            with (
                patch(
                    "krizovkar.renderer._draw_letter_cell",
                    wraps=_draw_letter_cell,
                ) as draw_letter,
                patch(
                    "krizovkar.renderer._draw_cell_number",
                    wraps=_draw_cell_number,
                ) as draw_number,
                patch(
                    "krizovkar.renderer._draw_external_clues",
                    wraps=_draw_external_clues,
                ) as draw_clues,
                patch(
                    "krizovkar.renderer._draw_secret_beak",
                    wraps=_draw_secret_beak,
                ) as draw_secret_beak,
            ):
                render_pdf(crossword, output, filled=False)

        draw_letter.assert_not_called()
        self.assertEqual(20, draw_number.call_count)
        draw_clues.assert_called_once()
        draw_secret_beak.assert_called_once()
        self.assertTrue(draw_secret_beak.call_args.kwargs["numbered"])

    def test_inline_and_numbered_clues_are_drawn_together(self) -> None:
        crossword = load_crossword_grid(GRID_MIXED_CLUES_EXAMPLE)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "mixed.pdf"
            with (
                patch(
                    "krizovkar.renderer._draw_legend_cell",
                    wraps=_draw_legend_cell,
                ) as draw_inline_clue,
                patch(
                    "krizovkar.renderer._draw_cell_number",
                    wraps=_draw_cell_number,
                ) as draw_number,
                patch(
                    "krizovkar.renderer._draw_external_clues",
                    wraps=_draw_external_clues,
                ) as draw_external_clues,
            ):
                render_pdf(crossword, output, filled=False)

        self.assertEqual(6, draw_inline_clue.call_count)
        draw_number.assert_called_once()
        draw_external_clues.assert_called_once()


if __name__ == "__main__":
    unittest.main()

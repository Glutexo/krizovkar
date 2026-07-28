"""Testy sazby a obsahových režimů PDF rendereru."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from reportlab.lib.styles import ParagraphStyle

from krizovkar.model import (
    CrosswordGrid,
    EmptyCell,
    Grid,
    LegendCell,
    LetterCell,
    SecretCell,
    load_crossword_grid,
)
from krizovkar.renderer import (
    MAX_CELL_SIZE,
    TEXT_CELL_FONT_STEP,
    TEXT_CELL_MAX_FONT_SIZE,
    TEXT_CELL_PADDING,
    STRONG_LINE_WIDTH,
    _draw_cell_number,
    _draw_external_clues,
    _draw_fitted_text,
    _draw_legend_cell,
    _draw_letter_cell,
    _draw_secret_beak,
    _draw_strong_grid_lines,
    _secret_beak_points,
    _secret_letter_center,
    render_pdf,
)
from krizovkar.typography import SOFT_HYPHEN

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRID_CLASSIC_EXAMPLE = PROJECT_ROOT / "examples" / "grid-classic.yaml"
GRID_MIXED_CLUES_EXAMPLE = PROJECT_ROOT / "examples" / "grid-mixed-clues.yaml"


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


class NumberedClueRenderTest(unittest.TestCase):
    def test_word_bars_and_outer_frame_share_strong_line_width(self) -> None:
        crossword = load_crossword_grid(GRID_CLASSIC_EXAMPLE)
        pdf = Mock()

        _draw_strong_grid_lines(pdf, crossword.grid, 0, 0, 10)

        pdf.setLineWidth.assert_called_once_with(STRONG_LINE_WIDTH)
        self.assertEqual(12, pdf.line.call_count)
        pdf.rect.assert_called_once_with(0, 0, 60, 60, stroke=1, fill=0)

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

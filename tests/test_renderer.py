"""Testy sazby textu v PDF rendereru."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from reportlab.lib.styles import ParagraphStyle

from krizovkar.renderer import (
    MAX_CELL_SIZE,
    TEXT_CELL_FONT_STEP,
    TEXT_CELL_MAX_FONT_SIZE,
    TEXT_CELL_PADDING,
    _draw_fitted_text,
)
from krizovkar.typography import SOFT_HYPHEN


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


if __name__ == "__main__":
    unittest.main()

"""Testy sazby textu v PDF rendereru."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from reportlab.lib.styles import ParagraphStyle

from krizovkar.renderer import (
    MAX_CELL_SIZE,
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


if __name__ == "__main__":
    unittest.main()

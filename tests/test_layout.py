"""Testy hustých masek křížovek."""

from __future__ import annotations

import unittest
from collections import Counter

from krizovkar.layout import (
    LayoutError,
    create_dense_numbered_layout,
    create_dense_numbered_layout_candidates,
    create_dense_swedish_layout,
    create_dense_swedish_layout_candidates,
)


class LayoutTest(unittest.TestCase):
    def test_creates_dense_default_layout(self) -> None:
        layout = create_dense_swedish_layout(15, 10)

        self.assertEqual((4, 4), tuple(s.length for s in layout.row_segments))
        self.assertEqual((0, 5), tuple(s.legend for s in layout.row_segments))
        self.assertEqual(
            (4, 4, 4),
            tuple(s.length for s in layout.column_segments),
        )
        self.assertEqual(
            (0, 5, 10),
            tuple(s.legend for s in layout.column_segments),
        )

        roles = Counter(
            layout.role(row, column)
            for row in range(layout.height)
            for column in range(layout.width)
        )
        self.assertEqual(
            {
                "empty": 6,
                "horizontal_legend": 24,
                "vertical_legend": 24,
                "letter": 96,
            },
            roles,
        )

    def test_every_legend_has_exactly_one_possible_exit(self) -> None:
        layout = create_dense_swedish_layout(15, 10)

        for row in range(layout.height):
            for column in range(layout.width):
                role = layout.role(row, column)
                if role not in {"horizontal_legend", "vertical_legend"}:
                    continue
                right_is_letter = (
                    column + 1 < layout.width
                    and layout.role(row, column + 1) == "letter"
                )
                down_is_letter = (
                    row + 1 < layout.height
                    and layout.role(row + 1, column) == "letter"
                )
                self.assertNotEqual(right_is_letter, down_is_letter)

    def test_top_and_left_border_follow_internal_legend_exception(self) -> None:
        layout = create_dense_swedish_layout(15, 10)

        for column in range(layout.width):
            has_internal_legend = any(
                layout.role(row, column) == "horizontal_legend"
                for row in range(1, layout.height)
            )
            self.assertEqual(
                "empty" if has_internal_legend else "vertical_legend",
                layout.role(0, column),
            )

        for row in range(layout.height):
            has_internal_legend = any(
                layout.role(row, column) == "vertical_legend"
                for column in range(1, layout.width)
            )
            self.assertEqual(
                "empty" if has_internal_legend else "horizontal_legend",
                layout.role(row, 0),
            )

    def test_prefers_short_balanced_segments(self) -> None:
        layout = create_dense_swedish_layout(9, 9)

        self.assertEqual((4, 3), tuple(s.length for s in layout.row_segments))
        self.assertEqual((4, 3), tuple(s.length for s in layout.column_segments))

    def test_can_include_length_required_by_secret(self) -> None:
        layout = create_dense_swedish_layout(
            15,
            10,
            required_lengths=(6,),
        )

        lengths = {
            segment.length
            for segment in (*layout.row_segments, *layout.column_segments)
        }
        self.assertIn(6, lengths)
        self.assertEqual(
            (6, 3, 3),
            tuple(s.length for s in layout.column_segments),
        )

    def test_can_distribute_multiple_required_lengths_between_axes(self) -> None:
        layouts = create_dense_swedish_layout_candidates(
            15,
            10,
            required_lengths=(5, 6),
        )

        self.assertTrue(layouts)
        for layout in layouts:
            lengths = {
                segment.length
                for segment in (*layout.row_segments, *layout.column_segments)
            }
            self.assertTrue({5, 6} <= lengths)

    def test_rejects_required_length_outside_dense_range(self) -> None:
        with self.assertRaisesRegex(LayoutError, "obsahoval délky: 2"):
            create_dense_swedish_layout(
                15,
                10,
                required_lengths=(2,),
            )

    def test_rejects_dimension_without_minimum_word_length(self) -> None:
        with self.assertRaisesRegex(LayoutError, "nelze rozdělit"):
            create_dense_swedish_layout(3, 10)

    def test_creates_dense_numbered_layout(self) -> None:
        layout = create_dense_numbered_layout(15, 10)

        self.assertEqual(
            (4, 4, 4, 3),
            tuple(segment.length for segment in layout.column_segments),
        )
        self.assertEqual(
            (0, 4, 8, 12),
            tuple(segment.start for segment in layout.column_segments),
        )
        self.assertEqual(
            (5, 5),
            tuple(segment.length for segment in layout.row_segments),
        )
        self.assertEqual(
            (0, 5),
            tuple(segment.start for segment in layout.row_segments),
        )

    def test_numbered_layout_can_include_required_length(self) -> None:
        layouts = create_dense_numbered_layout_candidates(
            15,
            10,
            required_lengths=(6,),
        )

        self.assertTrue(layouts)
        for layout in layouts:
            lengths = {
                segment.length
                for segment in (*layout.row_segments, *layout.column_segments)
            }
            self.assertIn(6, lengths)

    def test_numbered_layout_rejects_too_short_dimension(self) -> None:
        with self.assertRaisesRegex(LayoutError, "nelze rozdělit"):
            create_dense_numbered_layout(2, 10)


if __name__ == "__main__":
    unittest.main()

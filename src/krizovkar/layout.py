"""Hustá maska švédské křížovky bez směrových šipek."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MIN_SEGMENT_LENGTH = 3
MAX_SEGMENT_LENGTH = 8
PREFERRED_SEGMENT_LENGTH = 4

CellRole = Literal[
    "empty",
    "horizontal_legend",
    "vertical_legend",
    "letter",
]


class LayoutError(ValueError):
    """Pro zadaný rozměr nelze vytvořit podporovanou hustou masku."""


@dataclass(frozen=True, slots=True)
class AxisSegment:
    """Souvislý písmenný úsek bezprostředně za legendovou souřadnicí."""

    legend: int
    start: int
    length: int

    @property
    def stop(self) -> int:
        return self.start + self.length


@dataclass(frozen=True, slots=True)
class SwedishLayout:
    """Rozdělení mřížky na legendové osy a písmenné obdélníky."""

    width: int
    height: int
    row_segments: tuple[AxisSegment, ...]
    column_segments: tuple[AxisSegment, ...]

    @property
    def legend_rows(self) -> frozenset[int]:
        return frozenset(segment.legend for segment in self.row_segments)

    @property
    def legend_columns(self) -> frozenset[int]:
        return frozenset(segment.legend for segment in self.column_segments)

    def role(self, row: int, column: int) -> CellRole:
        """Vrátí účel jedné souřadnice v masce."""

        if not 0 <= row < self.height or not 0 <= column < self.width:
            raise IndexError(f"souřadnice mimo mřížku: row={row}, column={column}")

        legend_row = row in self.legend_rows
        legend_column = column in self.legend_columns
        if legend_row and legend_column:
            return "empty"
        if legend_row:
            return "vertical_legend"
        if legend_column:
            return "horizontal_legend"
        return "letter"


def _segment_lengths(dimension: int) -> tuple[int, ...]:
    candidates: list[tuple[tuple[int, int], tuple[int, ...]]] = []
    for segment_count in range(1, dimension):
        letter_count = dimension - segment_count
        if not (
            segment_count * MIN_SEGMENT_LENGTH
            <= letter_count
            <= segment_count * MAX_SEGMENT_LENGTH
        ):
            continue

        shorter, longer_count = divmod(letter_count, segment_count)
        lengths = tuple(
            shorter + (1 if index < longer_count else 0)
            for index in range(segment_count)
        )
        distance = sum(
            abs(length - PREFERRED_SEGMENT_LENGTH) for length in lengths
        )
        candidates.append(((distance, segment_count), lengths))

    if not candidates:
        raise LayoutError(
            f"rozměr {dimension} nelze rozdělit na písmenné úseky "
            f"délky {MIN_SEGMENT_LENGTH} až {MAX_SEGMENT_LENGTH}"
        )
    return min(candidates, key=lambda candidate: candidate[0])[1]


def _axis_segments(dimension: int) -> tuple[AxisSegment, ...]:
    segments = []
    legend = 0
    for length in _segment_lengths(dimension):
        segments.append(AxisSegment(legend=legend, start=legend + 1, length=length))
        legend += length + 1
    return tuple(segments)


def create_dense_swedish_layout(width: int, height: int) -> SwedishLayout:
    """Vytvoří masku s legendami na horní a levé straně každého bloku."""

    return SwedishLayout(
        width=width,
        height=height,
        row_segments=_axis_segments(height),
        column_segments=_axis_segments(width),
    )

"""Hustá maska švédské křížovky bez směrových šipek."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
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


def _segment_score(lengths: tuple[int, ...]) -> tuple[int, int]:
    return (
        sum(abs(length - PREFERRED_SEGMENT_LENGTH) for length in lengths),
        len(lengths),
    )


@cache
def _segment_length_candidates(dimension: int) -> tuple[tuple[int, ...], ...]:
    candidates = []
    for segment_count in range(1, dimension):
        letter_count = dimension - segment_count
        if not (
            segment_count * MIN_SEGMENT_LENGTH
            <= letter_count
            <= segment_count * MAX_SEGMENT_LENGTH
        ):
            continue

        def search(
            remaining_count: int,
            remaining_letters: int,
            maximum: int,
            lengths: tuple[int, ...],
        ) -> None:
            if remaining_count == 0:
                if remaining_letters == 0:
                    candidates.append(lengths)
                return
            minimum_rest = (remaining_count - 1) * MIN_SEGMENT_LENGTH
            maximum_rest = (remaining_count - 1) * MAX_SEGMENT_LENGTH
            for length in range(
                min(MAX_SEGMENT_LENGTH, maximum),
                MIN_SEGMENT_LENGTH - 1,
                -1,
            ):
                rest = remaining_letters - length
                if minimum_rest <= rest <= maximum_rest:
                    search(
                        remaining_count - 1,
                        rest,
                        length,
                        (*lengths, length),
                    )

        search(segment_count, letter_count, MAX_SEGMENT_LENGTH, ())

    if not candidates:
        raise LayoutError(
            f"rozměr {dimension} nelze rozdělit na písmenné úseky "
            f"délky {MIN_SEGMENT_LENGTH} až {MAX_SEGMENT_LENGTH}"
        )
    return tuple(
        sorted(
            candidates,
            key=lambda lengths: (
                *_segment_score(lengths),
                tuple(-length for length in lengths),
            ),
        )
    )


def _segment_lengths(dimension: int) -> tuple[int, ...]:
    return _segment_length_candidates(dimension)[0]


def _axis_segments(
    dimension: int,
    lengths: tuple[int, ...] | None = None,
) -> tuple[AxisSegment, ...]:
    segments = []
    legend = 0
    for length in lengths or _segment_lengths(dimension):
        segments.append(AxisSegment(legend=legend, start=legend + 1, length=length))
        legend += length + 1
    return tuple(segments)


def create_dense_swedish_layout_candidates(
    width: int,
    height: int,
    *,
    required_lengths: tuple[int, ...] = (),
) -> tuple[SwedishLayout, ...]:
    """Seřadí husté masky, které obsahují všechny požadované délky."""

    required = frozenset(required_lengths)
    candidates = []
    for column_lengths in _segment_length_candidates(width):
        for row_lengths in _segment_length_candidates(height):
            if not required <= set((*column_lengths, *row_lengths)):
                continue
            candidates.append(
                (
                    (
                        _segment_score(column_lengths)[0]
                        + _segment_score(row_lengths)[0],
                        len(column_lengths) + len(row_lengths),
                        tuple(-length for length in column_lengths),
                        tuple(-length for length in row_lengths),
                    ),
                    SwedishLayout(
                        width=width,
                        height=height,
                        row_segments=_axis_segments(height, row_lengths),
                        column_segments=_axis_segments(width, column_lengths),
                    ),
                )
            )
    if not candidates:
        lengths = ", ".join(str(length) for length in sorted(required))
        raise LayoutError(
            f"rozměr {width} × {height} nelze rozdělit tak, "
            f"aby obsahoval délky: {lengths}"
        )
    return tuple(
        layout
        for _, layout in sorted(candidates, key=lambda item: item[0])
    )


def create_dense_swedish_layout(
    width: int,
    height: int,
    *,
    required_lengths: tuple[int, ...] = (),
) -> SwedishLayout:
    """Vytvoří masku s legendami na horní a levé straně každého bloku."""

    return create_dense_swedish_layout_candidates(
        width,
        height,
        required_lengths=required_lengths,
    )[0]

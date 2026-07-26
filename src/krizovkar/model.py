"""Načtení a validace datového modelu křížovky."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


class ModelError(ValueError):
    """Vstupní soubor není platným dokumentem Křížovkáře."""


WordDirection = Literal["horizontal", "vertical"]


@dataclass(frozen=True, slots=True)
class LetterCell:
    """Buňka obsahující jedno písmeno."""

    value: str


@dataclass(frozen=True, slots=True)
class SecretCell:
    """Zvýrazněná buňka, jejíž písmeno patří do tajenky."""

    value: str


@dataclass(frozen=True, slots=True)
class LegendCell:
    """Buňka s jedním nebo dvěma texty legendy."""

    texts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmptyCell:
    """Nevyplňovaná buňka bez písmene a legendy."""


@dataclass(frozen=True, slots=True)
class HelpCell:
    """Pomocná buňka se seznamem slov."""

    words: tuple[str, ...]


GridCell = LetterCell | SecretCell | LegendCell | EmptyCell | HelpCell


@dataclass(frozen=True, slots=True)
class Grid:
    """Obdélníková křížovková mřížka a její případné buňky."""

    width: int
    height: int
    cells: tuple[tuple[GridCell, ...], ...] | None = None


@dataclass(frozen=True, slots=True)
class CrosswordGrid:
    """Cílová křížovková mřížka načtená z datového souboru."""

    format_name: str
    kind: str
    version: int
    grid: Grid


@dataclass(frozen=True, slots=True)
class GridDimensions:
    """Rozměr mřížky v buňkách."""

    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Coordinate:
    """Souřadnice buňky počítaná od 1 z levého horního rohu."""

    row: int
    column: int


@dataclass(frozen=True, slots=True)
class WordPlacement:
    """Slovo umístěné v mřížce spolu se svou legendou."""

    answer: str
    start: Coordinate
    direction: WordDirection
    legend: str
    in_help: bool = False


@dataclass(frozen=True, slots=True)
class CrosswordSpecification:
    """Vstupní zadání, ze kterého má vzniknout cílová mřížka."""

    format_name: str
    kind: str
    version: int
    grid: GridDimensions | None = None
    words: tuple[WordPlacement, ...] = ()
    help_position: Coordinate | None = None


@cache
def _validator(schema_name: str) -> Draft202012Validator:
    schema_resource = files("krizovkar.schemas").joinpath(schema_name)
    schema = json.loads(schema_resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _yaml_data(source: Path) -> Any:
    yaml = YAML(typ="safe", pure=True)
    yaml.version = (1, 2)
    yaml.allow_duplicate_keys = False

    try:
        with source.open(encoding="utf-8") as stream:
            return yaml.load(stream)
    except OSError as error:
        detail = error.strerror or str(error)
        raise ModelError(f"vstupní soubor nelze načíst ({source}): {detail}") from error
    except (UnicodeError, YAMLError) as error:
        problem = getattr(error, "problem", None) or str(error)
        raise ModelError(f"neplatný YAML ({source}): {problem}") from error


def _validation_path(error: ValidationError) -> str:
    parts = [
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    ]
    return "$" + "".join(parts)


def _validated_data(source: Path, schema_name: str) -> dict[str, Any]:
    data = _yaml_data(source)
    errors = sorted(
        _validator(schema_name).iter_errors(data),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )

    if errors:
        details = "; ".join(
            f"{_validation_path(error)}: {error.message}" for error in errors
        )
        raise ModelError(f"neplatný datový model: {details}")

    return data


def _grid_cell(cell: dict[str, Any]) -> GridCell:
    if cell["type"] == "letter":
        return LetterCell(value=cell["value"])
    if cell["type"] == "secret":
        return SecretCell(value=cell["value"])
    if cell["type"] == "legend":
        return LegendCell(texts=tuple(cell["texts"]))
    if cell["type"] == "empty":
        return EmptyCell()
    if cell["type"] == "help":
        return HelpCell(words=tuple(cell["words"]))
    raise ModelError(f"nepodporovaný typ buňky: {cell['type']!r}")


def _grid_cells(grid: dict[str, Any]) -> tuple[tuple[GridCell, ...], ...] | None:
    raw_cells = grid.get("cells")
    if raw_cells is None:
        return None

    if len(raw_cells) != grid["height"]:
        raise ModelError(
            "neplatný datový model: $.grid.cells: "
            f"počet řádků ({len(raw_cells)}) neodpovídá "
            f"grid.height ({grid['height']})"
        )

    rows: list[tuple[GridCell, ...]] = []
    for row_index, raw_row in enumerate(raw_cells):
        if len(raw_row) != grid["width"]:
            raise ModelError(
                f"neplatný datový model: $.grid.cells[{row_index}]: "
                f"počet buněk ({len(raw_row)}) neodpovídá "
                f"grid.width ({grid['width']})"
            )
        rows.append(tuple(_grid_cell(cell) for cell in raw_row))

    return tuple(rows)


def load_crossword_grid(source: str | Path) -> CrosswordGrid:
    """Načte a ověří YAML s cílovou křížovkovou mřížkou."""

    source_path = Path(source)
    data = _validated_data(source_path, "grid-v1.schema.json")
    grid = data["grid"]
    return CrosswordGrid(
        format_name=data["format"],
        kind=data["kind"],
        version=data["version"],
        grid=Grid(
            width=grid["width"],
            height=grid["height"],
            cells=_grid_cells(grid),
        ),
    )


def load_crossword_specification(
    source: str | Path,
) -> CrosswordSpecification:
    """Načte a ověří YAML se zadáním křížovky."""

    source_path = Path(source)
    data = _validated_data(source_path, "specification-v1.schema.json")
    raw_grid = data.get("grid")
    if raw_grid is None:
        return CrosswordSpecification(
            format_name=data["format"],
            kind=data["kind"],
            version=data["version"],
        )

    grid = GridDimensions(width=raw_grid["width"], height=raw_grid["height"])
    words = tuple(
        WordPlacement(
            answer=word["answer"],
            start=Coordinate(
                row=word["start"]["row"],
                column=word["start"]["column"],
            ),
            direction=word["direction"],
            legend=word["legend"],
            in_help=word.get("in_help", False),
        )
        for word in data["words"]
    )
    raw_help = data.get("help")
    help_position = (
        Coordinate(
            row=raw_help["position"]["row"],
            column=raw_help["position"]["column"],
        )
        if raw_help is not None
        else None
    )
    _validate_specification_placements(grid, words, help_position)
    return CrosswordSpecification(
        format_name=data["format"],
        kind=data["kind"],
        version=data["version"],
        grid=grid,
        words=words,
        help_position=help_position,
    )


def _validate_specification_placements(
    grid: GridDimensions,
    words: tuple[WordPlacement, ...],
    help_position: Coordinate | None,
) -> None:
    occupied: dict[tuple[int, int], tuple[str, int]] = {}

    for word_index, word in enumerate(words):
        row_step = 1 if word.direction == "vertical" else 0
        column_step = 1 if word.direction == "horizontal" else 0
        for offset, letter in enumerate(word.answer):
            row = word.start.row + offset * row_step
            column = word.start.column + offset * column_step
            if row > grid.height or column > grid.width:
                raise ModelError(
                    "neplatný datový model: "
                    f"$.words[{word_index}]: slovo {word.answer!r} "
                    f"přesahuje mřížku {grid.width} × {grid.height}"
                )

            coordinate = (row, column)
            previous = occupied.get(coordinate)
            if previous is not None and previous[0] != letter:
                previous_letter, previous_index = previous
                raise ModelError(
                    "neplatný datový model: "
                    f"$.words[{word_index}]: písmeno {letter!r} na souřadnici "
                    f"row={row}, column={column} je v rozporu s písmenem "
                    f"{previous_letter!r} ze $.words[{previous_index}]"
                )
            occupied.setdefault(coordinate, (letter, word_index))

    help_words = tuple(word for word in words if word.in_help)
    if help_position is None:
        if help_words and len(occupied) == grid.width * grid.height:
            raise ModelError(
                "neplatný datový model: $.words: "
                "pomůcku nelze umístit, protože mřížka nemá prázdnou buňku"
            )
        return

    if not help_words:
        raise ModelError(
            "neplatný datový model: $.help: "
            "poloha pomůcky je uvedená, ale žádné slovo nemá in_help: true"
        )
    if help_position.row > grid.height or help_position.column > grid.width:
        raise ModelError(
            "neplatný datový model: $.help.position: "
            f"souřadnice row={help_position.row}, column={help_position.column} "
            f"leží mimo mřížku {grid.width} × {grid.height}"
        )
    if (help_position.row, help_position.column) in occupied:
        raise ModelError(
            "neplatný datový model: $.help.position: "
            "pomůcka musí ležet v buňce neobsazené písmenem"
        )

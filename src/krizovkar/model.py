"""Načtení a validace datového modelu křížovky."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


class ModelError(ValueError):
    """Vstupní soubor není platným dokumentem Křížovkáře."""


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


GridCell = LetterCell | SecretCell | LegendCell


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
class CrosswordSpecification:
    """Vstupní zadání, ze kterého má vzniknout cílová mřížka."""

    format_name: str
    kind: str
    version: int


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
    return CrosswordSpecification(
        format_name=data["format"],
        kind=data["kind"],
        version=data["version"],
    )

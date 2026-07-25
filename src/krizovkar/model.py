"""Načtení a validace datového modelu křížovky."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
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
class Grid:
    """Rozměr obdélníkové křížovkové mřížky."""

    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Crossword:
    """Křížovka načtená z datového souboru."""

    format_name: str
    version: int
    grid: Grid


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema_resource = files("krizovkar.schemas").joinpath("krizovkar-v1.schema.json")
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


def load_crossword(source: str | Path) -> Crossword:
    """Načte YAML, ověří jej podle schématu a vrátí doménový model."""

    source_path = Path(source)
    data = _yaml_data(source_path)
    errors = sorted(
        _validator().iter_errors(data),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )

    if errors:
        details = "; ".join(
            f"{_validation_path(error)}: {error.message}" for error in errors
        )
        raise ModelError(f"neplatný datový model: {details}")

    grid = data["grid"]
    return Crossword(
        format_name=data["format"],
        version=data["version"],
        grid=Grid(width=grid["width"], height=grid["height"]),
    )

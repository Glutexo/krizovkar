"""Načtení a validace datového modelu křížovky."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from itertools import pairwise
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal, TextIO

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.error import YAMLError

from krizovkar.alphabet import split_answer_letters
from krizovkar.localization import system_error_message


class ModelError(ValueError):
    """Datový dokument Křížovkáře nelze načíst, ověřit nebo zapsat."""


WordDirection = Literal["horizontal", "vertical"]
LegendArrow = Literal["right", "down"]
SecretArrow = Literal["up", "right", "down", "left"]
CellBar = Literal["right", "bottom"]
SecretPromptPlacement = Literal["above", "below"]
SecretPromptAlignment = Literal["left", "right"]
DEFAULT_SECRET_LEGEND = "Tajenka"
DEFAULT_SECRET_PART_LEGEND = "{number}. část tajenky"


@dataclass(frozen=True, slots=True)
class LetterCell:
    """Běžná písmenná buňka s volitelně již známou hodnotou."""

    value: str | None = None
    number: int | None = None
    bars: tuple[CellBar, ...] = ()


@dataclass(frozen=True, slots=True)
class SecretCell:
    """Zvýrazněná tajenková buňka s volitelně již známou hodnotou."""

    value: str | None = None
    arrow: SecretArrow | None = None
    number: int | None = None
    bars: tuple[CellBar, ...] = ()


@dataclass(frozen=True, slots=True)
class LegendCell:
    """Buňka pro dosud neznámé nebo již vyplněné texty legend."""

    texts: tuple[str | None, ...] = ()
    arrows: tuple[LegendArrow, ...] = ()


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
class ExternalClue:
    """Očíslovaná legenda uvedená vně mřížky."""

    number: int
    direction: WordDirection
    text: str


@dataclass(frozen=True, slots=True)
class SecretPrompt:
    """Text zadání tajenky umístěný vně mřížky."""

    text: str
    placement: SecretPromptPlacement = "above"
    alignment: SecretPromptAlignment = "left"


@dataclass(frozen=True, slots=True)
class CrosswordGrid:
    """Jednotná cílová mřížka s libovolným způsobem uvedení legend."""

    format_name: str
    kind: str
    version: int
    grid: Grid
    clues: tuple[ExternalClue, ...] = ()
    secret_prompts: tuple[SecretPrompt, ...] = ()


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
class TemplateLetterCell:
    """Dosud nevyplněná písmenná buňka šablony."""


@dataclass(frozen=True, slots=True)
class TemplateLegendCell:
    """Buňka šablony vyhrazená pro jednu nebo dvě legendy."""


@dataclass(frozen=True, slots=True)
class TemplateEmptyCell:
    """Nevyplňovaná buňka šablony."""


TemplateCell = TemplateLetterCell | TemplateLegendCell | TemplateEmptyCell


@dataclass(frozen=True, slots=True)
class TemplateGrid:
    """Obdélníková matice rolí buněk šablony."""

    width: int
    height: int
    cells: tuple[tuple[TemplateCell, ...], ...]


@dataclass(frozen=True, slots=True)
class WordSlot:
    """Místo pro jedno heslo bez dosud zvolené odpovědi a legendy."""

    identifier: str
    start: Coordinate
    direction: WordDirection
    length: int
    legend_position: Coordinate | None = None


@dataclass(frozen=True, slots=True)
class TemplateSecretPart:
    """Jedna část tajenky rezervovaná v konkrétním slotu."""

    slot_identifier: str
    word_count: int | None = None


@dataclass(frozen=True, slots=True)
class TemplateSecret:
    """Připravené sloty tajenky a volitelně její známá slova."""

    parts: tuple[TemplateSecretPart, ...]
    words: tuple[str, ...] = ()
    prompt: SecretPrompt | None = None


@dataclass(frozen=True, slots=True)
class CrosswordTemplate:
    """Strukturální mezivýsledek mezi zadáním a vyplněnou mřížkou."""

    format_name: str
    kind: str
    version: int
    grid: TemplateGrid
    slots: tuple[WordSlot, ...]
    secrets: tuple[TemplateSecret, ...] = ()


@dataclass(frozen=True, slots=True)
class WordPlacement:
    """Slovo umístěné v mřížce spolu se svou legendou."""

    answer: str
    start: Coordinate
    direction: WordDirection
    legend: str
    in_help: bool = False


@dataclass(frozen=True, slots=True)
class SecretCells:
    """Tajenka určená výběrem buněk a volitelnou souvislou cestou."""

    cells: tuple[Coordinate, ...]
    arrows: bool = False
    prompt: SecretPrompt | None = None

    @property
    def reading_cells(self) -> tuple[Coordinate, ...]:
        """Vrátí pole v pořadí čtení tajenky."""

        if self.arrows:
            return self.cells
        return tuple(
            sorted(self.cells, key=lambda cell: (cell.row, cell.column))
        )


def _secret_step_direction(
    current: Coordinate,
    following: Coordinate,
) -> SecretArrow:
    step = (following.row - current.row, following.column - current.column)
    directions: dict[tuple[int, int], SecretArrow] = {
        (-1, 0): "up",
        (0, 1): "right",
        (1, 0): "down",
        (0, -1): "left",
    }
    try:
        return directions[step]
    except KeyError as error:
        raise ValueError(
            "následující buňky musí sousedit společnou hranou"
        ) from error


def secret_path_arrows(
    secret: SecretCells,
) -> tuple[tuple[Coordinate, SecretArrow], ...]:
    """Určí odchozí šipku na začátku a při každé změně směru."""

    if not secret.arrows:
        return ()
    if len(secret.cells) < 2:
        raise ValueError("tajenka se šipkami musí obsahovat alespoň dvě buňky")

    arrows: list[tuple[Coordinate, SecretArrow]] = []
    previous_direction: SecretArrow | None = None
    for current, following in pairwise(secret.reading_cells):
        direction = _secret_step_direction(current, following)
        if previous_direction is None or direction != previous_direction:
            arrows.append((current, direction))
        previous_direction = direction
    return tuple(arrows)


@dataclass(frozen=True, slots=True)
class SecretWord:
    """Souvislá tajenka s popiskem a směrem."""

    answer: str
    start: Coordinate
    direction: WordDirection
    legend: str = DEFAULT_SECRET_LEGEND
    prompt: SecretPrompt | None = None


SecretPart = SecretCells | SecretWord


@dataclass(frozen=True, slots=True)
class SecretParts:
    """Jedna tajenka složená z několika částí v určeném pořadí."""

    parts: tuple[SecretPart, ...]
    prompt: SecretPrompt | None = None


SecretDefinition = SecretPart | SecretParts


@dataclass(frozen=True, slots=True)
class CrosswordSpecification:
    """Společné vstupní zadání nezávislé na budoucím rozložení legend."""

    format_name: str
    kind: str
    version: int
    grid: GridDimensions | None = None
    words: tuple[WordPlacement, ...] = ()
    secrets: tuple[SecretDefinition, ...] = ()
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
        raise ModelError(
            f"vstupní soubor nelze načíst ({source}): "
            f"{system_error_message(error)}"
        ) from error
    except UnicodeError as error:
        raise ModelError(
            f"vstupní soubor není platný text v UTF-8 ({source})"
        ) from error
    except DuplicateKeyError as error:
        raise ModelError(
            f"neplatný YAML ({source}{_yaml_error_location(error)}): "
            "duplicitní klíč"
        ) from error
    except YAMLError as error:
        raise ModelError(
            f"neplatný YAML ({source}{_yaml_error_location(error)}): "
            "syntaktická chyba"
        ) from error


def _yaml_error_location(error: YAMLError) -> str:
    mark = getattr(error, "problem_mark", None)
    if mark is None:
        return ""
    return f", řádek {mark.line + 1}, sloupec {mark.column + 1}"


def _validation_path(error: ValidationError) -> str:
    parts = [
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    ]
    return "$" + "".join(parts)


_SCHEMA_TYPE_NAMES = {
    "array": "seznam",
    "boolean": "logická hodnota",
    "integer": "celé číslo",
    "null": "prázdná hodnota null",
    "number": "číslo",
    "object": "objekt",
    "string": "text",
}


def _schema_values(values: Any) -> str:
    return ", ".join(repr(value) for value in values)


def _schema_type_name(expected: Any) -> str:
    if isinstance(expected, list):
        return "jeden z typů " + ", ".join(
            _SCHEMA_TYPE_NAMES.get(value, repr(value)) for value in expected
        )
    return _SCHEMA_TYPE_NAMES.get(expected, repr(expected))


def _schema_validation_message(error: ValidationError) -> str:
    """Popíše porušení JSON Schema česky bez textu z knihovny."""

    validator = error.validator
    expected = error.validator_value

    if validator == "required":
        missing = tuple(key for key in expected if key not in error.instance)
        if len(missing) == 1:
            return f"chybí povinný klíč {missing[0]!r}"
        return f"chybějí povinné klíče {_schema_values(missing)}"
    if validator == "type":
        return f"očekává se {_schema_type_name(expected)}"
    if validator == "const":
        return f"očekává se hodnota {expected!r}"
    if validator == "enum":
        return f"povolené hodnoty jsou {_schema_values(expected)}"
    if validator == "minimum":
        return f"minimální povolená hodnota je {expected}"
    if validator == "maximum":
        return f"maximální povolená hodnota je {expected}"
    if validator == "minItems":
        return f"minimální počet položek seznamu je {expected}"
    if validator == "maxItems":
        return f"maximální počet položek seznamu je {expected}"
    if validator == "minLength":
        return f"minimální délka textu je {expected} znaků"
    if validator == "maxLength":
        return f"maximální délka textu je {expected} znaků"
    if validator == "uniqueItems":
        return "položky seznamu se nesmějí opakovat"
    if validator == "pattern":
        return "text neodpovídá požadovanému formátu"
    if validator == "additionalProperties":
        properties = error.schema.get("properties", {})
        unexpected = tuple(
            sorted(
                (key for key in error.instance if key not in properties),
                key=str,
            )
        )
        if len(unexpected) == 1:
            return f"objekt obsahuje nepovolený klíč {unexpected[0]!r}"
        if unexpected:
            return f"objekt obsahuje nepovolené klíče {_schema_values(unexpected)}"
        return "objekt obsahuje nepovolený klíč"
    if validator == "dependentRequired":
        missing_dependencies = tuple(
            (key, dependency)
            for key, dependencies in expected.items()
            if key in error.instance
            for dependency in dependencies
            if dependency not in error.instance
        )
        if missing_dependencies:
            key, dependency = missing_dependencies[0]
            return f"klíč {key!r} vyžaduje také klíč {dependency!r}"
        return "chybí klíč vyžadovaný jiným klíčem"
    if validator == "anyOf":
        return "hodnota neodpovídá žádné povolené variantě"
    if validator == "oneOf":
        return "hodnota musí odpovídat právě jedné povolené variantě"
    if validator == "allOf":
        return "hodnota nesplňuje všechna požadovaná pravidla"
    if validator == "not":
        return "hodnota odpovídá zakázané variantě"
    return f"hodnota neodpovídá pravidlu {validator!r}"


def _validated_data(source: Path, schema_name: str) -> dict[str, Any]:
    data = _yaml_data(source)
    errors = sorted(
        _validator(schema_name).iter_errors(data),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )

    if errors:
        details = "; ".join(
            dict.fromkeys(
                f"{_validation_path(error)}: {_schema_validation_message(error)}"
                for error in errors
            )
        )
        raise ModelError(f"neplatný datový model: {details}")

    return data


def _grid_cell(cell: dict[str, Any]) -> GridCell:
    if cell["type"] == "letter":
        return LetterCell(
            value=cell.get("value"),
            number=cell.get("number"),
            bars=tuple(cell.get("bars", ())),
        )
    if cell["type"] == "secret":
        return SecretCell(
            value=cell.get("value"),
            arrow=cell.get("arrow"),
            number=cell.get("number"),
            bars=tuple(cell.get("bars", ())),
        )
    if cell["type"] == "legend":
        return LegendCell(
            texts=tuple(cell.get("texts", ())),
            arrows=tuple(cell.get("arrows", ())),
        )
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


def _secret_prompt(data: dict[str, Any]) -> SecretPrompt:
    return SecretPrompt(
        text=data["text"],
        placement=data.get("placement", "above"),
        alignment=data.get("alignment", "left"),
    )


def _optional_secret_prompt(data: dict[str, Any]) -> SecretPrompt | None:
    raw_prompt = data.get("prompt")
    return _secret_prompt(raw_prompt) if raw_prompt is not None else None


def load_crossword_grid(source: str | Path) -> CrosswordGrid:
    """Načte a ověří YAML s cílovou křížovkovou mřížkou."""

    source_path = Path(source)
    data = _validated_data(source_path, "grid-v1.schema.json")
    raw_grid = data["grid"]
    grid = Grid(
        width=raw_grid["width"],
        height=raw_grid["height"],
        cells=_grid_cells(raw_grid),
    )
    clues = tuple(
        ExternalClue(
            number=clue["number"],
            direction=clue["direction"],
            text=clue["text"],
        )
        for clue in data.get("clues", ())
    )
    secret_prompts = tuple(
        _secret_prompt(prompt) for prompt in data.get("secret_prompts", ())
    )
    _validate_grid_annotations(grid, clues)
    return CrosswordGrid(
        format_name=data["format"],
        kind=data["kind"],
        version=data["version"],
        grid=grid,
        clues=clues,
        secret_prompts=secret_prompts,
    )


def load_crossword_document_kind(source: str | Path) -> str:
    """Načte kořenový klíč ``kind`` pro volbu správného loaderu."""

    source_path = Path(source)
    data = _yaml_data(source_path)
    if not isinstance(data, dict):
        raise ModelError("neplatný datový model: $: očekává se objekt")
    if "kind" not in data:
        raise ModelError(
            "neplatný datový model: $.kind: chybí povinný klíč 'kind'"
        )
    kind = data["kind"]
    if not isinstance(kind, str):
        raise ModelError("neplatný datový model: $.kind: očekává se text")
    return kind


def _template_cell(cell: dict[str, Any]) -> TemplateCell:
    if cell["type"] == "letter":
        return TemplateLetterCell()
    if cell["type"] == "legend":
        return TemplateLegendCell()
    if cell["type"] == "empty":
        return TemplateEmptyCell()
    raise ModelError(f"nepodporovaný typ buňky šablony: {cell['type']!r}")


def _template_cells(
    grid: dict[str, Any],
) -> tuple[tuple[TemplateCell, ...], ...]:
    raw_cells = grid["cells"]
    if len(raw_cells) != grid["height"]:
        raise ModelError(
            "neplatný datový model: $.grid.cells: "
            f"počet řádků ({len(raw_cells)}) neodpovídá "
            f"grid.height ({grid['height']})"
        )

    rows: list[tuple[TemplateCell, ...]] = []
    for row_index, raw_row in enumerate(raw_cells):
        if len(raw_row) != grid["width"]:
            raise ModelError(
                f"neplatný datový model: $.grid.cells[{row_index}]: "
                f"počet buněk ({len(raw_row)}) neodpovídá "
                f"grid.width ({grid['width']})"
            )
        rows.append(tuple(_template_cell(cell) for cell in raw_row))
    return tuple(rows)


def load_crossword_template(source: str | Path) -> CrosswordTemplate:
    """Načte a ověří YAML se strukturální šablonou křížovky."""

    source_path = Path(source)
    data = _validated_data(source_path, "template-v1.schema.json")
    raw_grid = data["grid"]
    template = CrosswordTemplate(
        format_name=data["format"],
        kind=data["kind"],
        version=data["version"],
        grid=TemplateGrid(
            width=raw_grid["width"],
            height=raw_grid["height"],
            cells=_template_cells(raw_grid),
        ),
        slots=tuple(
            WordSlot(
                identifier=slot["id"],
                start=Coordinate(
                    row=slot["start"]["row"],
                    column=slot["start"]["column"],
                ),
                direction=slot["direction"],
                length=slot["length"],
                legend_position=(
                    Coordinate(
                        row=slot["legend"]["row"],
                        column=slot["legend"]["column"],
                    )
                    if "legend" in slot
                    else None
                ),
            )
            for slot in data["slots"]
        ),
        secrets=tuple(
            TemplateSecret(
                parts=tuple(
                    TemplateSecretPart(
                        slot_identifier=part["slot"],
                        word_count=part.get("word_count"),
                    )
                    for part in secret["parts"]
                ),
                words=tuple(secret.get("words", ())),
                prompt=_optional_secret_prompt(secret),
            )
            for secret in data.get("secrets", ())
        ),
    )
    _validate_crossword_template(template)
    return template


def _validate_crossword_template(template: CrosswordTemplate) -> None:
    grid = template.grid
    if grid.width < 1 or grid.height < 1:
        raise ModelError("neplatný datový model: $.grid: rozměry musí být kladné")
    if len(grid.cells) != grid.height:
        raise ModelError(
            "neplatný datový model: $.grid.cells: "
            f"počet řádků ({len(grid.cells)}) neodpovídá "
            f"grid.height ({grid.height})"
        )
    for row_index, row in enumerate(grid.cells):
        if len(row) != grid.width:
            raise ModelError(
                f"neplatný datový model: $.grid.cells[{row_index}]: "
                f"počet buněk ({len(row)}) neodpovídá "
                f"grid.width ({grid.width})"
            )
    if not template.slots:
        raise ModelError("neplatný datový model: $.slots: seznam nesmí být prázdný")

    identifiers: dict[str, str] = {}
    occupied: dict[tuple[int, int], dict[WordDirection, str]] = {}
    used_letters: set[tuple[int, int]] = set()
    used_legends: dict[tuple[int, int], dict[WordDirection, str]] = {}

    for slot_index, slot in enumerate(template.slots):
        path = f"$.slots[{slot_index}]"
        if slot.length < 1:
            raise ModelError(
                f"neplatný datový model: {path}.length: délka musí být kladná"
            )
        if slot.start.row < 1 or slot.start.column < 1:
            raise ModelError(
                f"neplatný datový model: {path}.start: souřadnice musí být kladné"
            )
        previous_identifier_path = identifiers.get(slot.identifier)
        if previous_identifier_path is not None:
            raise ModelError(
                "neplatný datový model: "
                f"{path}.id: identifikátor {slot.identifier!r} už používá "
                f"{previous_identifier_path}"
            )
        identifiers[slot.identifier] = f"{path}.id"

        row_step = 1 if slot.direction == "vertical" else 0
        column_step = 1 if slot.direction == "horizontal" else 0
        for offset in range(slot.length):
            row = slot.start.row + offset * row_step
            column = slot.start.column + offset * column_step
            if row > grid.height or column > grid.width:
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: slot {slot.identifier!r} přesahuje šablonu "
                    f"{grid.width} × {grid.height}"
                )
            cell = grid.cells[row - 1][column - 1]
            if not isinstance(cell, TemplateLetterCell):
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: slot {slot.identifier!r} vede přes nepísmennou "
                    f"buňku row={row}, column={column}"
                )

            coordinate = (row, column)
            directions = occupied.setdefault(coordinate, {})
            previous_slot = directions.get(slot.direction)
            if previous_slot is not None:
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: slot {slot.identifier!r} se ve stejném směru "
                    f"překrývá se slotem {previous_slot!r}"
                )
            directions[slot.direction] = slot.identifier
            used_letters.add(coordinate)

        if slot.legend_position is None:
            continue
        legend = slot.legend_position
        if (
            legend.row < 1
            or legend.column < 1
            or legend.row > grid.height
            or legend.column > grid.width
        ):
            raise ModelError(
                "neplatný datový model: "
                f"{path}.legend: souřadnice leží mimo šablonu "
                f"{grid.width} × {grid.height}"
            )
        expected_legend = (
            Coordinate(row=slot.start.row, column=slot.start.column - 1)
            if slot.direction == "horizontal"
            else Coordinate(row=slot.start.row - 1, column=slot.start.column)
        )
        if legend != expected_legend:
            raise ModelError(
                "neplatný datový model: "
                f"{path}.legend: legenda musí bezprostředně předcházet "
                "prvnímu písmenu slotu"
            )
        legend_cell = grid.cells[legend.row - 1][legend.column - 1]
        if not isinstance(legend_cell, TemplateLegendCell):
            raise ModelError(
                "neplatný datový model: "
                f"{path}.legend: souřadnice row={legend.row}, "
                f"column={legend.column} není legendová buňka"
            )
        directions = used_legends.setdefault((legend.row, legend.column), {})
        previous_slot = directions.get(slot.direction)
        if previous_slot is not None:
            raise ModelError(
                "neplatný datový model: "
                f"{path}.legend: legendu ve směru {slot.direction!r} "
                f"už používá slot {previous_slot!r}"
            )
        directions[slot.direction] = slot.identifier

    for row_index, row in enumerate(grid.cells, start=1):
        for column_index, cell in enumerate(row, start=1):
            coordinate = (row_index, column_index)
            if (
                isinstance(cell, TemplateLetterCell)
                and coordinate not in used_letters
            ):
                raise ModelError(
                    "neplatný datový model: "
                    f"$.grid.cells[{row_index - 1}][{column_index - 1}]: "
                    "písmenná buňka nepatří do žádného slotu"
                )
            if (
                isinstance(cell, TemplateLegendCell)
                and coordinate not in used_legends
            ):
                raise ModelError(
                    "neplatný datový model: "
                    f"$.grid.cells[{row_index - 1}][{column_index - 1}]: "
                    "legendovou buňku nepoužívá žádný slot"
                )

    slots_by_identifier = {slot.identifier: slot for slot in template.slots}
    used_secret_slots: dict[str, str] = {}
    for secret_index, secret in enumerate(template.secrets):
        secret_path = f"$.secrets[{secret_index}]"
        if not secret.parts:
            raise ModelError(
                f"neplatný datový model: {secret_path}.parts: "
                "seznam nesmí být prázdný"
            )
        counts = tuple(part.word_count for part in secret.parts)
        if secret.words:
            if any(count is None for count in counts):
                raise ModelError(
                    f"neplatný datový model: {secret_path}.parts: "
                    "známá tajenka musí u každé části uvést word_count"
                )
            if sum(count for count in counts if count is not None) != len(
                secret.words
            ):
                raise ModelError(
                    f"neplatný datový model: {secret_path}.parts: "
                    "součet word_count neodpovídá počtu slov tajenky"
                )
        elif any(count is not None for count in counts):
            raise ModelError(
                f"neplatný datový model: {secret_path}.parts: "
                "word_count lze uvést jen u tajenky se známými words"
            )

        word_offset = 0
        for part_index, part in enumerate(secret.parts):
            part_path = f"{secret_path}.parts[{part_index}]"
            slot = slots_by_identifier.get(part.slot_identifier)
            if slot is None:
                raise ModelError(
                    f"neplatný datový model: {part_path}.slot: "
                    f"slot {part.slot_identifier!r} v šabloně neexistuje"
                )
            previous_path = used_secret_slots.get(part.slot_identifier)
            if previous_path is not None:
                raise ModelError(
                    f"neplatný datový model: {part_path}.slot: "
                    f"slot {part.slot_identifier!r} už používá {previous_path}"
                )
            used_secret_slots[part.slot_identifier] = f"{part_path}.slot"

            if not secret.words:
                continue
            assert part.word_count is not None
            part_words = secret.words[
                word_offset : word_offset + part.word_count
            ]
            word_offset += part.word_count
            part_length = len(split_answer_letters("".join(part_words)))
            if part_length != slot.length:
                raise ModelError(
                    f"neplatný datový model: {part_path}: "
                    f"část tajenky má {part_length} polí, ale slot "
                    f"{slot.identifier!r} má délku {slot.length}"
                )


def _validate_grid_annotations(
    grid: Grid,
    clues: tuple[ExternalClue, ...],
) -> None:
    numbered_cells: dict[int, tuple[str, int, int]] = {}
    if grid.cells is not None:
        for row_index, row in enumerate(grid.cells):
            for column_index, cell in enumerate(row):
                if not isinstance(cell, (LetterCell, SecretCell)):
                    continue
                path = f"$.grid.cells[{row_index}][{column_index}]"
                if cell.number is not None:
                    previous = numbered_cells.get(cell.number)
                    if previous is not None:
                        previous_path, _, _ = previous
                        raise ModelError(
                            "neplatný datový model: "
                            f"{path}.number: číslo {cell.number} už používá "
                            f"buňka {previous_path}"
                        )
                    numbered_cells[cell.number] = (
                        path,
                        row_index,
                        column_index,
                    )
                if "right" in cell.bars and column_index == grid.width - 1:
                    raise ModelError(
                        "neplatný datový model: "
                        f"{path}.bars: pravý předěl musí ležet uvnitř mřížky"
                    )
                if "bottom" in cell.bars and row_index == grid.height - 1:
                    raise ModelError(
                        "neplatný datový model: "
                        f"{path}.bars: dolní předěl musí ležet uvnitř mřížky"
                    )

    clue_keys: set[tuple[int, WordDirection]] = set()
    for clue_index, clue in enumerate(clues):
        path = f"$.clues[{clue_index}]"
        numbered_cell = numbered_cells.get(clue.number)
        if numbered_cell is None:
            raise ModelError(
                "neplatný datový model: "
                f"{path}.number: číslo {clue.number} nemá odpovídající "
                "písmennou buňku"
            )
        _, row_index, column_index = numbered_cell
        key = (clue.number, clue.direction)
        if key in clue_keys:
            raise ModelError(
                "neplatný datový model: "
                f"{path}: legenda číslo {clue.number} ve směru "
                f"{clue.direction!r} je uvedená vícekrát"
            )
        clue_keys.add(key)

        assert grid.cells is not None
        if clue.direction == "horizontal" and column_index > 0:
            previous_cell = grid.cells[row_index][column_index - 1]
            if (
                isinstance(previous_cell, (LetterCell, SecretCell))
                and "right" not in previous_cell.bars
            ):
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: vodorovné slovo začínající uvnitř souvislého "
                    "řádku musí mít před sebou silný pravý předěl"
                )
        if clue.direction == "vertical" and row_index > 0:
            previous_cell = grid.cells[row_index - 1][column_index]
            if (
                isinstance(previous_cell, (LetterCell, SecretCell))
                and "bottom" not in previous_cell.bars
            ):
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: svislé slovo začínající uvnitř souvislého "
                    "sloupce musí mít nad sebou silný dolní předěl"
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
        for word in data.get("words", ())
    )
    secrets = tuple(
        _secret_definition(secret) for secret in data.get("secrets", ())
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
    _validate_specification_placements(grid, words, secrets, help_position)
    return CrosswordSpecification(
        format_name=data["format"],
        kind=data["kind"],
        version=data["version"],
        grid=grid,
        words=words,
        secrets=secrets,
        help_position=help_position,
    )


def _secret_part(data: dict[str, Any], default_legend: str) -> SecretPart:
    if data["type"] == "cells":
        return SecretCells(
            cells=tuple(
                Coordinate(row=cell["row"], column=cell["column"])
                for cell in data["cells"]
            ),
            arrows=data.get("arrows", False),
            prompt=_optional_secret_prompt(data),
        )
    return SecretWord(
        answer=data["answer"],
        start=Coordinate(
            row=data["start"]["row"],
            column=data["start"]["column"],
        ),
        direction=data["direction"],
        legend=data.get("legend", default_legend),
        prompt=_optional_secret_prompt(data),
    )


def _secret_definition(data: dict[str, Any]) -> SecretDefinition:
    if data["type"] != "parts":
        return _secret_part(data, DEFAULT_SECRET_LEGEND)
    return SecretParts(
        parts=tuple(
            _secret_part(
                part,
                DEFAULT_SECRET_PART_LEGEND.format(number=part_index + 1),
            )
            for part_index, part in enumerate(data["parts"])
        ),
        prompt=_optional_secret_prompt(data),
    )


def _validate_specification_placements(
    grid: GridDimensions,
    words: tuple[WordPlacement, ...],
    secrets: tuple[SecretDefinition, ...],
    help_position: Coordinate | None,
) -> None:
    occupied: dict[tuple[int, int], tuple[str, str]] = {}
    secret_parts: list[tuple[SecretPart, str]] = []
    for secret_index, secret in enumerate(secrets):
        if isinstance(secret, SecretParts):
            secret_parts.extend(
                (
                    part,
                    f"$.secrets[{secret_index}].parts[{part_index}]",
                )
                for part_index, part in enumerate(secret.parts)
            )
        else:
            secret_parts.append((secret, f"$.secrets[{secret_index}]"))

    placements = [
        (word.answer, word.start, word.direction, f"$.words[{word_index}]")
        for word_index, word in enumerate(words)
    ]
    placements.extend(
        (part.answer, part.start, part.direction, path)
        for part, path in secret_parts
        if isinstance(part, SecretWord)
    )

    for answer, start, direction, path in placements:
        row_step = 1 if direction == "vertical" else 0
        column_step = 1 if direction == "horizontal" else 0
        for offset, letter in enumerate(split_answer_letters(answer)):
            row = start.row + offset * row_step
            column = start.column + offset * column_step
            if row > grid.height or column > grid.width:
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: slovo {answer!r} "
                    f"přesahuje mřížku {grid.width} × {grid.height}"
                )

            coordinate = (row, column)
            previous = occupied.get(coordinate)
            if previous is not None and previous[0] != letter:
                previous_letter, previous_path = previous
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: písmeno {letter!r} na souřadnici "
                    f"row={row}, column={column} je v rozporu s písmenem "
                    f"{previous_letter!r} z {previous_path}"
                )
            occupied.setdefault(coordinate, (letter, path))

    for part, secret_path in secret_parts:
        if not isinstance(part, SecretCells):
            continue
        for cell_index, cell in enumerate(part.cells):
            path = f"{secret_path}.cells[{cell_index}]"
            if cell.row > grid.height or cell.column > grid.width:
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: souřadnice row={cell.row}, column={cell.column} "
                    f"leží mimo mřížku {grid.width} × {grid.height}"
                )
            if (cell.row, cell.column) not in occupied:
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: tajenka musí odkazovat na buňku obsazenou písmenem"
                )

        if not part.arrows:
            continue
        if part.arrows and len(part.cells) < 2:
            raise ModelError(
                "neplatný datový model: "
                f"{secret_path}.arrows: tajenka se šipkami "
                "musí obsahovat alespoň dvě buňky"
            )
        for cell_index, (current, following) in enumerate(
            pairwise(part.cells)
        ):
            try:
                _secret_step_direction(current, following)
            except ValueError as error:
                path = f"{secret_path}.cells[{cell_index + 1}]"
                raise ModelError(
                    "neplatný datový model: "
                    f"{path}: {error}"
                ) from error

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


def _grid_cell_data(cell: GridCell) -> dict[str, Any]:
    if isinstance(cell, LetterCell):
        data: dict[str, Any] = {"type": "letter"}
        if cell.value is not None:
            data["value"] = cell.value
        if cell.number is not None:
            data["number"] = cell.number
        if cell.bars:
            data["bars"] = list(cell.bars)
        return data
    if isinstance(cell, SecretCell):
        data = {"type": "secret"}
        if cell.value is not None:
            data["value"] = cell.value
        if cell.arrow is not None:
            data["arrow"] = cell.arrow
        if cell.number is not None:
            data["number"] = cell.number
        if cell.bars:
            data["bars"] = list(cell.bars)
        return data
    if isinstance(cell, LegendCell):
        data: dict[str, Any] = {"type": "legend"}
        if cell.texts:
            data["texts"] = list(cell.texts)
        if cell.arrows:
            data["arrows"] = list(cell.arrows)
        return data
    if isinstance(cell, EmptyCell):
        return {"type": "empty"}
    if isinstance(cell, HelpCell):
        return {"type": "help", "words": list(cell.words)}
    raise ModelError(f"nepodporovaný typ buňky pro zápis: {type(cell).__name__}")


def _crossword_grid_data(crossword: CrosswordGrid) -> dict[str, Any]:
    _validate_grid_annotations(crossword.grid, crossword.clues)
    grid: dict[str, Any] = {
        "width": crossword.grid.width,
        "height": crossword.grid.height,
    }
    if crossword.grid.cells is not None:
        grid["cells"] = [
            [_grid_cell_data(cell) for cell in row]
            for row in crossword.grid.cells
        ]
    data: dict[str, Any] = {
        "format": crossword.format_name,
        "kind": crossword.kind,
        "version": crossword.version,
        "grid": grid,
    }
    if crossword.secret_prompts:
        data["secret_prompts"] = [
            {
                "text": prompt.text,
                "placement": prompt.placement,
                "alignment": prompt.alignment,
            }
            for prompt in crossword.secret_prompts
        ]
    if crossword.clues:
        data["clues"] = [
            {
                "number": clue.number,
                "direction": clue.direction,
                "text": clue.text,
            }
            for clue in crossword.clues
        ]
    return data


def _template_cell_data(cell: TemplateCell) -> dict[str, str]:
    if isinstance(cell, TemplateLetterCell):
        return {"type": "letter"}
    if isinstance(cell, TemplateLegendCell):
        return {"type": "legend"}
    if isinstance(cell, TemplateEmptyCell):
        return {"type": "empty"}
    raise ModelError(
        f"nepodporovaný typ buňky šablony pro zápis: {type(cell).__name__}"
    )


def _crossword_template_data(template: CrosswordTemplate) -> dict[str, Any]:
    _validate_crossword_template(template)
    slots = []
    for slot in template.slots:
        data: dict[str, Any] = {
            "id": slot.identifier,
            "start": {
                "row": slot.start.row,
                "column": slot.start.column,
            },
            "direction": slot.direction,
            "length": slot.length,
        }
        if slot.legend_position is not None:
            data["legend"] = {
                "row": slot.legend_position.row,
                "column": slot.legend_position.column,
            }
        slots.append(data)

    result: dict[str, Any] = {
        "format": template.format_name,
        "kind": template.kind,
        "version": template.version,
        "grid": {
            "width": template.grid.width,
            "height": template.grid.height,
            "cells": [
                [_template_cell_data(cell) for cell in row]
                for row in template.grid.cells
            ],
        },
        "slots": slots,
    }
    if template.secrets:
        result["secrets"] = []
        for secret in template.secrets:
            parts = []
            for part in secret.parts:
                part_data: dict[str, Any] = {"slot": part.slot_identifier}
                if part.word_count is not None:
                    part_data["word_count"] = part.word_count
                parts.append(part_data)
            secret_data: dict[str, Any] = {"parts": parts}
            if secret.words:
                secret_data["words"] = list(secret.words)
            if secret.prompt is not None:
                secret_data["prompt"] = {
                    "text": secret.prompt.text,
                    "placement": secret.prompt.placement,
                    "alignment": secret.prompt.alignment,
                }
            result["secrets"].append(secret_data)
    return result


def _write_yaml_document(
    data: dict[str, Any],
    output: str | Path,
    *,
    overwrite: bool,
    subject: str,
) -> Path:
    output_path = Path(output)
    if output_path.exists() and not overwrite:
        raise ModelError(f"výstupní soubor již existuje: {output_path}")

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{output_path.name}.",
            suffix=".yaml",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            _dump_yaml_document(data, temporary)

        temporary_path.replace(output_path)
    except OSError as error:
        raise ModelError(
            f"{subject} nelze zapsat ({output_path}): "
            f"{system_error_message(error)}"
        ) from error
    except YAMLError as error:
        raise ModelError(
            f"{subject} nelze zapsat ({output_path}): "
            "data se nepodařilo převést do YAML"
        ) from error
    finally:
        if "temporary_path" in locals():
            temporary_path.unlink(missing_ok=True)

    return output_path


def _dump_yaml_document(
    data: dict[str, Any],
    output: TextIO,
) -> None:
    yaml = YAML()
    yaml.width = 100
    yaml.indent(mapping=2, sequence=2, offset=0)
    yaml.representer.add_representer(
        type(None),
        lambda representer, _: representer.represent_scalar(
            "tag:yaml.org,2002:null",
            "null",
        ),
    )
    yaml.dump(data, output)


def _dump_yaml_document_safely(
    data: dict[str, Any],
    output: TextIO,
    *,
    subject: str,
) -> None:
    try:
        _dump_yaml_document(data, output)
    except OSError as error:
        raise ModelError(
            f"{subject} nelze zapsat: {system_error_message(error)}"
        ) from error
    except YAMLError as error:
        raise ModelError(
            f"{subject} nelze zapsat: data se nepodařilo převést do YAML"
        ) from error


def write_crossword_grid(
    crossword: CrosswordGrid,
    output: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Zapíše cílovou mřížku atomicky jako YAML."""

    return _write_yaml_document(
        _crossword_grid_data(crossword),
        output,
        overwrite=overwrite,
        subject="cílovou mřížku",
    )


def dump_crossword_grid(crossword: CrosswordGrid, output: TextIO) -> None:
    """Zapíše cílovou mřížku jako YAML do textového proudu."""

    _dump_yaml_document_safely(
        _crossword_grid_data(crossword),
        output,
        subject="cílovou mřížku",
    )


def write_crossword_template(
    template: CrosswordTemplate,
    output: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Zapíše šablonu křížovky atomicky jako YAML."""

    return _write_yaml_document(
        _crossword_template_data(template),
        output,
        overwrite=overwrite,
        subject="šablonu křížovky",
    )


def dump_crossword_template(
    template: CrosswordTemplate,
    output: TextIO,
) -> None:
    """Zapíše šablonu křížovky jako YAML do textového proudu."""

    _dump_yaml_document_safely(
        _crossword_template_data(template),
        output,
        subject="šablonu křížovky",
    )

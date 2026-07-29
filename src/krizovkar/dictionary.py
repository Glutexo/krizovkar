"""Načtení a validace slovníku hesel a legend."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from krizovkar.alphabet import ANSWER_PATTERN
from krizovkar.localization import system_error_message


class DictionaryError(ValueError):
    """Slovník nelze načíst nebo nemá podporovaný obsah."""


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    """Jedno křížovkářské heslo a jeho možné legendy."""

    answer: str
    clues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrosswordDictionary:
    """Ověřený slovník v deterministickém pořadí hesel."""

    entries: tuple[DictionaryEntry, ...]

    def __len__(self) -> int:
        return len(self.entries)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DictionaryError(f"slovník obsahuje duplicitní klíč {key!r}")
        result[key] = value
    return result


DictionarySource = str | Path | TextIO


def _source_description(source: DictionarySource) -> str:
    if isinstance(source, (str, Path)):
        return str(Path(source))
    return "standardní vstup"


def _json_data(source: DictionarySource) -> Any:
    description = _source_description(source)
    try:
        if isinstance(source, (str, Path)):
            with Path(source).open(encoding="utf-8") as stream:
                return json.load(stream, object_pairs_hook=_unique_object)
        return json.load(source, object_pairs_hook=_unique_object)
    except OSError as error:
        raise DictionaryError(
            f"slovník nelze načíst ({description}): "
            f"{system_error_message(error)}"
        ) from error
    except UnicodeError as error:
        raise DictionaryError(
            f"slovník není platný text v UTF-8 ({description})"
        ) from error
    except json.JSONDecodeError as error:
        raise DictionaryError(
            f"slovník není platný JSON ({description}, řádek {error.lineno}, "
            f"sloupec {error.colno})"
        ) from error


def load_dictionary(source: DictionarySource) -> CrosswordDictionary:
    """Načte JSON objekt ze souboru nebo proudu a ověří jeho obsah."""

    data = _json_data(source)
    if not isinstance(data, dict):
        raise DictionaryError("slovník musí být JSON objekt")
    if not data:
        raise DictionaryError("slovník nesmí být prázdný")

    entries: list[DictionaryEntry] = []
    for answer in sorted(data):
        if ANSWER_PATTERN.fullmatch(answer) is None:
            raise DictionaryError(
                f"heslo {answer!r} musí obsahovat pouze podporovaná "
                "velká písmena"
            )

        raw_clues = data[answer]
        if not isinstance(raw_clues, list) or not raw_clues:
            raise DictionaryError(
                f"heslo {answer!r} musí mít neprázdný seznam legend"
            )

        clues: list[str] = []
        for clue_index, clue in enumerate(raw_clues):
            if not isinstance(clue, str) or not clue.strip():
                raise DictionaryError(
                    f"legenda [{clue_index}] hesla {answer!r} "
                    "musí být neprázdný text"
                )
            if clue in clues:
                raise DictionaryError(
                    f"heslo {answer!r} obsahuje duplicitní legendu {clue!r}"
                )
            clues.append(clue)

        entries.append(DictionaryEntry(answer=answer, clues=tuple(clues)))

    return CrosswordDictionary(entries=tuple(entries))

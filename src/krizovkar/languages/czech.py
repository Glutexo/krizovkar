"""Česká typografická a slovní pravidla pro texty v křížovce."""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import cache

import pyphen

NON_BREAKING_SPACE = "\N{NO-BREAK SPACE}"
SOFT_HYPHEN = "\N{SOFT HYPHEN}"
_CONSONANT_PREPOSITION = re.compile(
    r"(?<!\w)([KSVZksvz])[ \t\r\n]+(?=\S)"
)
_WORD = re.compile(r"[^\W\d_]+")


@cache
def _hyphenator() -> pyphen.Pyphen:
    return pyphen.Pyphen(lang="cs_CZ")


def protect_prepositions(text: str) -> str:
    """Spojí české jednopísmenné souhláskové předložky s dalším výrazem."""

    return _CONSONANT_PREPOSITION.sub(
        rf"\1{NON_BREAKING_SPACE}",
        text,
    )


def mark_hyphenation(text: str) -> str:
    """Vloží do českých slov neviditelná slovníková dělicí místa."""

    hyphenator = _hyphenator()
    return _WORD.sub(
        lambda match: hyphenator.inserted(match.group(), SOFT_HYPHEN),
        text,
    )


def unbreakable_word_boundaries(words: Sequence[str]) -> frozenset[int]:
    """Vrátí indexy slov, před nimiž česká pravidla zakazují zlom."""

    boundaries = set()
    for following_index in range(1, len(words)):
        pair = f"{words[following_index - 1]} {words[following_index]}"
        if protect_prepositions(pair) != pair:
            boundaries.add(following_index)
    return frozenset(boundaries)

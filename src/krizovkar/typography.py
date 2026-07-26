"""Česká typografická pravidla pro texty v křížovce."""

from __future__ import annotations

from functools import cache
import re

import pyphen


NON_BREAKING_SPACE = "\N{NO-BREAK SPACE}"
SOFT_HYPHEN = "\N{SOFT HYPHEN}"
_CONSONANT_PREPOSITION = re.compile(
    r"(?<!\w)([KSVZksvz])[ \t\r\n]+(?=\S)"
)
_CZECH_WORD = re.compile(r"[^\W\d_]+")


@cache
def _czech_hyphenator() -> pyphen.Pyphen:
    return pyphen.Pyphen(lang="cs_CZ")


def protect_czech_prepositions(text: str) -> str:
    """Spojí jednopísmenné souhláskové předložky s dalším výrazem."""

    return _CONSONANT_PREPOSITION.sub(
        rf"\1{NON_BREAKING_SPACE}",
        text,
    )


def mark_czech_hyphenation(text: str) -> str:
    """Vloží do českých slov neviditelná slovníková dělicí místa."""

    hyphenator = _czech_hyphenator()
    return _CZECH_WORD.sub(
        lambda match: hyphenator.inserted(match.group(), SOFT_HYPHEN),
        text,
    )

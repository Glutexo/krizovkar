"""Česká typografická pravidla pro texty v křížovce."""

from __future__ import annotations

import re


NON_BREAKING_SPACE = "\N{NO-BREAK SPACE}"
_CONSONANT_PREPOSITION = re.compile(
    r"(?<!\w)([KSVZksvz])[ \t\r\n]+(?=\S)"
)


def protect_czech_prepositions(text: str) -> str:
    """Spojí jednopísmenné souhláskové předložky s dalším výrazem."""

    return _CONSONANT_PREPOSITION.sub(
        rf"\1{NON_BREAKING_SPACE}",
        text,
    )

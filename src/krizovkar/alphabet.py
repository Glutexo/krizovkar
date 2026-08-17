"""Pravidla pro písmena používaná v české křížovce."""

from __future__ import annotations

import re

SUPPORTED_SINGLE_LETTERS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÁÄČĎÉĚÍŇÓÔÖŘŠŤÚŮÜÝŽ"
)
ANSWER_PATTERN = re.compile(f"[{SUPPORTED_SINGLE_LETTERS}]+")


def split_answer_letters(answer: str) -> tuple[str, ...]:
    """Rozdělí heslo na buňky; české ``CH`` tvoří jednu z nich."""

    if ANSWER_PATTERN.fullmatch(answer) is None:
        raise ValueError(f"nepodporované křížovkářské heslo: {answer!r}")

    letters: list[str] = []
    index = 0
    while index < len(answer):
        if answer.startswith("CH", index):
            letters.append("CH")
            index += 2
        else:
            letters.append(answer[index])
            index += 1
    return tuple(letters)

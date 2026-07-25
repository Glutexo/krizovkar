"""Příkazové rozhraní Křížovkáře."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from krizovkar.model import ModelError, load_crossword
from krizovkar.renderer import (
    DEFAULT_PAGE_FORMAT,
    SUPPORTED_PAGE_FORMATS,
    RenderError,
    render_pdf,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="krizovkar",
        description="Tvorba švédských, klasických a dalších křížovek.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    render = commands.add_parser(
        "render",
        help="vytvoří PDF z křížovky uložené v YAML",
        description="Načte a ověří YAML a vykreslí křížovkovou mřížku do PDF.",
    )
    render.add_argument("source", type=Path, metavar="VSTUP.yaml")
    render.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="VÝSTUP.pdf",
        help="cílový soubor; výchozí je VSTUP.pdf vedle YAML",
    )
    render.add_argument(
        "--force",
        action="store_true",
        help="povolí přepsání existujícího PDF",
    )
    render.add_argument(
        "--page-format",
        type=str.upper,
        choices=SUPPORTED_PAGE_FORMATS,
        default=DEFAULT_PAGE_FORMAT,
        metavar="FORMÁT",
        help=(
            "formát stránky: "
            f"{', '.join(SUPPORTED_PAGE_FORMATS)}; výchozí je {DEFAULT_PAGE_FORMAT}"
        ),
    )
    render.set_defaults(handler=_render)
    return parser


def _render(arguments: argparse.Namespace) -> int:
    output = arguments.output or arguments.source.with_suffix(".pdf")

    try:
        crossword = load_crossword(arguments.source)
        render_pdf(
            crossword,
            output,
            overwrite=arguments.force,
            page_format=arguments.page_format,
        )
    except (ModelError, RenderError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    print(f"PDF vytvořeno: {output}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Spustí příkazové rozhraní a vrátí jeho návratový kód."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)

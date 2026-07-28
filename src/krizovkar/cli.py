"""Příkazové rozhraní Křížovkáře."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from krizovkar.dictionary import DictionaryError, load_dictionary
from krizovkar.generator import (
    DEFAULT_GRID_HEIGHT,
    DEFAULT_GRID_WIDTH,
    DEFAULT_SEED,
    GenerationError,
    generate_swedish_grid,
    generate_swedish_template,
)
from krizovkar.model import (
    LegendCell,
    ModelError,
    load_crossword_grid,
    write_crossword_grid,
    write_crossword_template,
)
from krizovkar.renderer import (
    DEFAULT_PAGE_FORMAT,
    SUPPORTED_PAGE_FORMATS,
    RenderError,
    render_pdf,
)
from krizovkar.validation import validate_crossword_grid_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="krizovkar",
        description="Tvorba švédských, klasických a dalších křížovek.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    template = commands.add_parser(
        "template",
        help="vytvoří nevyplněnou hustou švédskou šablonu",
        description=(
            "Rozvrhne písmenné, legendové a nevyplňované buňky a "
            "zapíše sloty budoucích hesel bez použití slovníku."
        ),
    )
    template.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        metavar="ŠABLONA.yaml",
        help="cílový YAML soubor",
    )
    template.add_argument(
        "--width",
        type=int,
        default=DEFAULT_GRID_WIDTH,
        metavar="POČET",
        help=f"počet sloupců; výchozí je {DEFAULT_GRID_WIDTH}",
    )
    template.add_argument(
        "--height",
        type=int,
        default=DEFAULT_GRID_HEIGHT,
        metavar="POČET",
        help=f"počet řádků; výchozí je {DEFAULT_GRID_HEIGHT}",
    )
    template.add_argument(
        "--force",
        action="store_true",
        help="povolí přepsání existujícího YAML souboru",
    )
    template.set_defaults(handler=_template)

    generate = commands.add_parser(
        "generate",
        help="pokusně vytvoří švédskou mřížku z JSON slovníku",
        description=(
            "Vybere a propojí hesla z JSON slovníku a zapíše cílovou mřížku "
            "ve formátu YAML."
        ),
    )
    generate.add_argument("source", type=Path, metavar="SLOVNÍK.json")
    generate.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        metavar="MŘÍŽKA.yaml",
        help="cílový YAML soubor",
    )
    generate.add_argument(
        "--width",
        type=int,
        default=DEFAULT_GRID_WIDTH,
        metavar="POČET",
        help=f"počet sloupců; výchozí je {DEFAULT_GRID_WIDTH}",
    )
    generate.add_argument(
        "--height",
        type=int,
        default=DEFAULT_GRID_HEIGHT,
        metavar="POČET",
        help=f"počet řádků; výchozí je {DEFAULT_GRID_HEIGHT}",
    )
    generate.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        metavar="ČÍSLO",
        help=f"seed náhodných voleb; výchozí je {DEFAULT_SEED}",
    )
    generate.add_argument(
        "--force",
        action="store_true",
        help="povolí přepsání existujícího YAML souboru",
    )
    generate.set_defaults(handler=_generate)

    validate = commands.add_parser(
        "validate",
        help="odliší chyby dat od varování ke kvalitě mřížky",
        description=(
            "Ověří cílovou mřížku a posoudí společná pravidla pro vepsané "
            "i číselné legendy. Varování zpracování neblokují."
        ),
    )
    validate.add_argument("source", type=Path, metavar="MŘÍŽKA.yaml")
    validate.set_defaults(handler=_validate)

    render = commands.add_parser(
        "render",
        help="vytvoří PDF z cílové mřížky uložené v YAML",
        description=("Načte a ověří YAML typu grid a vykreslí cílovou mřížku do PDF."),
    )
    render.add_argument("source", type=Path, metavar="MŘÍŽKA.yaml")
    render.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="VÝSTUP.pdf",
        help="cílový soubor; výchozí je MŘÍŽKA.pdf vedle YAML",
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
    render.add_argument(
        "--blank",
        action="store_true",
        help=(
            "skryje písmena; legendy, pomůcky, zvýraznění a zobáčky tajenky "
            "zůstanou"
        ),
    )
    render.set_defaults(handler=_render)
    return parser


def _template(arguments: argparse.Namespace) -> int:
    try:
        template = generate_swedish_template(
            width=arguments.width,
            height=arguments.height,
        )
        write_crossword_template(
            template,
            arguments.output,
            overwrite=arguments.force,
        )
    except (GenerationError, ModelError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    print(
        f"Šablona vytvořena: {arguments.output} "
        f"({arguments.width} × {arguments.height}, {len(template.slots)} slotů)"
    )
    return 0


def _generate(arguments: argparse.Namespace) -> int:
    try:
        dictionary = load_dictionary(arguments.source)
        crossword = generate_swedish_grid(
            dictionary,
            width=arguments.width,
            height=arguments.height,
            seed=arguments.seed,
        )
        write_crossword_grid(
            crossword,
            arguments.output,
            overwrite=arguments.force,
        )
    except (DictionaryError, GenerationError, ModelError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    assert crossword.grid.cells is not None
    word_count = sum(
        len(cell.texts)
        for row in crossword.grid.cells
        for cell in row
        if isinstance(cell, LegendCell)
    )
    print(
        f"Mřížka vytvořena: {arguments.output} "
        f"({arguments.width} × {arguments.height}, {word_count} hesel, "
        f"seed {arguments.seed})"
    )
    return 0


def _render(arguments: argparse.Namespace) -> int:
    output = arguments.output or arguments.source.with_suffix(".pdf")

    try:
        crossword = load_crossword_grid(arguments.source)
        render_pdf(
            crossword,
            output,
            overwrite=arguments.force,
            page_format=arguments.page_format,
            filled=not arguments.blank,
        )
    except (ModelError, RenderError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    print(f"PDF vytvořeno: {output}")
    return 0


def _validate(arguments: argparse.Namespace) -> int:
    report = validate_crossword_grid_file(arguments.source)
    for issue in report.issues:
        label = "chyba" if issue.severity == "error" else "varování"
        print(
            f"{label} [{issue.code}] {issue.path}: {issue.message}",
            file=sys.stderr,
        )

    if report.errors:
        return 2

    if report.warnings:
        print(
            f"Mřížka je formálně platná: {arguments.source} "
            f"({len(report.warnings)} varování kvality)"
        )
    else:
        print(f"Mřížka je platná a bez varování: {arguments.source}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Spustí příkazové rozhraní a vrátí jeho návratový kód."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)

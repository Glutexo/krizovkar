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
    SecretRequirement,
    fill_crossword_template,
    generate_swedish_grid,
    generate_swedish_template,
    normalize_secret_text,
)
from krizovkar.model import (
    LegendCell,
    ModelError,
    SecretPrompt,
    load_crossword_grid,
    load_crossword_template,
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
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        metavar="ČÍSLO",
        help=(
            "seed výběru tajenkových slotů; "
            f"výchozí je {DEFAULT_SEED}"
        ),
    )
    _add_secret_arguments(template, allow_lengths=True)
    template.add_argument(
        "--force",
        action="store_true",
        help="povolí přepsání existujícího YAML souboru",
    )
    template.set_defaults(handler=_template)

    fill = commands.add_parser(
        "fill",
        help="vyplní uloženou šablonu hesly ze slovníku",
        description=(
            "Přiřadí různá hesla všem slotům šablony, dodrží jejich "
            "délky a písmena na kříženích a zapíše cílovou mřížku."
        ),
    )
    fill.add_argument("template", type=Path, metavar="ŠABLONA.yaml")
    fill.add_argument("dictionary", type=Path, metavar="SLOVNÍK.json")
    fill.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        metavar="MŘÍŽKA.yaml",
        help="cílový YAML soubor",
    )
    fill.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        metavar="ČÍSLO",
        help=f"seed náhodných voleb; výchozí je {DEFAULT_SEED}",
    )
    _add_secret_arguments(fill, allow_lengths=False)
    fill.add_argument(
        "--force",
        action="store_true",
        help="povolí přepsání existujícího YAML souboru",
    )
    fill.set_defaults(handler=_fill)

    generate = commands.add_parser(
        "generate",
        help="vytvoří vyplněnou švédskou mřížku z JSON slovníku",
        description=(
            "Vytvoří šablonu, volitelně do ní umístí konkrétní tajenku, "
            "vybere křížící se hesla z JSON slovníku a zapíše cílovou "
            "mřížku ve formátu YAML."
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
    _add_secret_arguments(generate, allow_lengths=False)
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


def _secret_part_lengths(value: str) -> tuple[int, ...]:
    try:
        lengths = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "délky částí musí být celá čísla oddělená čárkou"
        ) from error
    if not lengths or any(length < 1 for length in lengths):
        raise argparse.ArgumentTypeError(
            "délky částí musí být kladná celá čísla"
        )
    return lengths


def _add_secret_arguments(
    parser: argparse.ArgumentParser,
    *,
    allow_lengths: bool,
) -> None:
    group = parser.add_mutually_exclusive_group()
    if allow_lengths:
        group.add_argument(
            "--secret-length",
            type=int,
            metavar="POČET",
            help="rezervuje tajenku o zadaném celkovém počtu polí",
        )
        group.add_argument(
            "--secret-parts",
            type=_secret_part_lengths,
            metavar="DÉLKY",
            help="rezervuje pevné délky částí oddělené čárkou",
        )
    group.add_argument(
        "--secret",
        metavar="TEXT",
        help="konkrétní tajenka s automatickým dělením na švech slov",
    )
    group.add_argument(
        "--secret-part",
        action="append",
        metavar="TEXT",
        help="jedna pevná část tajenky; volbu lze zopakovat",
    )
    parser.add_argument(
        "--secret-prompt",
        metavar="TEXT",
        help="zadání tajenky zobrazené vně mřížky",
    )
    parser.add_argument(
        "--secret-prompt-placement",
        choices=("above", "below"),
        help="umístění zadání nad nebo pod mřížkou",
    )
    parser.add_argument(
        "--secret-prompt-alignment",
        choices=("left", "right"),
        help="zarovnání zadání doleva nebo doprava",
    )


def _secret_requirement(arguments: argparse.Namespace) -> SecretRequirement | None:
    total_length = getattr(arguments, "secret_length", None)
    part_lengths = getattr(arguments, "secret_parts", None)
    secret_text = getattr(arguments, "secret", None)
    raw_parts = getattr(arguments, "secret_part", None)
    prompt_text = getattr(arguments, "secret_prompt", None)
    prompt_placement = getattr(arguments, "secret_prompt_placement", None)
    prompt_alignment = getattr(arguments, "secret_prompt_alignment", None)
    if (
        total_length is None
        and part_lengths is None
        and secret_text is None
        and raw_parts is None
    ):
        if any((prompt_text, prompt_placement, prompt_alignment)):
            raise GenerationError(
                "zadání tajenky lze uvést jen společně s tajenkou"
            )
        return None

    if prompt_text is not None and not prompt_text.strip():
        raise GenerationError("zadání tajenky nesmí být prázdné")

    prompt = (
        SecretPrompt(
            text=prompt_text,
            placement=prompt_placement or "above",
            alignment=prompt_alignment or "left",
        )
        if prompt_text is not None
        else None
    )
    if prompt is None and any((prompt_placement, prompt_alignment)):
        raise GenerationError(
            "umístění a zarovnání vyžaduje --secret-prompt"
        )
    if total_length is not None:
        return SecretRequirement(total_length=total_length, prompt=prompt)
    if part_lengths is not None:
        return SecretRequirement(part_lengths=part_lengths, prompt=prompt)
    if secret_text is not None:
        return SecretRequirement(
            words=normalize_secret_text(secret_text),
            prompt=prompt,
        )

    assert raw_parts is not None
    normalized_parts = tuple(normalize_secret_text(part) for part in raw_parts)
    return SecretRequirement(
        words=tuple(word for part in normalized_parts for word in part),
        part_word_counts=tuple(len(part) for part in normalized_parts),
        prompt=prompt,
    )


def _template(arguments: argparse.Namespace) -> int:
    try:
        secret = _secret_requirement(arguments)
        template = generate_swedish_template(
            width=arguments.width,
            height=arguments.height,
            seed=arguments.seed,
            secret=secret,
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


def _fill(arguments: argparse.Namespace) -> int:
    try:
        secret = _secret_requirement(arguments)
        template = load_crossword_template(arguments.template)
        dictionary = load_dictionary(arguments.dictionary)
        crossword = fill_crossword_template(
            template,
            dictionary,
            seed=arguments.seed,
            secret=secret,
        )
        write_crossword_grid(
            crossword,
            arguments.output,
            overwrite=arguments.force,
        )
    except (DictionaryError, GenerationError, ModelError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    print(
        f"Mřížka vytvořena: {arguments.output} "
        f"({template.grid.width} × {template.grid.height}, "
        f"{len(template.slots)} hesel, seed {arguments.seed})"
    )
    return 0


def _generate(arguments: argparse.Namespace) -> int:
    try:
        secret = _secret_requirement(arguments)
        dictionary = load_dictionary(arguments.source)
        crossword = generate_swedish_grid(
            dictionary,
            width=arguments.width,
            height=arguments.height,
            seed=arguments.seed,
            secret=secret,
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

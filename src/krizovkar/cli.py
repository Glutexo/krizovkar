"""Příkazové rozhraní Křížovkáře."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, BinaryIO

from krizovkar.dictionary import DictionaryError, load_dictionary
from krizovkar.generator import (
    DEFAULT_GRID_HEIGHT,
    DEFAULT_GRID_WIDTH,
    DEFAULT_SEED,
    GenerationError,
    SecretRequirement,
    create_grid_from_template,
    fill_crossword_template,
    generate_numbered_grid,
    generate_numbered_template,
    generate_swedish_grid,
    generate_swedish_template,
    normalize_secret_text,
)
from krizovkar.model import (
    LegendCell,
    ModelError,
    SecretPrompt,
    dump_crossword_grid,
    dump_crossword_template,
    load_crossword_document_kind,
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
    render_pdf_stream,
)
from krizovkar.validation import validate_crossword_grid_file


LAYOUT_CHOICES = ("swedish", "numbered")
DEFAULT_LAYOUT = "swedish"


class _CzechHelpFormatter(argparse.HelpFormatter):
    """Formátuje automaticky vytvářený řádek použití česky."""

    def add_usage(
        self,
        usage: str | None,
        actions: Sequence[argparse.Action],
        groups: Sequence[argparse._MutuallyExclusiveGroup],
        prefix: str | None = None,
    ) -> None:
        super().add_usage(
            usage,
            actions,
            groups,
            prefix="použití: " if prefix is None else prefix,
        )


def _localize_parser_error(message: str) -> str:
    """Přeloží uživatelské chyby vytvářené knihovnou ``argparse``."""

    replacements = (
        ("the following arguments are required:", "je nutné zadat:"),
        ("unrecognized arguments:", "nerozpoznané argumenty:"),
        ("invalid choice:", "neplatná volba:"),
        ("(choose from ", "(vyberte z "),
        ("not allowed with argument", "nelze použít společně s argumentem"),
        ("ignored explicit argument", "neočekávaná hodnota argumentu"),
        ("expected at most one argument", "očekává se nejvýše jedna hodnota"),
        ("expected at least one argument", "očekává se alespoň jedna hodnota"),
        ("expected one argument", "očekává se jedna hodnota"),
        ("ambiguous option:", "nejednoznačná volba:"),
        (" could match ", " může znamenat "),
        ("unexpected option string:", "neočekávaná volba:"),
        ("conflicting subparser alias:", "opakovaný alias příkazu:"),
        ("conflicting subparser:", "opakovaný příkaz:"),
        ("unknown parser ", "neznámý příkaz "),
        (" (choices: ", " (možnosti: "),
    )
    for source, translation in replacements:
        message = message.replace(source, translation)

    message = re.sub(
        r"one of the arguments (.+) is required",
        r"je nutné zadat jeden z argumentů \1",
        message,
    )
    message = re.sub(
        r"expected (\d+) arguments?",
        r"očekávaný počet hodnot je \1",
        message,
    )
    message = re.sub(
        r"invalid ([^ ]+) value:",
        r"neplatná hodnota typu \1:",
        message,
    )
    message = re.sub(
        r"can't open (.+): .+",
        r"nelze otevřít \1",
        message,
    )
    return message


class _CzechArgumentParser(argparse.ArgumentParser):
    """Argument parser se všemi automatickými uživatelskými texty česky."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        add_help = kwargs.pop("add_help", True)
        kwargs.setdefault("formatter_class", _CzechHelpFormatter)
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = "poziční argumenty"
        self._optionals.title = "volby"
        if add_help:
            self.add_argument(
                "-h",
                "--help",
                action="help",
                default=argparse.SUPPRESS,
                help="zobrazí tuto nápovědu a skončí",
            )

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        localized_message = _localize_parser_error(message)
        self.exit(2, f"{self.prog}: chyba: {localized_message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = _CzechArgumentParser(
        prog="krizovkar",
        description="Tvorba švédských, klasických a dalších křížovek.",
    )
    commands = parser.add_subparsers(
        dest="příkaz",
        required=True,
        title="příkazy",
    )

    template = commands.add_parser(
        "template",
        help="vytvoří nevyplněnou hustou šablonu",
        description=(
            "Vytvoří švédské nebo číslované rozvržení a zapíše sloty "
            "budoucích hesel bez použití slovníku."
        ),
    )
    template.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="ŠABLONA.yaml",
        help="cílový YAML soubor; bez volby standardní výstup",
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
    _add_layout_argument(template)
    template.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        metavar="ČÍSLO",
        help=(
            "počáteční hodnota výběru tajenkových slotů; "
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

    grid = commands.add_parser(
        "grid",
        help="vytvoří nevyplněnou cílovou mřížku ze šablony",
        description=(
            "Převede role buněk a sloty šablony na nevyplněnou cílovou "
            "mřížku bez použití slovníku."
        ),
    )
    grid.add_argument(
        "template",
        type=Path,
        metavar="ŠABLONA.yaml",
        help="vstupní YAML šablona křížovky",
    )
    grid.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="MŘÍŽKA.yaml",
        help="cílový YAML soubor; bez volby standardní výstup",
    )
    grid.add_argument(
        "--force",
        action="store_true",
        help="povolí přepsání existujícího YAML souboru",
    )
    grid.set_defaults(handler=_grid)

    fill = commands.add_parser(
        "fill",
        help="vyplní uloženou šablonu hesly ze slovníku",
        description=(
            "Přiřadí různá hesla všem slotům šablony, dodrží jejich "
            "délky a písmena na kříženích a zapíše cílovou mřížku."
        ),
    )
    fill.add_argument(
        "template",
        type=Path,
        metavar="ŠABLONA.yaml",
        help="vstupní YAML šablona křížovky",
    )
    fill.add_argument(
        "dictionary",
        type=Path,
        metavar="SLOVNÍK.json",
        help="vstupní JSON slovník hesel a legend",
    )
    fill.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="MŘÍŽKA.yaml",
        help="cílový YAML soubor; bez volby standardní výstup",
    )
    fill.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        metavar="ČÍSLO",
        help=f"počáteční hodnota náhodných voleb; výchozí je {DEFAULT_SEED}",
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
        help="vytvoří vyplněnou mřížku z JSON slovníku",
        description=(
            "Vytvoří švédskou nebo číslovanou šablonu, volitelně do ní "
            "umístí konkrétní tajenku, vybere křížící se hesla z JSON "
            "slovníku a zapíše cílovou mřížku ve formátu YAML."
        ),
    )
    generate.add_argument(
        "source",
        type=Path,
        metavar="SLOVNÍK.json",
        help="vstupní JSON slovník hesel a legend",
    )
    generate.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="MŘÍŽKA.yaml",
        help="cílový YAML soubor; bez volby standardní výstup",
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
    _add_layout_argument(generate)
    generate.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        metavar="ČÍSLO",
        help=f"počáteční hodnota náhodných voleb; výchozí je {DEFAULT_SEED}",
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
    validate.add_argument(
        "source",
        type=Path,
        metavar="MŘÍŽKA.yaml",
        help="vstupní YAML cílové mřížky",
    )
    validate.set_defaults(handler=_validate)

    render = commands.add_parser(
        "render",
        help="vytvoří PDF z cílové mřížky nebo šablony",
        description=(
            "Načte a ověří YAML typu grid nebo template a vykreslí cílovou "
            "mřížku do PDF. Šablonu převede bez použití slovníku."
        ),
    )
    render.add_argument(
        "source",
        type=Path,
        metavar="VSTUP.yaml",
        help="vstupní YAML cílové mřížky nebo šablony",
    )
    render.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="VÝSTUP.pdf",
        help="cílový PDF soubor; bez volby standardní výstup",
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


def _add_layout_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--layout",
        choices=LAYOUT_CHOICES,
        default=DEFAULT_LAYOUT,
        help=(
            "automatické rozvržení: swedish s legendami v mřížce, "
            "nebo numbered s číslovanými vnějšími legendami; "
            f"výchozí je {DEFAULT_LAYOUT}"
        ),
    )


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


def _output_description(output: Path | None) -> str:
    return str(output) if output is not None else "standardní výstup"


def _czech_count(
    count: int,
    singular: str,
    few: str,
    many: str,
) -> str:
    if count == 1:
        noun = singular
    elif 2 <= count <= 4:
        noun = few
    else:
        noun = many
    return f"{count} {noun}"


def _print_success(message: str, output: Path | None) -> None:
    stream = sys.stdout if output is not None else sys.stderr
    print(message, file=stream)


def _binary_standard_output() -> BinaryIO:
    output = getattr(sys.stdout, "buffer", None)
    if output is None:
        raise RenderError("standardní výstup nepodporuje binární zápis")
    return output


def _template(arguments: argparse.Namespace) -> int:
    try:
        secret = _secret_requirement(arguments)
        generate_template = (
            generate_numbered_template
            if arguments.layout == "numbered"
            else generate_swedish_template
        )
        template = generate_template(
            width=arguments.width,
            height=arguments.height,
            seed=arguments.seed,
            secret=secret,
        )
        if arguments.output is None:
            dump_crossword_template(template, sys.stdout)
        else:
            write_crossword_template(
                template,
                arguments.output,
                overwrite=arguments.force,
            )
    except (GenerationError, ModelError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    _print_success(
        f"Šablona vytvořena: {_output_description(arguments.output)} "
        f"({arguments.width} × {arguments.height}, "
        f"{_czech_count(len(template.slots), 'slot', 'sloty', 'slotů')})",
        arguments.output,
    )
    return 0


def _grid(arguments: argparse.Namespace) -> int:
    try:
        template = load_crossword_template(arguments.template)
        crossword = create_grid_from_template(template)
        if arguments.output is None:
            dump_crossword_grid(crossword, sys.stdout)
        else:
            write_crossword_grid(
                crossword,
                arguments.output,
                overwrite=arguments.force,
            )
    except ModelError as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    _print_success(
        f"Nevyplněná mřížka vytvořena: "
        f"{_output_description(arguments.output)} "
        f"({template.grid.width} × {template.grid.height}, "
        f"{_czech_count(len(template.slots), 'slot', 'sloty', 'slotů')})",
        arguments.output,
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
        if arguments.output is None:
            dump_crossword_grid(crossword, sys.stdout)
        else:
            write_crossword_grid(
                crossword,
                arguments.output,
                overwrite=arguments.force,
            )
    except (DictionaryError, GenerationError, ModelError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    _print_success(
        f"Mřížka vytvořena: {_output_description(arguments.output)} "
        f"({template.grid.width} × {template.grid.height}, "
        f"{len(template.slots)} hesel, seed {arguments.seed})",
        arguments.output,
    )
    return 0


def _generate(arguments: argparse.Namespace) -> int:
    try:
        secret = _secret_requirement(arguments)
        dictionary = load_dictionary(arguments.source)
        generate_grid = (
            generate_numbered_grid
            if arguments.layout == "numbered"
            else generate_swedish_grid
        )
        crossword = generate_grid(
            dictionary,
            width=arguments.width,
            height=arguments.height,
            seed=arguments.seed,
            secret=secret,
        )
        if arguments.output is None:
            dump_crossword_grid(crossword, sys.stdout)
        else:
            write_crossword_grid(
                crossword,
                arguments.output,
                overwrite=arguments.force,
            )
    except (DictionaryError, GenerationError, ModelError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    assert crossword.grid.cells is not None
    word_count = len(crossword.clues) + sum(
        len(cell.texts)
        for row in crossword.grid.cells
        for cell in row
        if isinstance(cell, LegendCell)
    )
    _print_success(
        f"Mřížka vytvořena: {_output_description(arguments.output)} "
        f"({arguments.width} × {arguments.height}, {word_count} hesel, "
        f"seed {arguments.seed})",
        arguments.output,
    )
    return 0


def _render(arguments: argparse.Namespace) -> int:
    try:
        document_kind = load_crossword_document_kind(arguments.source)
        if document_kind == "grid":
            crossword = load_crossword_grid(arguments.source)
        elif document_kind == "template":
            template = load_crossword_template(arguments.source)
            crossword = create_grid_from_template(template)
        else:
            raise ModelError(
                "vykreslit lze pouze cílovou mřížku kind: grid nebo "
                f"šablonu kind: template; vstup má kind: {document_kind!r}"
            )
        if arguments.output is None:
            render_pdf_stream(
                crossword,
                _binary_standard_output(),
                page_format=arguments.page_format,
                filled=not arguments.blank,
            )
        else:
            render_pdf(
                crossword,
                arguments.output,
                overwrite=arguments.force,
                page_format=arguments.page_format,
                filled=not arguments.blank,
            )
    except (ModelError, RenderError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    _print_success(
        f"PDF vytvořeno: {_output_description(arguments.output)}",
        arguments.output,
    )
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

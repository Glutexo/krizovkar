"""Příkazové rozhraní Křížovkáře."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from io import StringIO
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from krizovkar.dictionary import DictionaryError, load_dictionary
from krizovkar.generator import (
    DEFAULT_GRID_HEIGHT,
    DEFAULT_GRID_WIDTH,
    DEFAULT_SEED,
    GenerationError,
    SecretRequirement,
    create_crossword_from_specification,
    create_grid_from_crossword,
    fill_crossword,
    generate_numbered_crossword,
    generate_swedish_crossword,
    normalize_secret_text,
)
from krizovkar.localization import ngettext, system_error_message
from krizovkar.model import (
    CrosswordGrid,
    ModelError,
    SecretPrompt,
    dump_crossword_document,
    dump_crossword_grid,
    load_crossword_document,
    load_crossword_document_kind,
    load_crossword_grid,
    load_crossword_specification,
    write_crossword_document,
    write_crossword_grid,
)
from krizovkar.renderer import (
    DEFAULT_PAGE_FORMAT,
    SUPPORTED_PAGE_FORMATS,
    RenderError,
    render_latex,
    render_latex_stream,
    render_pdf,
    render_pdf_stream,
)
from krizovkar.validation import validate_crossword_grid_file

LAYOUT_CHOICES = ("swedish", "numbered")
DEFAULT_LAYOUT = "swedish"
STANDARD_INPUT_PATH = Path("-")


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

    crossword = commands.add_parser(
        "crossword",
        help="vytvoří editovatelnou křížovku ze zadání nebo bez něj",
        description=(
            "Převede vstupní zadání na švédskou nebo číslovanou "
            "křížovku. Bez vstupního zadání vytvoří hustou nevyplněnou "
            "křížovku z rozměru, aniž použije slovník."
        ),
    )
    crossword.add_argument(
        "specification",
        nargs="?",
        type=Path,
        metavar="ZADÁNÍ.yaml",
        help="volitelné vstupní YAML zadání; - znamená standardní vstup",
    )
    crossword.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="KŘÍŽOVKA.yaml",
        help="cílový YAML soubor; bez volby standardní výstup",
    )
    crossword.add_argument(
        "--width",
        type=int,
        default=None,
        metavar="POČET",
        help=f"počet sloupců; výchozí je {DEFAULT_GRID_WIDTH}",
    )
    crossword.add_argument(
        "--height",
        type=int,
        default=None,
        metavar="POČET",
        help=f"počet řádků; výchozí je {DEFAULT_GRID_HEIGHT}",
    )
    _add_layout_argument(crossword)
    crossword.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="ČÍSLO",
        help=(
            "počáteční hodnota výběru tajenkových slotů; "
            f"výchozí je {DEFAULT_SEED}"
        ),
    )
    _add_secret_arguments(crossword, allow_lengths=True)
    crossword.add_argument(
        "--force",
        action="store_true",
        help="povolí přepsání existujícího YAML souboru",
    )
    crossword.set_defaults(handler=_crossword)

    grid = commands.add_parser(
        "grid",
        help="vytvoří cílovou mřížku z editovatelné křížovky",
        description=(
            "Převede role buněk a místa křížovky na cílovou mřížku bez "
            "použití slovníku. Případný pevný obsah slotů zachová."
        ),
    )
    grid.add_argument(
        "crossword",
        type=Path,
        metavar="KŘÍŽOVKA.yaml",
        help="vstupní YAML křížovka; - znamená standardní vstup",
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
        help="doplní prázdná místa křížovky hesly ze slovníku",
        description=(
            "Přiřadí různá hesla všem prázdným místům křížovky, dodrží jejich "
            "délky a písmena na kříženích a zapíše vyplněnou křížovku."
        ),
    )
    fill.add_argument(
        "crossword",
        type=Path,
        metavar="KŘÍŽOVKA.yaml",
        help="vstupní YAML křížovka; - znamená standardní vstup",
    )
    fill.add_argument(
        "dictionary",
        type=Path,
        metavar="SLOVNÍK.json",
        help="vstupní JSON slovník; - znamená standardní vstup",
    )
    fill.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="KŘÍŽOVKA.yaml",
        help="cílová YAML křížovka; bez volby standardní výstup",
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
        help="vstupní YAML cílové mřížky; - znamená standardní vstup",
    )
    validate.set_defaults(handler=_validate)

    latex = commands.add_parser(
        "latex",
        help="vytvoří LaTeXovou sazbu z cílové mřížky nebo křížovky",
        description=(
            "Načte a ověří YAML typu grid nebo crossword a vysází "
            "křížovku jako samostatně přeložitelný LaTeXový dokument."
        ),
    )
    latex.add_argument(
        "source",
        type=Path,
        metavar="VSTUP.yaml",
        help=(
            "vstupní YAML cílové mřížky nebo křížovky; "
            "- znamená standardní vstup"
        ),
    )
    latex.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="VÝSTUP.tex",
        help="cílový LaTeXový soubor; bez volby standardní výstup",
    )
    latex.add_argument(
        "--force",
        action="store_true",
        help="povolí přepsání existujícího LaTeXového souboru",
    )
    latex.add_argument(
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
    latex.add_argument(
        "--blank",
        action="store_true",
        help=(
            "skryje písmena; legendy, pomůcky, zvýraznění a zobáčky tajenky "
            "zůstanou"
        ),
    )
    latex.set_defaults(handler=_latex)

    render = commands.add_parser(
        "render",
        help="sestaví PDF přes LaTeX z cílové mřížky nebo křížovky",
        description=(
            "Načte a ověří YAML typu grid nebo crossword, vytvoří stejný "
            "LaTeXový dokument jako příkaz latex a přeloží jej pomocí "
            "LuaLaTeXu do PDF."
        ),
    )
    render.add_argument(
        "source",
        type=Path,
        metavar="VSTUP.yaml",
        help=(
            "vstupní YAML cílové mřížky nebo křížovky; "
            "- znamená standardní vstup"
        ),
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


def _input_source(source: Path) -> Path | TextIO:
    if source == STANDARD_INPUT_PATH:
        return sys.stdin
    return source


def _reusable_input_source(source: Path) -> Path | StringIO:
    if source != STANDARD_INPUT_PATH:
        return source
    try:
        return StringIO(sys.stdin.read())
    except OSError as error:
        raise ModelError(
            "standardní vstup nelze načíst: "
            f"{system_error_message(error)}"
        ) from error
    except UnicodeError as error:
        raise ModelError(
            "standardní vstup není platný text v UTF-8"
        ) from error


def _input_description(source: Path) -> str:
    if source == STANDARD_INPUT_PATH:
        return "standardní vstup"
    return str(source)


def _localized_count(
    count: int,
    singular: str,
    plural: str,
) -> str:
    return f"{count} {ngettext(singular, plural, count)}"


def _print_success(message: str, output: Path | None) -> None:
    stream = sys.stdout if output is not None else sys.stderr
    print(message, file=stream)


def _binary_standard_output() -> BinaryIO:
    output = getattr(sys.stdout, "buffer", None)
    if output is None:
        raise RenderError("standardní výstup nepodporuje binární zápis")
    return output


def _crossword(arguments: argparse.Namespace) -> int:
    try:
        if arguments.specification is not None:
            dense_options = (
                arguments.width,
                arguments.height,
                arguments.seed,
                arguments.secret_length,
                arguments.secret_parts,
                arguments.secret,
                arguments.secret_part,
                arguments.secret_prompt,
                arguments.secret_prompt_placement,
                arguments.secret_prompt_alignment,
            )
            if any(value is not None for value in dense_options):
                raise GenerationError(
                    "při převodu zadání nelze použít --width, --height, "
                    "--seed ani volby tajenky"
                )
            specification = load_crossword_specification(
                _input_source(arguments.specification)
            )
            crossword = create_crossword_from_specification(
                specification,
                layout=arguments.layout,
            )
        else:
            secret = _secret_requirement(arguments)
            generate_crossword = (
                generate_numbered_crossword
                if arguments.layout == "numbered"
                else generate_swedish_crossword
            )
            crossword = generate_crossword(
                width=(
                    arguments.width
                    if arguments.width is not None
                    else DEFAULT_GRID_WIDTH
                ),
                height=(
                    arguments.height
                    if arguments.height is not None
                    else DEFAULT_GRID_HEIGHT
                ),
                seed=(
                    arguments.seed
                    if arguments.seed is not None
                    else DEFAULT_SEED
                ),
                secret=secret,
            )
        if arguments.output is None:
            dump_crossword_document(crossword, sys.stdout)
        else:
            write_crossword_document(
                crossword,
                arguments.output,
                overwrite=arguments.force,
            )
    except (GenerationError, ModelError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    _print_success(
        f"Křížovka vytvořena: {_output_description(arguments.output)} "
        f"({crossword.grid.width} × {crossword.grid.height}, "
        f"{_localized_count(len(crossword.slots), 'heslo', 'hesel')})",
        arguments.output,
    )
    return 0


def _grid(arguments: argparse.Namespace) -> int:
    try:
        crossword = load_crossword_document(
            _input_source(arguments.crossword)
        )
        grid = create_grid_from_crossword(crossword)
        if arguments.output is None:
            dump_crossword_grid(grid, sys.stdout)
        else:
            write_crossword_grid(
                grid,
                arguments.output,
                overwrite=arguments.force,
            )
    except ModelError as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    _print_success(
        f"Mřížka z křížovky vytvořena: {_output_description(arguments.output)} "
        f"({crossword.grid.width} × {crossword.grid.height}, "
        f"{_localized_count(len(crossword.slots), 'heslo', 'hesel')})",
        arguments.output,
    )
    return 0


def _fill(arguments: argparse.Namespace) -> int:
    try:
        if (
            arguments.crossword == STANDARD_INPUT_PATH
            and arguments.dictionary == STANDARD_INPUT_PATH
        ):
            raise ModelError(
                "standardní vstup nelze u příkazu fill použít zároveň "
                "pro křížovku i slovník"
            )
        secret = _secret_requirement(arguments)
        crossword = load_crossword_document(
            _input_source(arguments.crossword)
        )
        dictionary = load_dictionary(_input_source(arguments.dictionary))
        crossword = fill_crossword(
            crossword,
            dictionary,
            seed=arguments.seed,
            secret=secret,
        )
        if arguments.output is None:
            dump_crossword_document(crossword, sys.stdout)
        else:
            write_crossword_document(
                crossword,
                arguments.output,
                overwrite=arguments.force,
            )
    except (DictionaryError, GenerationError, ModelError) as error:
        print(f"chyba: {error}", file=sys.stderr)
        return 2

    _print_success(
        f"Křížovka vyplněna: {_output_description(arguments.output)} "
        f"({crossword.grid.width} × {crossword.grid.height}, "
        f"{_localized_count(len(crossword.slots), 'heslo', 'hesel')}, "
        f"seed {arguments.seed})",
        arguments.output,
    )
    return 0


def _load_renderable_crossword(source_path: Path) -> CrosswordGrid:
    source = _reusable_input_source(source_path)
    document_kind = load_crossword_document_kind(source)
    if isinstance(source, StringIO):
        source.seek(0)
    if document_kind == "grid":
        return load_crossword_grid(source)
    if document_kind == "crossword":
        crossword = load_crossword_document(source)
        return create_grid_from_crossword(crossword)
    raise ModelError(
        "sázet lze pouze cílovou mřížku kind: grid nebo křížovku "
        "kind: crossword; vstup má "
        f"kind: {document_kind!r}"
    )


def _latex(arguments: argparse.Namespace) -> int:
    try:
        crossword = _load_renderable_crossword(arguments.source)
        if arguments.output is None:
            render_latex_stream(
                crossword,
                sys.stdout,
                page_format=arguments.page_format,
                filled=not arguments.blank,
            )
        else:
            render_latex(
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
        f"LaTeX vytvořen: {_output_description(arguments.output)}",
        arguments.output,
    )
    return 0


def _render(arguments: argparse.Namespace) -> int:
    try:
        crossword = _load_renderable_crossword(arguments.source)
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
    report = validate_crossword_grid_file(_input_source(arguments.source))
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
            f"Mřížka je formálně platná: "
            f"{_input_description(arguments.source)} "
            f"({len(report.warnings)} varování kvality)"
        )
    else:
        print(
            "Mřížka je platná a bez varování: "
            f"{_input_description(arguments.source)}"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Spustí příkazové rozhraní a vrátí jeho návratový kód."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)

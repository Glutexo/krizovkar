"""Nástroje pro práci s křížovkami."""

from krizovkar.dictionary import (
    CrosswordDictionary,
    DictionaryEntry,
    DictionaryError,
    load_dictionary,
)
from krizovkar.generator import GenerationError, generate_swedish_grid

from krizovkar.model import (
    Coordinate,
    CrosswordGrid,
    CrosswordSpecification,
    EmptyCell,
    Grid,
    GridCell,
    GridDimensions,
    HelpCell,
    LegendArrow,
    LegendCell,
    LetterCell,
    ModelError,
    SecretCell,
    WordDirection,
    WordPlacement,
    load_crossword_grid,
    load_crossword_specification,
    write_crossword_grid,
)
from krizovkar.renderer import RenderError, render_pdf
from krizovkar.validation import (
    ValidationIssue,
    ValidationReport,
    check_dense_swedish_grid,
    validate_dense_swedish_grid_file,
)

__all__ = [
    "Coordinate",
    "CrosswordDictionary",
    "CrosswordGrid",
    "CrosswordSpecification",
    "DictionaryEntry",
    "DictionaryError",
    "EmptyCell",
    "Grid",
    "GridCell",
    "GridDimensions",
    "GenerationError",
    "HelpCell",
    "LegendArrow",
    "LegendCell",
    "LetterCell",
    "ModelError",
    "RenderError",
    "SecretCell",
    "ValidationIssue",
    "ValidationReport",
    "WordDirection",
    "WordPlacement",
    "check_dense_swedish_grid",
    "generate_swedish_grid",
    "load_dictionary",
    "load_crossword_grid",
    "load_crossword_specification",
    "render_pdf",
    "validate_dense_swedish_grid_file",
    "write_crossword_grid",
]

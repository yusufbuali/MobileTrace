"""Parser dispatcher — selects the correct parser for a given file."""
from pathlib import Path
from .base import BaseParser, ParsedCase
from .ufdr_parser import UfdrParser
from .xry_parser import XryParser
from .oxygen_parser import OxygenParser

_PARSERS: list[BaseParser] = [UfdrParser(), XryParser(), OxygenParser()]


def dispatch(source_path: Path, dest_dir: Path) -> ParsedCase:
    """Find the right parser and parse. Raises ValueError if none match."""
    for parser in _PARSERS:
        if parser.can_handle(source_path):
            return parser.parse(source_path, dest_dir)
    raise ValueError(f"No parser found for: {source_path}")


def detect_format(source_path: Path) -> str | None:
    for parser in _PARSERS:
        if parser.can_handle(source_path):
            return parser.__class__.__name__.replace("Parser", "").lower()
    return None

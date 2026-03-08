"""Parser dispatcher — selects the correct parser for a given file."""
from pathlib import Path
from .base import BaseParser, ParsedCase
from .ufdr_parser import UfdrParser
from .xry_parser import XryParser
from .oxygen_parser import OxygenParser
from .ios_parser import iOSParser
from .android_parser import AndroidParser

_PARSERS: list[BaseParser] = [
    UfdrParser(),
    AndroidParser(),   # before XRY/iOS — checks ZIP+TAR with data/data/ marker
    XryParser(),
    OxygenParser(),
    iOSParser(),
]


def dispatch(source_path: Path, dest_dir: Path, **kwargs) -> ParsedCase:
    """Find the right parser and parse. Raises ValueError if none match."""
    for parser in _PARSERS:
        if parser.can_handle(source_path):
            return parser.parse(source_path, dest_dir, **kwargs)
    raise ValueError(f"No parser found for: {source_path}")


def detect_format(source_path: Path) -> str | None:
    for parser in _PARSERS:
        if parser.can_handle(source_path):
            name = parser.__class__.__name__
            # iOSParser -> "ios_fs"
            if name == "iOSParser":
                return "ios_fs"
            if name == "AndroidParser":
                return "android_tar"
            return name.replace("Parser", "").lower()
    return None

"""Parser registry and selection."""

from __future__ import annotations

from pathlib import Path

from finance_tooling.parsers.base import StatementParser
from finance_tooling.parsers.boursobank import BoursobankParser
from finance_tooling.parsers.generic import GenericParser
from finance_tooling.parsers.hsbc import HsbcParser
from finance_tooling.parsers.labanquepostale import LaBanquePostaleParser
from finance_tooling.parsers.revolut import RevolutParser

PARSERS: tuple[StatementParser, ...] = (
    LaBanquePostaleParser(),
    RevolutParser(),
    BoursobankParser(),
    HsbcParser(),
    GenericParser(),
)


def select_parser(file_path: Path, first_page_text: str) -> StatementParser:
    """Select the most appropriate parser for the given statement."""
    for parser in PARSERS:
        if parser.can_handle(file_path, first_page_text):
            return parser
    return GenericParser()

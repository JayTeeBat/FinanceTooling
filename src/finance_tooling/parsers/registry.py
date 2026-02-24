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

_MIN_MATCH_SCORE = 2


def select_parser(file_path: Path, first_page_text: str) -> StatementParser:
    """Select the most appropriate parser for the given statement."""
    scored: list[tuple[int, int, StatementParser]] = []
    for index, parser in enumerate(PARSERS):
        score = parser.match_score(file_path, first_page_text)
        scored.append((score, -index, parser))

    best_score, _, best_parser = max(scored, key=lambda item: (item[0], item[1]))
    if best_score >= _MIN_MATCH_SCORE:
        return best_parser
    return GenericParser()

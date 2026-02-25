"""Parser registry and selection."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ParserScoreItem:
    parser_name: str
    score: int


@dataclass(frozen=True)
class ParserSelection:
    parser: StatementParser
    score: int
    threshold: int
    candidates: tuple[ParserScoreItem, ...]


def select_parser_with_diagnostics(file_path: Path, first_page_text: str) -> ParserSelection:
    """Select parser and return routing diagnostics."""
    scored: list[tuple[int, int, StatementParser]] = []
    for index, parser in enumerate(PARSERS):
        score = parser.match_score(file_path, first_page_text)
        scored.append((score, -index, parser))

    ranked = sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)
    candidates = tuple(
        ParserScoreItem(parser_name=parser.name, score=score) for score, _, parser in ranked
    )

    best_score, _, best_parser = ranked[0]
    if best_score >= _MIN_MATCH_SCORE:
        return ParserSelection(
            parser=best_parser,
            score=best_score,
            threshold=_MIN_MATCH_SCORE,
            candidates=candidates,
        )

    return ParserSelection(
        parser=GenericParser(),
        score=best_score,
        threshold=_MIN_MATCH_SCORE,
        candidates=candidates,
    )


def select_parser(file_path: Path, first_page_text: str) -> StatementParser:
    """Select the most appropriate parser for the given statement."""
    return select_parser_with_diagnostics(file_path, first_page_text).parser

"""Bank statement parser registry."""

from finance_tooling.parsers.registry import (
    PARSERS,
    ParserScoreItem,
    ParserSelection,
    select_parser,
    select_parser_with_diagnostics,
)

__all__ = [
    "PARSERS",
    "ParserScoreItem",
    "ParserSelection",
    "select_parser",
    "select_parser_with_diagnostics",
]

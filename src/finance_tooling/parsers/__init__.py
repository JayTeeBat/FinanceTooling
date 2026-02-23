"""Bank statement parser registry."""

from finance_tooling.parsers.registry import PARSERS, select_parser

__all__ = ["PARSERS", "select_parser"]

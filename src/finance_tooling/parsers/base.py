"""Parser interfaces and helper dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from finance_tooling.models import Transaction


@dataclass(frozen=True)
class ParserOutput:
    """Result of parsing a single statement file."""

    transactions: list[Transaction]
    warnings: list[str]


class StatementParser(Protocol):
    """Protocol implemented by bank statement parsers."""

    name: str
    bank: str

    def can_handle(self, file_path: Path, first_page_text: str) -> bool: ...

    def parse(self, file_path: Path, full_text: str) -> ParserOutput: ...

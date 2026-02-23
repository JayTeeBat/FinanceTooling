"""HSBC UK statement parser."""

from __future__ import annotations

import re
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput
from finance_tooling.parsers.common import parse_date, parse_decimal

_LINE_PATTERN = re.compile(
    r"^(\d{2}\s[A-Za-z]{3}\s\d{2,4})\s+"
    r"(.+?)\s+"
    r"(-?\d[\d,.]*)\s+"
    r"(-?\d[\d,.]*)$"
)
_POSITIVE_HINTS = ("SALARY", "PAYMENT IN", "TRANSFER FROM", "INTEREST", "REFUND")
_SKIP_HINTS = ("BALANCEBROUGHTFORWARD", "BALANCECARRIEDFORWARD")


class HsbcParser:
    """Parser for HSBC statement transaction rows."""

    name = "hsbc"
    bank = "HSBC"

    def can_handle(self, file_path: Path, first_page_text: str) -> bool:
        marker = f"{file_path.name} {first_page_text}".lower()
        return "hsbc" in marker or "your statement" in marker

    def parse(self, file_path: Path, full_text: str) -> ParserOutput:
        transactions: list[Transaction] = []
        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            match = _LINE_PATTERN.match(line)
            if not match:
                continue

            description = match.group(2)
            if any(skip in description for skip in _SKIP_HINTS):
                continue

            booking_date = parse_date(match.group(1))
            amount = parse_decimal(match.group(3))
            if booking_date is None or amount is None:
                continue

            if not any(hint in description.upper() for hint in _POSITIVE_HINTS):
                amount = -amount

            transactions.append(
                Transaction(
                    booking_date=booking_date,
                    description=description,
                    amount_native=amount,
                    currency="GBP",
                    source_file=file_path,
                    bank=self.bank,
                    parser=self.name,
                )
            )

        return ParserOutput(transactions=transactions, warnings=[])

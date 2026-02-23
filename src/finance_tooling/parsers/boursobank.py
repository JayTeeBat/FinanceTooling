"""Boursobank statement parser."""

from __future__ import annotations

import re
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput
from finance_tooling.parsers.common import parse_date, parse_decimal

_LINE_PATTERN = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s*(.+?)\s+(\d{2}/\d{2}/\d{4})?\s*(-?\d[\d\s,.]*,\d{2})$"
)
_POSITIVE_HINTS = (
    "VIRSEPA",
    "VIREMENT",
    "VIR INST",
    "VIR INSTANTANE",
    "CREDIT",
    "REMBOURSEMENT",
    "VERSEMENT",
)


class BoursobankParser:
    """Parser for Boursobank account movement lines."""

    name = "boursobank"
    bank = "Boursobank"

    def can_handle(self, file_path: Path, first_page_text: str) -> bool:
        marker = f"{file_path.name} {first_page_text}".lower()
        if "revolut" in marker and "account-statement" in marker:
            return False
        return "boursobank" in marker or "boursorama" in marker

    def parse(self, file_path: Path, full_text: str) -> ParserOutput:
        transactions: list[Transaction] = []

        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            match = _LINE_PATTERN.match(line)
            if not match:
                continue

            booking_date = parse_date(match.group(1))
            amount = parse_decimal(match.group(4))
            if booking_date is None or amount is None:
                continue

            description = match.group(2)
            if not any(hint in description.upper() for hint in _POSITIVE_HINTS):
                amount = -amount

            transactions.append(
                Transaction(
                    booking_date=booking_date,
                    description=description,
                    amount_native=amount,
                    currency="EUR",
                    source_file=file_path,
                    bank=self.bank,
                    parser=self.name,
                )
            )

        return ParserOutput(transactions=transactions, warnings=[])

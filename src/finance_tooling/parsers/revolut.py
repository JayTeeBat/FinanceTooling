"""Revolut account statement parser."""

from __future__ import annotations

import re
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput
from finance_tooling.parsers.common import detect_currency, parse_date, parse_decimal

_LINE_PATTERN = re.compile(
    r"^(\d{1,2}\s[A-Za-z]{3}\s\d{4})\s+"
    r"(.+?)\s+"
    r"([€£$]?-?\d[\d,.]*)\s+"
    r"([€£$]?\d[\d,.]*)$"
)
_NEGATIVE_HINTS = ("TO ", "CARD PAYMENT", "ATM", "WITHDRAWAL", "EXCHANGE")
_POSITIVE_HINTS = ("PAYMENT FROM", "TRANSFER FROM", "REFUND", "REVERSAL")


class RevolutParser:
    """Parser for Revolut annual account statements."""

    name = "revolut"
    bank = "Revolut"

    def can_handle(self, file_path: Path, first_page_text: str) -> bool:
        marker = f"{file_path.name} {first_page_text}".lower()
        return "revolut" in marker and "account-statement" in marker

    def parse(self, file_path: Path, full_text: str) -> ParserOutput:
        transactions: list[Transaction] = []

        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            match = _LINE_PATTERN.match(line)
            if not match:
                continue

            booking_date = parse_date(match.group(1))
            description = match.group(2)
            raw_amount = match.group(3)
            amount = parse_decimal(_strip_currency_symbol(raw_amount))
            if booking_date is None or amount is None:
                continue

            description_upper = description.upper()
            amount = abs(amount)
            if any(hint in description_upper for hint in _POSITIVE_HINTS):
                amount = abs(amount)
            elif any(hint in description_upper for hint in _NEGATIVE_HINTS):
                amount = -abs(amount)
            else:
                amount = -abs(amount)

            transactions.append(
                Transaction(
                    booking_date=booking_date,
                    description=description,
                    amount_native=amount,
                    currency=detect_currency(raw_amount),
                    source_file=file_path,
                    bank=self.bank,
                    parser=self.name,
                )
            )

        return ParserOutput(transactions=transactions, warnings=[])


def _strip_currency_symbol(token: str) -> str:
    return token.replace("€", "").replace("£", "").replace("$", "")

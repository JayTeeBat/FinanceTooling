"""Generic fallback parser for unknown statement layouts."""

from __future__ import annotations

import re
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput
from finance_tooling.parsers.common import detect_currency, parse_date, parse_decimal

_DATE_REGEX = re.compile(r"\b(\d{1,4}[/-]\d{1,2}[/-]\d{2,4})\b")
_AMOUNT_REGEX = re.compile(r"[-+]?\(?\d[\d,.\s]*\d(?:[.,]\d{1,2})?\)?-?")


class GenericParser:
    """Regex-based fallback parser."""

    name = "generic"
    bank = "Unknown"

    def can_handle(self, file_path: Path, first_page_text: str) -> bool:
        return True

    def parse(self, file_path: Path, full_text: str) -> ParserOutput:
        transactions: list[Transaction] = []

        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue

            date_match = _DATE_REGEX.search(line)
            if not date_match:
                continue
            booking_date = parse_date(date_match.group(1))
            if booking_date is None:
                continue

            amount_matches = list(_AMOUNT_REGEX.finditer(line))
            if not amount_matches:
                continue
            amount_token = amount_matches[-1].group(0)
            amount = parse_decimal(amount_token)
            if amount is None:
                continue

            description = line.replace(date_match.group(0), "", 1)
            description = description.replace(amount_token, "", 1)
            description = description.strip(" -:\t") or "Unknown transaction"

            transactions.append(
                Transaction(
                    booking_date=booking_date,
                    description=description,
                    amount_native=amount,
                    currency=detect_currency(line),
                    source_file=file_path,
                    bank=self.bank,
                    parser=self.name,
                )
            )

        return ParserOutput(transactions=transactions, warnings=[])

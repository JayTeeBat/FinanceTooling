"""La Banque Postale statement parser."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput, StatementValidation
from finance_tooling.parsers.common import parse_decimal

_DAY_MONTH_PATTERN = re.compile(r"(0[1-9]|[12][0-9]|3[01])[/\-](0[1-9]|1[012])")
_FILE_YEAR_PATTERN = re.compile(
    r"((?:19|20)\d{2})[/-]?(0[1-9]|1[012])[/-]?(0[1-9]|[12][0-9]|3[01])"
)
_TRANSACTION_PATTERN = re.compile(
    r"\n\s*(\d{2}/\d{2})\s+"
    r"([^\n]*?)\s"
    r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.| )\d{3})+), ?\d{2}?)"
    r"(?:\n((?!\s*\d{2}/\d{2}).*))?"
)
_TOTAL_PATTERN = re.compile(
    r"Total\s?des\s?op.rations\s"
    r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.|\s)\d{3})+),\s?\d{2}?)\s"
    r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.|\s)\d{3})+),\s?\d{2}?)"
)
_CREDIT_HINTS = (
    "VIREMENT DE",
    "VIREMENT INSTANTANE DE",
    "CREDIT DU",
    "CREDIT CARTE BANCAIRE",
    "REMISE DE CHEQUES",
    "AVANTAGE CREDIT IMMOBILIER",
)


class LaBanquePostaleParser:
    """Parser for La Banque Postale monthly account statements."""

    name = "labanquepostale"
    bank = "LaBanquePostale"

    def can_handle(self, file_path: Path, first_page_text: str) -> bool:
        marker = f"{file_path.name} {first_page_text}".lower()
        return (
            "labanquepostale" in marker
            or "la banque postale" in marker
            or "releve_ccp" in marker
            or "releve de votre ccp" in marker
        )

    def parse(self, file_path: Path, full_text: str) -> ParserOutput:
        year = self._resolve_year(file_path.name)
        warnings: list[str] = []
        transactions: list[Transaction] = []

        matches = _TRANSACTION_PATTERN.findall(f"\n{full_text}")
        for match in matches:
            day, month = _DAY_MONTH_PATTERN.findall(match[0])[0]
            amount = parse_decimal(match[2])
            if amount is None:
                continue

            # By legacy behavior, operation amounts are spending by default.
            amount = amount * Decimal("-1")
            if any(hint.lower() in match[1].lower() for hint in _CREDIT_HINTS):
                amount = amount * Decimal("-1")

            details = match[3] if len(match) > 3 else ""
            description = " ".join([match[1].strip(), details.strip()]).strip()

            transactions.append(
                Transaction(
                    booking_date=date(year, int(month), int(day)),
                    description=description or "Unknown transaction",
                    amount_native=amount,
                    currency="EUR",
                    source_file=file_path,
                    bank=self.bank,
                    parser=self.name,
                )
            )

        transaction_sum = sum((tx.amount_native for tx in transactions), start=Decimal("0"))
        total_matches = _TOTAL_PATTERN.findall(full_text)
        if total_matches and transactions:
            debit = parse_decimal(total_matches[-1][0])
            credit = parse_decimal(total_matches[-1][1])
            if debit is not None and credit is not None:
                expected = -debit + credit
                if transaction_sum != expected:
                    warnings.append(
                        f"{file_path.name}: totals mismatch expected {expected} "
                        f"but parsed {transaction_sum}"
                    )

        validation = StatementValidation(
            source_file=file_path,
            bank=self.bank,
            parser=self.name,
            statement_type="statement",
            opening_balance=None,
            closing_balance=None,
            transaction_sum=transaction_sum,
            expected_closing_balance=None,
            difference=None,
            status="uncheckable",
            reason="missing_opening_or_closing",
            severity="info",
        )
        return ParserOutput(transactions=transactions, warnings=warnings, validation=validation)

    @staticmethod
    def _resolve_year(filename: str) -> int:
        matches = _FILE_YEAR_PATTERN.findall(filename)
        if matches:
            return int(matches[0][0])
        return date.today().year

"""HSBC UK statement parser."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput, StatementValidation
from finance_tooling.parsers.common import parse_date, parse_decimal

_LINE_PATTERN = re.compile(
    r"^(\d{2}\s[A-Za-z]{3}\s\d{2,4})\s+"
    r"(.+?)\s+"
    r"(-?\d[\d,.]*)\s+"
    r"(-?\d[\d,.]*)$"
)
_COMPACT_LINE_PATTERN = re.compile(
    r"^(\d{2}[A-Za-z]{3}\d{2,4})\s+"
    r"(.+?)\s+"
    r"(-?\d[\d,.]*)\s+"
    r"(-?\d[\d,.]*)$"
)
_POSITIVE_HINTS = ("SALARY", "PAYMENT IN", "TRANSFER FROM", "INTEREST", "REFUND")
_SKIP_HINTS = ("BALANCEBROUGHTFORWARD", "BALANCECARRIEDFORWARD")
_OPENING_PATTERN = re.compile(r"Opening\s*Balance\s+(-?\d[\d,.]*)", re.IGNORECASE)
_CLOSING_PATTERN = re.compile(r"Closing\s*Balance\s+(-?\d[\d,.]*)", re.IGNORECASE)


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
            match = _LINE_PATTERN.match(line) or _COMPACT_LINE_PATTERN.match(line)
            if not match:
                continue

            description = match.group(2)
            if any(skip in description for skip in _SKIP_HINTS):
                continue

            booking_date = parse_date(_normalize_compact_date(match.group(1)))
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

        transaction_sum = sum((tx.amount_native for tx in transactions), start=Decimal("0"))
        opening_balance = _extract_balance(full_text, _OPENING_PATTERN)
        closing_balance = _extract_balance(full_text, _CLOSING_PATTERN)
        validation, validation_warning = _build_validation(
            file_path=file_path,
            bank=self.bank,
            parser=self.name,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            transaction_sum=transaction_sum,
        )
        warnings: list[str] = []
        if validation_warning:
            warnings.append(validation_warning)
        return ParserOutput(transactions=transactions, warnings=warnings, validation=validation)


def _normalize_compact_date(raw_date: str) -> str:
    compact = re.fullmatch(r"(\d{2})([A-Za-z]{3})(\d{2,4})", raw_date)
    if compact is None:
        return raw_date
    return f"{compact.group(1)} {compact.group(2)} {compact.group(3)}"


def _extract_balance(full_text: str, pattern: re.Pattern[str]) -> Decimal | None:
    match = pattern.search(" ".join(full_text.split()))
    if match is None:
        return None
    return parse_decimal(match.group(1))


def _build_validation(
    *,
    file_path: Path,
    bank: str,
    parser: str,
    opening_balance: Decimal | None,
    closing_balance: Decimal | None,
    transaction_sum: Decimal,
) -> tuple[StatementValidation, str | None]:
    if opening_balance is None or closing_balance is None:
        return (
            StatementValidation(
                source_file=file_path,
                bank=bank,
                parser=parser,
                statement_type="statement",
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                transaction_sum=transaction_sum,
                expected_closing_balance=None,
                difference=None,
                status="uncheckable",
                reason="missing_opening_or_closing",
                severity="info",
            ),
            None,
        )

    expected = opening_balance + transaction_sum
    difference = expected - closing_balance
    if abs(difference) <= Decimal("0.01"):
        return (
            StatementValidation(
                source_file=file_path,
                bank=bank,
                parser=parser,
                statement_type="statement",
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                transaction_sum=transaction_sum,
                expected_closing_balance=expected,
                difference=difference,
                status="pass",
                reason=None,
                severity="none",
            ),
            None,
        )

    warning = (
        f"{file_path.name}: reconciliation mismatch opening {opening_balance} + "
        f"transactions {transaction_sum} = {expected} but closing is {closing_balance} "
        f"(diff {difference})"
    )
    return (
        StatementValidation(
            source_file=file_path,
            bank=bank,
            parser=parser,
            statement_type="statement",
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            transaction_sum=transaction_sum,
            expected_closing_balance=expected,
            difference=difference,
            status="fail",
            reason="balance_mismatch",
            severity="warning",
        ),
        warning,
    )

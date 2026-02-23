"""Revolut account statement parser."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput, StatementValidation
from finance_tooling.parsers.common import detect_currency, parse_date, parse_decimal

_LINE_PATTERN = re.compile(
    r"^(\d{1,2}\s[A-Za-z]{3}\s\d{4})\s+"
    r"(.+?)\s+"
    r"([€£$]?-?\d[\d,.]*)\s+"
    r"([€£$]?\d[\d,.]*)$"
)
_NEGATIVE_HINTS = ("TO ", "CARD PAYMENT", "ATM", "WITHDRAWAL", "EXCHANGE")
_POSITIVE_HINTS = ("PAYMENT FROM", "TRANSFER FROM", "REFUND", "REVERSAL")
_SUMMARY_ACCOUNT_PATTERN = re.compile(
    r"Account\s*\(E-Money\)\s+([€£$]?-?\d[\d,.]*)\s+([€£$]?-?\d[\d,.]*)\s+"
    r"([€£$]?-?\d[\d,.]*)\s+([€£$]?-?\d[\d,.]*)",
    re.IGNORECASE,
)


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

        transaction_sum = sum((tx.amount_native for tx in transactions), start=Decimal("0"))
        opening_balance, closing_balance = _extract_summary_balances(full_text)
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


def _strip_currency_symbol(token: str) -> str:
    return token.replace("€", "").replace("£", "").replace("$", "")


def _extract_summary_balances(full_text: str) -> tuple[Decimal | None, Decimal | None]:
    flattened = " ".join(full_text.split())
    match = _SUMMARY_ACCOUNT_PATTERN.search(flattened)
    if match is None:
        return None, None
    opening = parse_decimal(_strip_currency_symbol(match.group(1)))
    closing = parse_decimal(_strip_currency_symbol(match.group(4)))
    return opening, closing


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

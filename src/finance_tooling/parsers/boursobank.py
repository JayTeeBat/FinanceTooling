"""Boursobank statement parser."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput, StatementValidation
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
_BALANCE_PATTERN = re.compile(r"SOLDE\s+AU\s*:?\s*(?:\d{2}/\d{2}/\d{4})?\s*(-?\d[\d\s,.]*,\d{2})")


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

        transaction_sum = sum((tx.amount_native for tx in transactions), start=Decimal("0"))
        balances = _extract_balances(full_text)
        validation, validation_warning = _build_validation(
            file_path=file_path,
            bank=self.bank,
            parser=self.name,
            transaction_sum=transaction_sum,
            balances=balances,
        )
        warnings: list[str] = []
        if validation_warning:
            warnings.append(validation_warning)
        return ParserOutput(transactions=transactions, warnings=warnings, validation=validation)


def _extract_balances(full_text: str) -> list[Decimal]:
    balances: list[Decimal] = []
    for raw_line in full_text.splitlines():
        line = " ".join(raw_line.split())
        match = _BALANCE_PATTERN.search(line)
        if match is None:
            continue
        balance = parse_decimal(match.group(1))
        if balance is not None:
            balances.append(balance)
    return balances


def _build_validation(
    *,
    file_path: Path,
    bank: str,
    parser: str,
    transaction_sum: Decimal,
    balances: list[Decimal],
) -> tuple[StatementValidation, str | None]:
    if len(balances) < 2:
        return (
            StatementValidation(
                source_file=file_path,
                bank=bank,
                parser=parser,
                statement_type="statement",
                opening_balance=balances[0] if balances else None,
                closing_balance=None,
                transaction_sum=transaction_sum,
                expected_closing_balance=None,
                difference=None,
                status="uncheckable",
                reason="missing_opening_or_closing",
                severity="info",
            ),
            None,
        )

    opening_balance = balances[0]
    closing_balance = balances[-1]
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

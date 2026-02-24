"""Boursobank statement parser."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from finance_tooling.parsers.base import (
    BaseStatementParser,
    NormalizeConfig,
    ParsedRow,
    ValidationPayload,
)
from finance_tooling.parsers.common import parse_decimal

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


class BoursobankParser(BaseStatementParser):
    """Parser for Boursobank account movement lines."""

    name = "boursobank"
    bank = "Boursobank"

    def can_handle(self, file_path: Path, first_page_text: str) -> bool:
        marker = f"{file_path.name} {first_page_text}".lower()
        if "revolut" in marker and "account-statement" in marker:
            return False
        return "boursobank" in marker or "boursorama" in marker

    def _extract_rows(self, file_path: Path, full_text: str) -> tuple[list[ParsedRow], list[str]]:
        del file_path
        rows: list[ParsedRow] = []

        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            match = _LINE_PATTERN.match(line)
            if not match:
                continue

            rows.append(
                ParsedRow(
                    raw_date=match.group(1),
                    raw_description=match.group(2),
                    raw_amount=match.group(4),
                    raw_currency_hint="EUR",
                )
            )

        return rows, []

    def _normalize_config(self) -> NormalizeConfig:
        return NormalizeConfig(
            sign_mode="debit_default_with_positive_hints",
            default_currency="EUR",
            positive_hints=_POSITIVE_HINTS,
            description_fallback="Unknown transaction",
        )

    def _build_validation_payload(
        self,
        file_path: Path,
        full_text: str,
        transaction_sum: Decimal,
    ) -> ValidationPayload:
        del file_path, transaction_sum
        balances = _extract_balances(full_text)
        opening_balance = balances[0] if balances else None
        closing_balance = balances[-1] if len(balances) >= 2 else None
        return ValidationPayload(
            mode="balance",
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            reason="missing_opening_or_closing",
            severity="info",
        )


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

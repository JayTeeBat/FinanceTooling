"""Revolut account statement parser."""

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
    r"^(\d{1,2}\s[A-Za-z]{3,9}\s\d{4})\s+"
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
_ACCOUNT_TRANSACTIONS_START = re.compile(r"^Account transactions from\b", re.IGNORECASE)
_ACCOUNT_TRANSACTIONS_STOP = re.compile(
    r"^(Reverted from\b|Personal and Group Pockets transactions\b)",
    re.IGNORECASE,
)
_SEPT_PATTERN = re.compile(r"\bSept\b", re.IGNORECASE)
_SIGN_TOLERANCE = Decimal("0.02")


def _normalize_revolut_date(raw_date: str) -> str:
    return _SEPT_PATTERN.sub("Sep", raw_date)


class RevolutParser(BaseStatementParser):
    """Parser for Revolut annual account statements."""

    name = "revolut"
    bank = "Revolut"

    def _filename_markers(self) -> tuple[str, ...]:
        return ("revolut", "account-statement")

    def _content_markers(self) -> tuple[str, ...]:
        return ("revolut", "account-statement")

    def _extract_rows(self, file_path: Path, full_text: str) -> tuple[list[ParsedRow], list[str]]:
        del file_path
        opening_balance, _ = _extract_summary_balances(full_text)
        raw_rows = _extract_account_rows(full_text)
        if not raw_rows:
            raw_rows = _extract_rows_without_section_scope(full_text)

        rows: list[ParsedRow] = []
        previous_balance = opening_balance

        for (
            raw_date,
            raw_description,
            raw_amount_with_currency,
            raw_balance_with_currency,
        ) in raw_rows:
            amount = parse_decimal(_strip_currency_symbol(raw_amount_with_currency))
            running_balance = parse_decimal(_strip_currency_symbol(raw_balance_with_currency))
            if amount is None or running_balance is None:
                continue

            signed_amount = _signed_amount_from_balance(
                amount=amount,
                description=raw_description,
                previous_balance=previous_balance,
                running_balance=running_balance,
            )
            previous_balance = running_balance
            rows.append(
                ParsedRow(
                    raw_date=_normalize_revolut_date(raw_date),
                    raw_description=raw_description,
                    raw_amount=str(signed_amount),
                    raw_currency_hint=raw_amount_with_currency,
                )
            )

        return rows, []

    def _normalize_config(self) -> NormalizeConfig:
        return NormalizeConfig(
            sign_mode="explicit_sign",
            default_currency="UNKNOWN",
            positive_hints=_POSITIVE_HINTS,
            negative_hints=_NEGATIVE_HINTS,
            description_fallback="Unknown transaction",
        )

    def _build_validation_payload(
        self,
        file_path: Path,
        full_text: str,
        transaction_sum: Decimal,
    ) -> ValidationPayload:
        del file_path, transaction_sum
        opening_balance, closing_balance = _extract_summary_balances(full_text)
        return ValidationPayload(
            mode="balance",
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            reason="missing_opening_or_closing",
            severity="info",
        )


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


def _extract_account_rows(full_text: str) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    in_account_transactions = False

    for raw_line in full_text.splitlines():
        line = " ".join(raw_line.split())
        if _ACCOUNT_TRANSACTIONS_START.match(line):
            in_account_transactions = True
            continue
        if in_account_transactions and _ACCOUNT_TRANSACTIONS_STOP.match(line):
            break
        if not in_account_transactions:
            continue

        match = _LINE_PATTERN.match(line)
        if match is None:
            continue
        rows.append((match.group(1), match.group(2), match.group(3), match.group(4)))

    return rows


def _extract_rows_without_section_scope(full_text: str) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for raw_line in full_text.splitlines():
        line = " ".join(raw_line.split())
        match = _LINE_PATTERN.match(line)
        if match is None:
            continue
        rows.append((match.group(1), match.group(2), match.group(3), match.group(4)))
    return rows


def _signed_amount_from_balance(
    *,
    amount: Decimal,
    description: str,
    previous_balance: Decimal | None,
    running_balance: Decimal,
) -> Decimal:
    amount_abs = abs(amount)
    if previous_balance is None:
        return _signed_amount_from_description(amount_abs, description)

    delta = running_balance - previous_balance
    if abs(delta - amount_abs) <= _SIGN_TOLERANCE:
        return amount_abs
    if abs(delta + amount_abs) <= _SIGN_TOLERANCE:
        return -amount_abs
    return delta


def _signed_amount_from_description(amount_abs: Decimal, description: str) -> Decimal:
    description_upper = description.upper()
    if any(hint in description_upper for hint in _NEGATIVE_HINTS):
        return -amount_abs
    if any(hint in description_upper for hint in _POSITIVE_HINTS):
        return amount_abs
    return -amount_abs

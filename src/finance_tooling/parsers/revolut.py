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


class RevolutParser(BaseStatementParser):
    """Parser for Revolut annual account statements."""

    name = "revolut"
    bank = "Revolut"

    def can_handle(self, file_path: Path, first_page_text: str) -> bool:
        marker = f"{file_path.name} {first_page_text}".lower()
        return "revolut" in marker and "account-statement" in marker

    def _filename_markers(self) -> tuple[str, ...]:
        return ("revolut", "account-statement")

    def _content_markers(self) -> tuple[str, ...]:
        return ("revolut", "account-statement")

    def _extract_rows(self, file_path: Path, full_text: str) -> tuple[list[ParsedRow], list[str]]:
        del file_path
        rows: list[ParsedRow] = []

        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            match = _LINE_PATTERN.match(line)
            if not match:
                continue

            raw_amount = match.group(3)
            rows.append(
                ParsedRow(
                    raw_date=match.group(1),
                    raw_description=match.group(2),
                    raw_amount=_strip_currency_symbol(raw_amount),
                    raw_currency_hint=raw_amount,
                )
            )

        return rows, []

    def _normalize_config(self) -> NormalizeConfig:
        return NormalizeConfig(
            sign_mode="debit_default_with_positive_hints",
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

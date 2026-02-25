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
    r"^\s*(\d{2}/\d{2}/\d{4})\s*(.+?)\s+(\d{2}/\d{2}/\d{4})?\s+(-?\d[\d\s,.]*,\d{2})\s*$"
)
_FORCE_POSITIVE_HINTS = ("AVOIR", "REMBOURSEMENT")
_CREDIT_COLUMN_MIN_START = 70
_OPENING_BALANCE_PATTERNS = (
    re.compile(r"SOLDE\s*AU\s*:?\s*(?:\d{2}/\d{2}/\d{4})?\s*(-?\d[\d\s,.]*,\d{2})", re.IGNORECASE),
)
_CLOSING_BALANCE_PATTERNS = (
    re.compile(
        r"NOUVEAU\s*SOLDE(?:\s*EN\s*EUR)?\s*:?\s*(-?\d[\d\s,.]*,\d{2})",
        re.IGNORECASE,
    ),
)


class BoursobankParser(BaseStatementParser):
    """Parser for Boursobank account movement lines."""

    name = "boursobank"
    bank = "Boursobank"

    def _filename_markers(self) -> tuple[str, ...]:
        return ("boursobank", "boursorama")

    def _content_markers(self) -> tuple[str, ...]:
        return ("boursobank", "boursorama")

    def _negative_markers(self) -> tuple[str, ...]:
        return ("account-statement",)

    def _extract_rows(self, file_path: Path, full_text: str) -> tuple[list[ParsedRow], list[str]]:
        del file_path
        rows: list[ParsedRow] = []
        warnings: list[str] = []

        for raw_line in full_text.splitlines():
            match = _LINE_PATTERN.match(raw_line)
            if not match:
                continue

            raw_amount = match.group(4).strip()
            signed_amount, warning = _signed_amount_from_row(
                raw_amount=raw_amount,
                raw_description=match.group(2),
                raw_line=raw_line,
            )
            if warning is not None:
                warnings.append(warning)
            if signed_amount is None:
                continue

            rows.append(
                ParsedRow(
                    raw_date=match.group(1),
                    raw_description=match.group(2),
                    raw_amount=str(signed_amount),
                    raw_currency_hint="EUR",
                )
            )

        return rows, warnings

    def _normalize_config(self) -> NormalizeConfig:
        return NormalizeConfig(
            sign_mode="explicit_sign",
            default_currency="EUR",
            positive_hints=(),
            description_fallback="Unknown transaction",
        )

    def _build_validation_payload(
        self,
        file_path: Path,
        full_text: str,
        transaction_sum: Decimal,
    ) -> ValidationPayload:
        del file_path, transaction_sum
        opening_balance = _extract_balance(full_text, _OPENING_BALANCE_PATTERNS, keep="first")
        closing_balance = _extract_balance(full_text, _CLOSING_BALANCE_PATTERNS, keep="last")
        return ValidationPayload(
            mode="balance",
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            reason="missing_opening_or_closing",
            severity="info",
        )


def _signed_amount_from_row(
    *,
    raw_amount: str,
    raw_description: str,
    raw_line: str,
) -> tuple[Decimal | None, str | None]:
    amount = parse_decimal(raw_amount)
    if amount is None:
        return None, None

    description_upper = raw_description.upper()
    if raw_amount.strip().startswith("-"):
        return -abs(amount), None

    if any(hint in description_upper for hint in _FORCE_POSITIVE_HINTS):
        return abs(amount), None

    amount_start = raw_line.rfind(raw_amount)
    if amount_start < 0:
        return (
            None,
            "Skipped Boursobank row with ambiguous amount position for sign inference: "
            f"{raw_description!r}",
        )

    if amount_start >= _CREDIT_COLUMN_MIN_START:
        return abs(amount), None
    return -abs(amount), None


def _extract_balance(
    full_text: str,
    patterns: tuple[re.Pattern[str], ...],
    *,
    keep: str,
) -> Decimal | None:
    selected: Decimal | None = None
    for raw_line in full_text.splitlines():
        line = " ".join(raw_line.split())
        for pattern in patterns:
            match = pattern.search(line)
            if match is None:
                continue
            parsed = parse_decimal(match.group(1))
            if parsed is None:
                continue
            selected = parsed
            if keep == "first":
                return selected
            break
    return selected

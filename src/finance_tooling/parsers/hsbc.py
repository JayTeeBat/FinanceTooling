"""HSBC UK statement parser."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import (
    BaseStatementParser,
    NormalizeConfig,
    ParsedRow,
    ValidationPayload,
)
from finance_tooling.parsers.common import parse_decimal

_DATE_PREFIX_PATTERN = re.compile(r"^(?P<date>(?:\d{1,2}\s*[A-Za-z]{3}\s*\d{2,4}))\s+(?P<rest>.+)$")
_AMOUNT_TOKEN_PATTERN = re.compile(
    r"(?P<amount>[+-]?\d[\d,]*(?:\.\d{2}|,\d{2})(?:\s?(?:CR|DR))?)",
    re.IGNORECASE,
)
_POSITIVE_HINTS = ("SALARY", "PAYMENT IN", "TRANSFER FROM", "INTEREST", "REFUND")
_NEGATIVE_HINTS = ("DR_MARKER",)
_POSITIVE_MARKERS = ("CR_MARKER",)
_SKIP_HINTS = (
    "BALANCEBROUGHTFORWARD",
    "BALANCE CARRIED FORWARD",
    "BALANCECARRIEDFORWARD",
)
_OPENING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Opening\s*Balance\s+([+-]?\d[\d,.]*(?:\s?(?:CR|DR))?)", re.IGNORECASE),
    re.compile(
        r"Balance\s*Brought\s*Forward\s*(?:\.\s*)?([+-]?\d[\d,.]*(?:\s?(?:CR|DR))?)",
        re.IGNORECASE,
    ),
    re.compile(r"Previous\s*Balance\s+([+-]?\d[\d,.]*(?:\s?(?:CR|DR))?)", re.IGNORECASE),
)
_CLOSING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Closing\s*Balance\s+([+-]?\d[\d,.]*(?:\s?(?:CR|DR))?)", re.IGNORECASE),
    re.compile(
        r"Balance\s*Carried\s*Forward\s*(?:\.\s*)?([+-]?\d[\d,.]*(?:\s?(?:CR|DR))?)",
        re.IGNORECASE,
    ),
    re.compile(r"New\s*Balance\s+([+-]?\d[\d,.]*(?:\s?(?:CR|DR))?)", re.IGNORECASE),
)
_DESCRIPTION_SIGN_PATTERN = re.compile(r"^(?P<marker>CR|DR)\b", re.IGNORECASE)


class HsbcParser(BaseStatementParser):
    """Parser for HSBC statement transaction rows."""

    name = "hsbc"
    bank = "HSBC"

    def _filename_markers(self) -> tuple[str, ...]:
        return ("hsbc",)

    def _content_markers(self) -> tuple[str, ...]:
        return ("hsbc", "your statement")

    def _extract_rows(self, file_path: Path, full_text: str) -> tuple[list[ParsedRow], list[str]]:
        del file_path
        rows: list[ParsedRow] = []
        pending_date: str | None = None
        pending_description: str = ""

        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue

            match = _DATE_PREFIX_PATTERN.match(line)
            if match is not None:
                row = _parse_statement_row(
                    raw_date=match.group("date"),
                    rest=match.group("rest"),
                )
                if row is not None:
                    rows.append(row)
                    pending_date = None
                    pending_description = ""
                    continue

                pending_date = match.group("date")
                pending_description = match.group("rest")
                continue

            if pending_date is None:
                continue

            row = _parse_statement_row(
                raw_date=pending_date,
                rest=f"{pending_description} {line}",
            )
            if row is not None:
                rows.append(row)
            pending_date = None
            pending_description = ""

        return rows, []

    def _normalize_config(self) -> NormalizeConfig:
        return NormalizeConfig(
            sign_mode="hint_priority_with_default_debit",
            default_currency="GBP",
            positive_hints=_POSITIVE_HINTS + _POSITIVE_MARKERS,
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
        opening_balance = _extract_balance(full_text, _OPENING_PATTERNS)
        closing_balance = _extract_balance(full_text, _CLOSING_PATTERNS)
        return ValidationPayload(
            mode="balance",
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            reason="missing_opening_or_closing",
            severity="info",
        )

    def _post_normalization_warnings(
        self,
        file_path: Path,
        full_text: str,
        transactions: list[Transaction],
    ) -> list[str]:
        opening_balance = _extract_balance(full_text, _OPENING_PATTERNS)
        closing_balance = _extract_balance(full_text, _CLOSING_PATTERNS)
        if opening_balance is not None and closing_balance is not None and not transactions:
            return [
                (
                    f"{file_path.name}: balances were detected but no transactions were parsed; "
                    "HSBC row extraction may have missed this statement format"
                )
            ]
        return []


def _normalize_compact_date(raw_date: str) -> str:
    compact = re.fullmatch(r"(\d{1,2})\s*([A-Za-z]{3})\s*(\d{2,4})", raw_date)
    if compact is None:
        return raw_date
    return f"{compact.group(1).zfill(2)} {compact.group(2)} {compact.group(3)}"


def _extract_balance(full_text: str, patterns: tuple[re.Pattern[str], ...]) -> Decimal | None:
    flattened = " ".join(full_text.split())
    for pattern in patterns:
        match = pattern.search(flattened)
        if match is None:
            continue
        parsed = _parse_amount_token(match.group(1))
        if parsed is not None:
            return parsed
    return None


def _parse_statement_row(raw_date: str, rest: str) -> ParsedRow | None:
    matches = list(_AMOUNT_TOKEN_PATTERN.finditer(rest))
    if not matches:
        return None
    transaction_token = (
        matches[-2].group("amount") if len(matches) >= 2 else matches[-1].group("amount")
    )
    description = rest[: matches[-2].start() if len(matches) >= 2 else matches[-1].start()].strip()
    if not description:
        return None
    description_upper = description.upper()
    if any(skip in description_upper for skip in _SKIP_HINTS):
        return None
    indicator_marker = _token_sign_marker(transaction_token) or _description_sign_marker(
        description
    )
    amount = _parse_amount_token(transaction_token)
    if amount is None:
        return None
    if indicator_marker is not None:
        description = f"{description} {indicator_marker}"
    return ParsedRow(
        raw_date=_normalize_compact_date(raw_date),
        raw_description=description,
        raw_amount=str(abs(amount)),
        raw_currency_hint="GBP",
    )


def _parse_amount_token(token: str) -> Decimal | None:
    normalized = token.strip().replace(" ", "")
    upper = normalized.upper()
    if upper.endswith("CR"):
        parsed = parse_decimal(normalized[:-2])
        return None if parsed is None else abs(parsed)
    if upper.endswith("DR"):
        parsed = parse_decimal(normalized[:-2])
        return None if parsed is None else -abs(parsed)
    return parse_decimal(normalized)


def _token_sign_marker(token: str) -> str | None:
    upper = token.strip().replace(" ", "").upper()
    if upper.endswith("CR"):
        return "CR_MARKER"
    if upper.endswith("DR"):
        return "DR_MARKER"
    return None


def _description_sign_marker(description: str) -> str | None:
    match = _DESCRIPTION_SIGN_PATTERN.match(description.strip())
    if match is None:
        return None
    marker = match.group("marker").upper()
    if marker == "CR":
        return "CR_MARKER"
    if marker == "DR":
        return "DR_MARKER"
    return None

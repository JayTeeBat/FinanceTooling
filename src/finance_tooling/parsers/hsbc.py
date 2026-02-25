"""HSBC UK statement parser."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
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
_NOISE_PREFIXES = (
    "CONTACT TEL",
    "TEXT PHONE",
    "WWW.HSBC",
    "PO BOX",
    "YOUR STATEMENT",
    "ACCOUNT NAME",
    "DATE PAYMENT TYPE",
    "INTERNATIONAL BANK ACCOUNT NUMBER",
    "BRANCH IDENTIFIER CODE",
    "ACCOUNT SUMMARY",
    "SORTCODE",
    "ACCOUNT NUMBER",
    "SHEET NUMBER",
)
_NOISE_SUBSTRINGS = (
    "FINANCIAL SERVICES COMPENSATION SCHEME",
    "MONTHLY CAP ON UNARRANGED OVERDRAFT CHARGES",
    "CREDIT INTEREST IS CALCULATED DAILY",
    "PAYMENT SCHEME EXCHANGE RATES",
    "NON-STERLING CASH FEE",
    "COMMERCIAL BANKING CUSTOMERS",
    "BUSINESS PRICE LIST",
    "DEAF OR SPEECH IMPAIRED CUSTOMERS",
    "USED BY DEAF OR SPEECH IMPAIRED CUSTOMERS",
)
_NON_TXN_BALANCE_MARKERS = (
    "OPENINGBALANCE",
    "CLOSINGBALANCE",
    "PAYMENTSIN",
    "PAYMENTSOUT",
    "BALANCEBROUGHTFORWARD",
    "BALANCECARRIEDFORWARD",
)
_TXN_PREFIXES = ("VIS", "DD", "ATM", "BP", "SO", "CR", "DR", ")))")
_TXN_CONTEXT_HINTS = (
    "CARD",
    "PAYMENT",
    "TRANSFER",
    "WITHDRAWAL",
    "CASH",
    "PURCHASE",
    "DIRECT DEBIT",
    "DEBIT",
)


@dataclass(frozen=True)
class _ParsedBlock:
    raw_date: str
    header_text: str
    continuation_lines: list[str]


@dataclass(frozen=True)
class _ParsedRowCandidate:
    row: ParsedRow
    amount_absolute: Decimal
    running_balance: Decimal | None
    marker_source: str | None


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
        blocks: list[_ParsedBlock] = []
        current_date: str | None = None
        current_header: str = ""
        current_continuations: list[str] = []

        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue

            match = _DATE_PREFIX_PATTERN.match(line)
            if match is not None:
                if current_date is not None:
                    blocks.append(
                        _ParsedBlock(
                            raw_date=current_date,
                            header_text=current_header,
                            continuation_lines=current_continuations,
                        )
                    )
                current_date = match.group("date")
                current_header = match.group("rest")
                current_continuations = []
                continue

            if current_date is not None:
                current_continuations.append(line)

        if current_date is not None:
            blocks.append(
                _ParsedBlock(
                    raw_date=current_date,
                    header_text=current_header,
                    continuation_lines=current_continuations,
                )
            )
        for block in blocks:
            rows.extend(_rows_from_block(block))

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


def _rows_from_block(block: _ParsedBlock) -> list[ParsedRow]:
    rows: list[_ParsedRowCandidate] = []
    pending_context_parts: list[str] = []
    pending_has_txn_prefix = False
    pending_sign_marker: str | None = None
    previous_running_balance: Decimal | None = None

    header_row = _parse_statement_row_candidate(block.raw_date, block.header_text)
    if header_row is not None:
        header_row, previous_running_balance = _apply_running_balance_sign_override(
            header_row,
            previous_running_balance,
        )
        rows = _append_or_merge_duplicate_candidate(rows, header_row)
        if header_row.running_balance is not None:
            previous_running_balance = header_row.running_balance
    elif not _is_non_transaction_line(block.header_text):
        pending_context_parts = [block.header_text]
        pending_has_txn_prefix = _has_transaction_context(block.header_text)
        pending_sign_marker = _description_sign_marker(block.header_text)

    for line in block.continuation_lines:
        if _is_non_transaction_line(line):
            pending_context_parts = []
            pending_has_txn_prefix = False
            pending_sign_marker = None
            continue

        if _is_non_transaction_context_line(line):
            pending_context_parts = []
            pending_has_txn_prefix = False
            pending_sign_marker = None
            continue

        if not _contains_amount(line):
            pending_context_parts.append(line)
            if _has_transaction_context(line):
                pending_has_txn_prefix = True
                pending_sign_marker = _description_sign_marker(line)
            continue

        line_is_txn = _starts_with_transaction_prefix(line)
        if not line_is_txn and not pending_has_txn_prefix:
            pending_context_parts = []
            pending_has_txn_prefix = False
            pending_sign_marker = None
            continue

        fallback_context = " ".join(part for part in pending_context_parts if part).strip()
        row = _parse_statement_row_candidate(
            block.raw_date,
            line,
            fallback_context=fallback_context if fallback_context else None,
            inherited_sign_marker=pending_sign_marker if not line_is_txn else None,
        )
        if row is not None:
            row, previous_running_balance = _apply_running_balance_sign_override(
                row,
                previous_running_balance,
            )
            rows = _append_or_merge_duplicate_candidate(rows, row)
            if row.running_balance is not None:
                previous_running_balance = row.running_balance
        pending_context_parts = []
        pending_has_txn_prefix = False
        pending_sign_marker = None

    return [candidate.row for candidate in rows]


def _parse_statement_row_candidate(
    raw_date: str,
    rest: str,
    *,
    fallback_context: str | None = None,
    inherited_sign_marker: str | None = None,
) -> _ParsedRowCandidate | None:
    if _is_non_transaction_line(rest):
        return None

    matches = list(_AMOUNT_TOKEN_PATTERN.finditer(rest))
    if not matches:
        return None
    selected = _select_transaction_match(rest, matches)
    if selected is None:
        return None

    transaction_token = selected.group("amount")
    description_lead = rest[: selected.start()].strip()
    description = (
        f"{fallback_context} {description_lead}".strip() if fallback_context else description_lead
    )
    if not description:
        return None
    description_upper = description.upper()
    if any(skip in description_upper for skip in _SKIP_HINTS):
        return None
    # Fallback context can carry unrelated CR/DR text from previous lines; infer
    # description marker only from the transaction line lead itself.
    token_marker = _token_sign_marker(transaction_token)
    description_marker = _description_sign_marker(description_lead)
    indicator_marker = token_marker or description_marker
    if indicator_marker is None:
        indicator_marker = inherited_sign_marker
    marker_source: str | None = None
    if token_marker is not None:
        marker_source = "token"
    elif description_marker is not None:
        marker_source = "description"
    elif inherited_sign_marker is not None:
        marker_source = "inherited"
    amount = _parse_amount_token(transaction_token)
    if amount is None:
        return None
    running_balance: Decimal | None = None
    if len(matches) > 1:
        running_balance = _parse_amount_token(matches[-1].group("amount"))
    if indicator_marker is not None:
        description = f"{description} {indicator_marker}"
    row = ParsedRow(
        raw_date=_normalize_compact_date(raw_date),
        raw_description=description,
        raw_amount=str(abs(amount)),
        raw_currency_hint="GBP",
    )
    return _ParsedRowCandidate(
        row=row,
        amount_absolute=abs(amount),
        running_balance=running_balance,
        marker_source=marker_source,
    )


def _contains_amount(line: str) -> bool:
    return _AMOUNT_TOKEN_PATTERN.search(line) is not None


def _is_non_transaction_line(line: str) -> bool:
    upper = line.upper()
    compact = upper.replace(" ", "")
    if any(marker in compact for marker in _NON_TXN_BALANCE_MARKERS):
        return True
    if any(upper.startswith(prefix) for prefix in _NOISE_PREFIXES):
        return True
    if any(marker in upper for marker in _NOISE_SUBSTRINGS):
        return True
    return False


def _select_transaction_match(line: str, matches: list[re.Match[str]]) -> re.Match[str] | None:
    if _is_non_transaction_line(line):
        return None
    if len(matches) == 1:
        return matches[0]
    # Most HSBC rows end with running balance; transaction amount is penultimate token.
    return matches[-2]


def _starts_with_transaction_prefix(line: str) -> bool:
    upper = line.strip().upper()
    return any(upper.startswith(prefix) for prefix in _TXN_PREFIXES)


def _has_transaction_context(line: str) -> bool:
    upper = line.strip().upper()
    if _is_non_transaction_context_line(upper):
        return False
    if _starts_with_transaction_prefix(upper):
        return True
    return any(hint in upper for hint in _TXN_CONTEXT_HINTS)


def _is_non_transaction_context_line(line: str) -> bool:
    upper = line.strip().upper()
    return any(marker in upper for marker in _NOISE_SUBSTRINGS)


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


def _dedupe_description(description: str) -> str:
    normalized = " ".join(description.upper().split())
    normalized = normalized.removesuffix(" CR_MARKER")
    normalized = normalized.removesuffix(" DR_MARKER")
    return normalized


def _append_or_merge_duplicate_candidate(
    existing: list[_ParsedRowCandidate],
    candidate: _ParsedRowCandidate,
) -> list[_ParsedRowCandidate]:
    if not existing:
        return [candidate]

    last = existing[-1]
    same_key = (
        candidate.row.raw_date == last.row.raw_date
        and candidate.row.raw_amount == last.row.raw_amount
        and _dedupe_description(candidate.row.raw_description)
        == _dedupe_description(last.row.raw_description)
    )
    if not same_key:
        return [*existing, candidate]

    if last.running_balance is None and candidate.running_balance is not None:
        return [*existing[:-1], candidate]
    if last.running_balance is not None and candidate.running_balance is None:
        return existing
    if last.running_balance is None and candidate.running_balance is None:
        return [*existing, candidate]
    if last.running_balance == candidate.running_balance:
        return existing
    return [*existing, candidate]


def _apply_running_balance_sign_override(
    candidate: _ParsedRowCandidate,
    previous_running_balance: Decimal | None,
) -> tuple[_ParsedRowCandidate, Decimal | None]:
    if candidate.running_balance is None or previous_running_balance is None:
        return candidate, previous_running_balance
    if candidate.marker_source is not None:
        return candidate, previous_running_balance

    delta = candidate.running_balance - previous_running_balance
    if delta == 0:
        return candidate, previous_running_balance
    if abs(abs(delta) - candidate.amount_absolute) > Decimal("0.02"):
        return candidate, previous_running_balance

    inferred_marker = "CR_MARKER" if delta > 0 else "DR_MARKER"
    description_without_markers = _dedupe_description(candidate.row.raw_description)
    updated_description = f"{description_without_markers} {inferred_marker}"
    updated_row = replace(candidate.row, raw_description=updated_description)
    return replace(candidate, row=updated_row), previous_running_balance

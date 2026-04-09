"""HSBC UK statement parser."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from finance_tooling.core.models import Transaction
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
_POSITIVE_HINTS = ("PAYMENT IN", "TRANSFER FROM", "INTEREST", "REFUND")
_NEGATIVE_HINTS = ()
_POSITIVE_MARKERS = ()
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
_FX_CURRENCY_CODE_PATTERN = re.compile(
    r"\b(?:EUR|USD|RUB|CHF|CAD|AUD|JPY|NOK|SEK|DKK|PLN)\b",
    re.IGNORECASE,
)
_NON_STERLING_MARKER_PATTERN = re.compile(r"\b(?P<marker>CR|DR)\s+NON-STERLING\b", re.IGNORECASE)
_TXN_PREFIX_PATTERN = re.compile(r"(?:(?:^(?:VIS|DD|ATM|BP|SO|CR|DR)(?:\b|$))|(?:^\)\)\)(?:\s|$)))")
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
_HARD_TABLE_END_MARKERS = (
    "BALANCECARRIEDFORWARD",
    "CLOSINGBALANCE",
    "NEWBALANCE",
)
_TABLE_HEADER_MARKERS = (
    "DATE PAYMENT TYPE",
    "DATE DESCRIPTION",
)
_BOUNDARY_STATE_OUTSIDE = "OUTSIDE_TABLE"
_BOUNDARY_STATE_IN = "IN_TABLE"
_BOUNDARY_STATE_AFTER = "AFTER_TABLE"
_ATM_CASH_PREFIXES = ("ATM CASH", "DR CASH")


@dataclass(frozen=True)
class _ParsedBlock:
    raw_date: str
    header_text: str
    header_raw_text: str
    continuation_lines: list[str]
    continuation_raw_lines: list[str]
    column_anchors: _ColumnAnchors | None


@dataclass(frozen=True)
class _ColumnAnchors:
    paid_out_start: int
    paid_in_start: int
    balance_start: int


@dataclass(frozen=True)
class _ParsedRowCandidate:
    row: ParsedRow
    amount_absolute: Decimal
    signed_amount: Decimal
    running_balance: Decimal | None
    sign_source: str
    running_vs_marker_conflict: bool = False


@dataclass
class _BoundaryStats:
    table_start_count: int = 0
    table_end_count: int = 0
    rows_seen_in_table: int = 0
    rows_rejected_outside_table: int = 0
    rows_rejected_after_table: int = 0
    transition_anomaly_count: int = 0

    def as_diagnostics(self) -> dict[str, object]:
        return {
            "table_start_count": self.table_start_count,
            "table_end_count": self.table_end_count,
            "rows_seen_in_table": self.rows_seen_in_table,
            "rows_rejected_outside_table": self.rows_rejected_outside_table,
            "rows_rejected_after_table": self.rows_rejected_after_table,
            "transition_anomaly_count": self.transition_anomaly_count,
        }


@dataclass
class _SignStats:
    sign_from_running_balance_count: int = 0
    sign_from_column_position_count: int = 0
    sign_from_token_marker_count: int = 0
    sign_from_description_marker_count: int = 0
    sign_from_fallback_hint_count: int = 0
    sign_default_debit_count: int = 0
    sign_conflict_running_vs_marker_count: int = 0
    sign_unresolved_ambiguous_count: int = 0

    def add_source(self, source: str) -> None:
        if source == "running_balance":
            self.sign_from_running_balance_count += 1
            return
        if source == "column_position":
            self.sign_from_column_position_count += 1
            return
        if source == "token_marker":
            self.sign_from_token_marker_count += 1
            return
        if source == "description_marker":
            self.sign_from_description_marker_count += 1
            return
        if source == "fallback_hint":
            self.sign_from_fallback_hint_count += 1
            return
        if source == "default_debit":
            self.sign_default_debit_count += 1
            return
        self.sign_unresolved_ambiguous_count += 1

    def as_diagnostics(self) -> dict[str, object]:
        return {
            "sign_from_running_balance_count": self.sign_from_running_balance_count,
            "sign_from_column_position_count": self.sign_from_column_position_count,
            "sign_from_token_marker_count": self.sign_from_token_marker_count,
            "sign_from_description_marker_count": self.sign_from_description_marker_count,
            "sign_from_fallback_hint_count": self.sign_from_fallback_hint_count,
            "sign_default_debit_count": self.sign_default_debit_count,
            "sign_conflict_running_vs_marker_count": self.sign_conflict_running_vs_marker_count,
            "sign_unresolved_ambiguous_count": self.sign_unresolved_ambiguous_count,
        }


class HsbcParser(BaseStatementParser):
    """Parser for HSBC statement transaction rows."""

    name = "hsbc"
    bank = "HSBC"

    def _filename_markers(self) -> tuple[str, ...]:
        return ("hsbc",)

    def _content_markers(self) -> tuple[str, ...]:
        return ("hsbc", "your statement")

    def _extract_rows(
        self, file_path: Path, full_text: str
    ) -> tuple[list[ParsedRow], list[str], dict[str, object] | None]:
        rows: list[ParsedRow] = []
        warnings: list[str] = []
        blocks: list[_ParsedBlock] = []
        boundary = _BoundaryStats()
        sign_stats = _SignStats()
        previous_running_balance: Decimal | None = None
        current_date: str | None = None
        current_header: str = ""
        current_header_raw: str = ""
        current_continuations: list[str] = []
        current_continuations_raw: list[str] = []
        current_column_anchors: _ColumnAnchors | None = None

        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            maybe_column_anchors = _extract_column_anchors(raw_line)
            if maybe_column_anchors is not None:
                current_column_anchors = maybe_column_anchors

            match = _DATE_PREFIX_PATTERN.match(line)
            if match is not None:
                if current_date is not None:
                    blocks.append(
                        _ParsedBlock(
                            raw_date=current_date,
                            header_text=current_header,
                            header_raw_text=current_header_raw,
                            continuation_lines=current_continuations,
                            continuation_raw_lines=current_continuations_raw,
                            column_anchors=current_column_anchors,
                        )
                    )
                current_date = match.group("date")
                current_header = match.group("rest")
                current_header_raw = raw_line
                current_continuations = []
                current_continuations_raw = []
                continue

            if current_date is not None:
                current_continuations.append(line)
                current_continuations_raw.append(raw_line)

        if current_date is not None:
            blocks.append(
                _ParsedBlock(
                    raw_date=current_date,
                    header_text=current_header,
                    header_raw_text=current_header_raw,
                    continuation_lines=current_continuations,
                    continuation_raw_lines=current_continuations_raw,
                    column_anchors=current_column_anchors,
                )
            )
        state = _BOUNDARY_STATE_OUTSIDE
        saw_table_header = False
        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split()).upper()
            if not line:
                continue
            if any(line.startswith(marker) for marker in _TABLE_HEADER_MARKERS):
                saw_table_header = True

        for block in blocks:
            if _is_hard_table_end_line(block.header_text):
                if state != _BOUNDARY_STATE_IN:
                    if boundary.table_start_count > 0:
                        boundary.transition_anomaly_count += 1
                else:
                    boundary.table_end_count += 1
                    state = _BOUNDARY_STATE_AFTER
                continue

            parsed_rows, block_sign_stats, block_last_running_balance = _rows_from_block(
                block,
                previous_running_balance=previous_running_balance,
            )
            sign_stats.sign_from_running_balance_count += (
                block_sign_stats.sign_from_running_balance_count
            )
            sign_stats.sign_from_column_position_count += (
                block_sign_stats.sign_from_column_position_count
            )
            sign_stats.sign_from_token_marker_count += block_sign_stats.sign_from_token_marker_count
            sign_stats.sign_from_description_marker_count += (
                block_sign_stats.sign_from_description_marker_count
            )
            sign_stats.sign_from_fallback_hint_count += (
                block_sign_stats.sign_from_fallback_hint_count
            )
            sign_stats.sign_default_debit_count += block_sign_stats.sign_default_debit_count
            sign_stats.sign_conflict_running_vs_marker_count += (
                block_sign_stats.sign_conflict_running_vs_marker_count
            )
            sign_stats.sign_unresolved_ambiguous_count += (
                block_sign_stats.sign_unresolved_ambiguous_count
            )
            parsed_count = len(parsed_rows)

            if state == _BOUNDARY_STATE_OUTSIDE:
                if _is_confident_table_start(
                    block,
                    parsed_count,
                    saw_table_header=saw_table_header,
                ):
                    state = _BOUNDARY_STATE_IN
                    boundary.table_start_count += 1
                else:
                    boundary.rows_rejected_outside_table += parsed_count
                    continue

            if state == _BOUNDARY_STATE_AFTER:
                boundary.rows_rejected_after_table += parsed_count
                continue

            rows.extend(parsed_rows)
            boundary.rows_seen_in_table += parsed_count
            previous_running_balance = block_last_running_balance

        if boundary.transition_anomaly_count > 0:
            warnings.append(
                f"{file_path.name}: HSBC boundary state anomalies detected "
                f"({boundary.transition_anomaly_count}) while extracting rows"
            )

        return (
            rows,
            warnings,
            {
                "hsbc_boundary": boundary.as_diagnostics(),
                "hsbc_sign": sign_stats.as_diagnostics(),
            },
        )

    def _normalize_config(self) -> NormalizeConfig:
        return NormalizeConfig(
            sign_mode="explicit_sign",
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


def _rows_from_block(
    block: _ParsedBlock,
    *,
    previous_running_balance: Decimal | None,
) -> tuple[list[ParsedRow], _SignStats, Decimal | None]:
    rows: list[_ParsedRowCandidate] = []
    sign_stats = _SignStats()
    pending_context_parts: list[str] = []
    pending_has_txn_prefix = False
    pending_sign_marker: str | None = None

    header_row = _parse_statement_row_candidate(
        block.raw_date,
        block.header_text,
        raw_rest=block.header_raw_text,
        column_anchors=block.column_anchors,
    )
    if header_row is not None:
        header_row, previous_running_balance = _apply_running_balance_sign_override(
            header_row,
            previous_running_balance,
        )
        sign_stats.add_source(header_row.sign_source)
        if header_row.running_vs_marker_conflict:
            sign_stats.sign_conflict_running_vs_marker_count += 1
        rows = _append_or_merge_duplicate_candidate(rows, header_row)
        if header_row.running_balance is not None:
            previous_running_balance = header_row.running_balance
    elif not _is_non_transaction_line(block.header_text):
        pending_context_parts = [block.header_text]
        pending_has_txn_prefix = _has_transaction_context(block.header_text)
        pending_sign_marker = _description_sign_marker(block.header_text)

    index = 0
    while index < len(block.continuation_lines):
        line = block.continuation_lines[index]
        raw_line = block.continuation_raw_lines[index]
        if _is_non_transaction_line(line):
            pending_context_parts = []
            pending_has_txn_prefix = False
            pending_sign_marker = None
            index += 1
            continue

        if _is_non_transaction_context_line(line):
            pending_context_parts = []
            pending_has_txn_prefix = False
            pending_sign_marker = None
            index += 1
            continue

        if not _contains_amount(line):
            pending_context_parts.append(line)
            if _has_transaction_context(line):
                pending_has_txn_prefix = True
                pending_sign_marker = _description_sign_marker(line)
            index += 1
            continue

        fallback_context = " ".join(part for part in pending_context_parts if part).strip()
        if _should_defer_atm_charge_fragment(
            fallback_context=fallback_context,
            line=line,
            continuation_lines=block.continuation_lines,
            current_index=index,
        ):
            index += 1
            continue

        parsed_fx = _parse_fx_rows_from_context(
            raw_date=block.raw_date,
            fallback_context=fallback_context,
            continuation_lines=block.continuation_lines,
            continuation_raw_lines=block.continuation_raw_lines,
            start_index=index,
            column_anchors=block.column_anchors,
        )
        if parsed_fx is not None:
            fx_rows, next_index = parsed_fx
            for fx_row in fx_rows:
                fx_row, previous_running_balance = _apply_running_balance_sign_override(
                    fx_row,
                    previous_running_balance,
                )
                sign_stats.add_source(fx_row.sign_source)
                if fx_row.running_vs_marker_conflict:
                    sign_stats.sign_conflict_running_vs_marker_count += 1
                rows = _append_or_merge_duplicate_candidate(rows, fx_row)
                if fx_row.running_balance is not None:
                    previous_running_balance = fx_row.running_balance
            pending_context_parts = []
            pending_has_txn_prefix = False
            pending_sign_marker = None
            index = next_index
            continue

        line_is_txn = _starts_with_transaction_prefix(line)
        if not line_is_txn and not pending_has_txn_prefix:
            pending_context_parts = []
            pending_has_txn_prefix = False
            pending_sign_marker = None
            index += 1
            continue

        row = _parse_statement_row_candidate(
            block.raw_date,
            line,
            fallback_context=fallback_context if fallback_context else None,
            inherited_sign_marker=pending_sign_marker if not line_is_txn else None,
            raw_rest=raw_line,
            column_anchors=block.column_anchors,
        )
        if row is not None:
            row, previous_running_balance = _apply_running_balance_sign_override(
                row,
                previous_running_balance,
            )
            sign_stats.add_source(row.sign_source)
            if row.running_vs_marker_conflict:
                sign_stats.sign_conflict_running_vs_marker_count += 1
            rows = _append_or_merge_duplicate_candidate(rows, row)
            if row.running_balance is not None:
                previous_running_balance = row.running_balance
        pending_context_parts = []
        pending_has_txn_prefix = False
        pending_sign_marker = None
        index += 1

    return [candidate.row for candidate in rows], sign_stats, previous_running_balance


def _parse_statement_row_candidate(
    raw_date: str,
    rest: str,
    *,
    fallback_context: str | None = None,
    inherited_sign_marker: str | None = None,
    raw_rest: str | None = None,
    column_anchors: _ColumnAnchors | None = None,
) -> _ParsedRowCandidate | None:
    if _is_non_transaction_line(rest):
        return None

    matches = list(_AMOUNT_TOKEN_PATTERN.finditer(rest))
    if not matches:
        return None
    candidate_matches = _candidate_transaction_matches(rest, matches)
    selected = _select_transaction_match(rest, candidate_matches)
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
    sign_source = "default_debit"
    if token_marker is not None:
        sign_source = "token_marker"
    elif description_marker is not None:
        sign_source = "description_marker"
    elif inherited_sign_marker is not None:
        sign_source = "description_marker"
    amount = _parse_amount_token(transaction_token)
    if amount is None:
        return None
    amount_absolute = abs(amount)
    running_balance: Decimal | None = None
    if len(candidate_matches) > 1:
        running_balance = _parse_amount_token(candidate_matches[-1].group("amount"))
    column_sign_marker = _infer_column_sign_marker(
        normalized_rest=rest,
        raw_rest=raw_rest,
        selected_match=selected,
        all_matches=matches,
        column_anchors=column_anchors,
        indicator_marker=indicator_marker,
    )
    signed_amount, fallback_sign_source = _signed_amount_from_source(
        amount_absolute=amount_absolute,
        description=description,
        indicator_marker=indicator_marker,
        column_sign_marker=column_sign_marker,
    )
    if sign_source == "default_debit":
        sign_source = fallback_sign_source
    if indicator_marker is not None:
        description = f"{description} {indicator_marker}"
    row = ParsedRow(
        raw_date=_normalize_compact_date(raw_date),
        raw_description=description,
        raw_amount=str(signed_amount),
        raw_currency_hint="GBP",
    )
    return _ParsedRowCandidate(
        row=row,
        amount_absolute=amount_absolute,
        signed_amount=signed_amount,
        running_balance=running_balance,
        sign_source=sign_source,
    )


def _parse_fx_rows_from_context(
    *,
    raw_date: str,
    fallback_context: str,
    continuation_lines: list[str],
    continuation_raw_lines: list[str],
    start_index: int,
    column_anchors: _ColumnAnchors | None,
) -> tuple[list[_ParsedRowCandidate], int] | None:
    if not fallback_context:
        return None
    if not _looks_like_fx_context(fallback_context):
        return None

    end_index = start_index + 1
    while end_index < len(continuation_lines):
        if _starts_with_transaction_prefix(continuation_lines[end_index]) and (
            _NON_STERLING_MARKER_PATTERN.search(continuation_lines[end_index]) is None
        ):
            break
        end_index += 1

    cluster_lines = continuation_lines[start_index:end_index]
    cluster_raw_lines = continuation_raw_lines[start_index:end_index]
    if not any(_looks_like_fx_cluster_detail_line(line) for line in cluster_lines):
        return None
    marker = _non_sterling_marker_from_lines(cluster_lines)
    visa_rate_amount = _extract_visa_rate_amount(cluster_lines)
    if visa_rate_amount is None:
        return None

    sign_marker = marker or _description_sign_marker(fallback_context)
    if sign_marker == "CR_MARKER":
        signed_amount = visa_rate_amount
        sign_source = "description_marker"
    elif sign_marker == "DR_MARKER":
        signed_amount = -visa_rate_amount
        sign_source = "description_marker"
    else:
        signed_amount = -visa_rate_amount
        sign_source = "default_debit"

    description = fallback_context
    if sign_marker is not None and not description.endswith(sign_marker):
        description = f"{description} {sign_marker}"

    candidates = [
        _ParsedRowCandidate(
            row=ParsedRow(
                raw_date=_normalize_compact_date(raw_date),
                raw_description=description,
                raw_amount=str(signed_amount),
                raw_currency_hint="GBP",
            ),
            amount_absolute=visa_rate_amount,
            signed_amount=signed_amount,
            running_balance=None,
            sign_source=sign_source,
        )
    ]

    for offset, cluster_line in enumerate(cluster_lines):
        cluster_upper = cluster_line.upper()
        compact_cluster_upper = cluster_upper.replace(" ", "")
        if "TRANSACTION FEE" not in cluster_upper and "TRANSACTIONFEE" not in compact_cluster_upper:
            continue
        fee_row = _parse_statement_row_candidate(
            raw_date,
            cluster_line,
            inherited_sign_marker=sign_marker,
            raw_rest=cluster_raw_lines[offset],
            column_anchors=column_anchors,
        )
        if fee_row is not None:
            candidates.append(fee_row)
        break

    return candidates, end_index


def _looks_like_fx_context(context: str) -> bool:
    upper = context.upper().strip()
    if not _starts_with_transaction_prefix(upper):
        return False
    if "INT'L" in upper:
        return True
    return upper.startswith("VIS CASH")


def _looks_like_fx_cluster_detail_line(line: str) -> bool:
    upper = line.upper()
    compact_upper = upper.replace(" ", "")
    if "VISA RATE" in upper or "VISARATE" in compact_upper:
        return True
    if "NON-STERLING" in upper or "NONSTERLING" in compact_upper:
        return True
    if "TRANSACTION FEE" in upper or "TRANSACTIONFEE" in compact_upper:
        return True
    if _FX_CURRENCY_CODE_PATTERN.search(upper) is not None and _contains_amount(line):
        return True
    return False


def _non_sterling_marker_from_lines(lines: list[str]) -> str | None:
    for line in lines:
        match = _NON_STERLING_MARKER_PATTERN.search(line)
        if match is None:
            continue
        marker = match.group("marker").upper()
        if marker == "CR":
            return "CR_MARKER"
        if marker == "DR":
            return "DR_MARKER"
    return None


def _extract_visa_rate_amount(lines: list[str]) -> Decimal | None:
    for line in lines:
        upper = line.upper()
        compact_upper = upper.replace(" ", "")
        visa_rate_index = upper.find("VISA RATE")
        if visa_rate_index < 0:
            compact_index = compact_upper.find("VISARATE")
            if compact_index >= 0:
                # Map compact string index back to the original line index.
                no_space_idx = 0
                for idx, ch in enumerate(upper):
                    if ch == " ":
                        continue
                    if no_space_idx == compact_index:
                        visa_rate_index = idx
                        break
                    no_space_idx += 1
        if visa_rate_index < 0:
            continue
        matches = list(_AMOUNT_TOKEN_PATTERN.finditer(line))
        if not matches:
            continue
        trailing = [match for match in matches if match.start() >= visa_rate_index]
        ordered = trailing if trailing else matches
        for match in reversed(ordered):
            parsed = _parse_amount_token(match.group("amount"))
            if parsed is None:
                continue
            return abs(parsed)
    return None


def _contains_amount(line: str) -> bool:
    return _AMOUNT_TOKEN_PATTERN.search(line) is not None


def _is_hard_table_end_line(line: str) -> bool:
    upper = line.upper()
    compact = upper.replace(" ", "")
    if any(marker in compact for marker in _HARD_TABLE_END_MARKERS):
        return True
    return upper.startswith("ACCOUNT SUMMARY")


def _is_confident_table_start(
    block: _ParsedBlock,
    parsed_row_count: int,
    *,
    saw_table_header: bool,
) -> bool:
    if parsed_row_count == 0:
        return False
    if _is_hard_table_end_line(block.header_text):
        return False
    if _starts_with_transaction_prefix(block.header_text):
        return True
    if _has_transaction_context(block.header_text):
        return True
    if "SALARY" in block.header_text.upper():
        return True
    amount_count = len(list(_AMOUNT_TOKEN_PATTERN.finditer(block.header_text)))
    if amount_count >= 2:
        return True
    # Require a stronger signal when no explicit table header was seen.
    return saw_table_header


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


def _should_defer_atm_charge_fragment(
    *,
    fallback_context: str,
    line: str,
    continuation_lines: list[str],
    current_index: int,
) -> bool:
    if not _looks_like_atm_cash_context(fallback_context):
        return False
    if "BNKM CHG" not in line.upper():
        return False
    if len(list(_AMOUNT_TOKEN_PATTERN.finditer(line))) != 1:
        return False
    next_index = current_index + 1
    if next_index >= len(continuation_lines):
        return False
    next_line = continuation_lines[next_index]
    if _starts_with_transaction_prefix(next_line):
        return False
    return len(list(_AMOUNT_TOKEN_PATTERN.finditer(next_line))) >= 2


def _looks_like_atm_cash_context(context: str) -> bool:
    upper = context.upper().strip()
    return upper.startswith(_ATM_CASH_PREFIXES)


def _candidate_transaction_matches(
    line: str,
    matches: list[re.Match[str]],
) -> list[re.Match[str]]:
    candidates = [match for match in matches if not _is_embedded_amount_match(line, match)]
    return candidates if candidates else matches


def _is_embedded_amount_match(line: str, match: re.Match[str]) -> bool:
    start = match.start()
    end = match.end()
    if start > 0 and line[start - 1].isalnum():
        return True
    if end < len(line) and line[end].isalnum():
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
    return _TXN_PREFIX_PATTERN.match(upper) is not None


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

    # Only collapse rows when both carry the same running balance.
    # This avoids dropping legitimate repeated transactions where only one
    # line includes a balance token near page/table boundaries.
    if (
        last.running_balance is not None
        and candidate.running_balance is not None
        and last.running_balance == candidate.running_balance
    ):
        return existing
    return [*existing, candidate]


def _apply_running_balance_sign_override(
    candidate: _ParsedRowCandidate,
    previous_running_balance: Decimal | None,
) -> tuple[_ParsedRowCandidate, Decimal | None]:
    if candidate.running_balance is None or previous_running_balance is None:
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
    inferred_signed_amount = candidate.amount_absolute if delta > 0 else -candidate.amount_absolute
    marker_based_signed_amount = _signed_amount_from_description_marker(
        candidate.row.raw_description,
        amount_absolute=candidate.amount_absolute,
    )
    running_vs_marker_conflict = (
        marker_based_signed_amount is not None
        and marker_based_signed_amount != inferred_signed_amount
    )
    return (
        replace(
            candidate,
            row=replace(updated_row, raw_amount=str(inferred_signed_amount)),
            signed_amount=inferred_signed_amount,
            sign_source="running_balance",
            running_vs_marker_conflict=running_vs_marker_conflict,
        ),
        previous_running_balance,
    )


def _signed_amount_from_source(
    *,
    amount_absolute: Decimal,
    description: str,
    indicator_marker: str | None,
    column_sign_marker: str | None,
) -> tuple[Decimal, str]:
    if column_sign_marker == "CR_MARKER":
        return amount_absolute, "column_position"
    if column_sign_marker == "DR_MARKER":
        return -amount_absolute, "column_position"
    if indicator_marker == "CR_MARKER":
        return amount_absolute, "description_marker"
    if indicator_marker == "DR_MARKER":
        return -amount_absolute, "description_marker"
    description_upper = description.upper()
    if description_upper.startswith("BP ") and "SALARY" in description_upper:
        return amount_absolute, "fallback_hint"
    if any(hint in description_upper for hint in _POSITIVE_HINTS):
        return amount_absolute, "fallback_hint"
    return -amount_absolute, "default_debit"


def _signed_amount_from_description_marker(
    description: str,
    *,
    amount_absolute: Decimal,
) -> Decimal | None:
    if description.endswith(" CR_MARKER"):
        return amount_absolute
    if description.endswith(" DR_MARKER"):
        return -amount_absolute
    return None


def _extract_column_anchors(raw_line: str) -> _ColumnAnchors | None:
    upper = raw_line.upper()
    paid_out_start = upper.find("PAIDOUT")
    paid_in_start = upper.find("PAIDIN")
    balance_start = upper.find("BALANCE")
    if paid_out_start < 0 or paid_in_start < 0 or balance_start < 0:
        return None
    if not (paid_out_start < paid_in_start < balance_start):
        return None
    return _ColumnAnchors(
        paid_out_start=paid_out_start,
        paid_in_start=paid_in_start,
        balance_start=balance_start,
    )


def _infer_column_sign_marker(
    *,
    normalized_rest: str,
    raw_rest: str | None,
    selected_match: re.Match[str],
    all_matches: list[re.Match[str]],
    column_anchors: _ColumnAnchors | None,
    indicator_marker: str | None = None,
) -> str | None:
    if raw_rest is None or column_anchors is None:
        return None
    raw_matches = list(_AMOUNT_TOKEN_PATTERN.finditer(raw_rest))
    if not raw_matches:
        return None
    selected_index = 0
    for idx, match in enumerate(all_matches):
        if match.start() == selected_match.start() and match.end() == selected_match.end():
            selected_index = idx
            break
    if selected_index >= len(raw_matches):
        return None
    raw_selected = raw_matches[selected_index]
    token_start = raw_selected.start()
    token_end = raw_selected.end()
    token_center = token_start + ((token_end - token_start - 1) / 2.0)

    # OCR/text extraction can shift token starts by one character. Use token
    # center for column classification and guard the paid-out/paid-in boundary.
    if abs(token_center - column_anchors.paid_in_start) <= 1.0 and indicator_marker in {
        "CR_MARKER",
        "DR_MARKER",
    }:
        return indicator_marker

    if token_center >= column_anchors.paid_in_start and token_center < column_anchors.balance_start:
        return "CR_MARKER"
    if (
        token_center >= column_anchors.paid_out_start
        and token_center < column_anchors.paid_in_start
    ):
        return "DR_MARKER"
    del normalized_rest
    return None

"""Carry forward prior manual categories when parser descriptions drift."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from finance_tooling.categorization.classify import normalize_description
from finance_tooling.core.models import Transaction

_MANUAL_SOURCES = {"transaction_override"}
_BLOCKED_CURRENT_SOURCES = _MANUAL_SOURCES
_REQUIRED_COLUMNS = (
    "booking_date",
    "amount_native",
    "currency",
    "bank",
    "account_label",
    "source_file",
    "parser",
    "description",
    "category",
    "subcategory",
    "category_source",
)


@dataclass(frozen=True)
class CarryForwardDiagnostics:
    """Summary counters for category carry-forward matching."""

    applied_count: int = 0
    ambiguous_skipped_count: int = 0
    unmatched_count: int = 0


@dataclass(frozen=True)
class CarryForwardResult:
    """Output payload for category carry-forward stage."""

    transactions: list[Transaction]
    diagnostics: CarryForwardDiagnostics
    warnings: list[str]


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def _is_distinctive_prefix(text: str) -> bool:
    tokens = [token for token in text.split() if token]
    return len(tokens) >= 4 or len(text) >= 20


def _to_amount_key(value: object) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return text
    return format(amount.quantize(Decimal("0.01")), "f")


def _row_key(row: dict[str, object]) -> tuple[str, str, str, str, str, str, str]:
    return (
        _normalize_text(row.get("booking_date")),
        _to_amount_key(row.get("amount_native")),
        _normalize_text(row.get("currency")).upper(),
        _normalize_text(row.get("bank")).upper(),
        _normalize_text(row.get("account_label")).upper(),
        _normalize_text(row.get("source_file")),
        _normalize_text(row.get("parser")).lower(),
    )


def _transaction_key(transaction: Transaction) -> tuple[str, str, str, str, str, str, str]:
    return (
        transaction.booking_date.isoformat(),
        _to_amount_key(transaction.amount_native),
        transaction.currency.upper(),
        transaction.bank.strip().upper(),
        (transaction.account_label or "").strip().upper(),
        str(transaction.source_file),
        transaction.parser.strip().lower(),
    )


def _is_carry_candidate(row: dict[str, object]) -> bool:
    source = _normalize_text(row.get("category_source")).lower()
    if source not in _MANUAL_SOURCES:
        return False
    category = _normalize_text(row.get("category"))
    return bool(category) and category.lower() != "uncategorized"


def _pick_candidate(
    transaction: Transaction,
    candidates: list[dict[str, object]],
) -> tuple[dict[str, object] | None, bool]:
    normalized_tx = normalize_description(transaction.description)
    if not normalized_tx:
        return None, False

    exact = [
        candidate
        for candidate in candidates
        if normalize_description(_normalize_text(candidate.get("description"))) == normalized_tx
    ]
    if len(exact) == 1:
        return exact[0], False
    if len(exact) > 1:
        return None, True

    prefix = []
    for candidate in candidates:
        normalized_existing = normalize_description(_normalize_text(candidate.get("description")))
        if not normalized_existing:
            continue
        shorter = (
            normalized_existing
            if len(normalized_existing) <= len(normalized_tx)
            else normalized_tx
        )
        if not _is_distinctive_prefix(shorter):
            continue
        if (
            normalized_existing.startswith(normalized_tx)
            or normalized_tx.startswith(normalized_existing)
        ):
            prefix.append(candidate)
    if len(prefix) == 1:
        return prefix[0], False
    if len(prefix) > 1:
        return None, True
    return None, False


def apply_manual_category_carry_forward(
    transactions: list[Transaction],
    *,
    master_parquet_path: Path,
) -> CarryForwardResult:
    """Carry forward manual category/subcategory from existing canonical output."""
    if not transactions:
        return CarryForwardResult(
            transactions=[], diagnostics=CarryForwardDiagnostics(), warnings=[]
        )
    if not master_parquet_path.exists():
        return CarryForwardResult(
            transactions=list(transactions),
            diagnostics=CarryForwardDiagnostics(unmatched_count=len(transactions)),
            warnings=[],
        )

    try:
        existing = pd.read_parquet(master_parquet_path)
    except Exception as exc:
        return CarryForwardResult(
            transactions=list(transactions),
            diagnostics=CarryForwardDiagnostics(unmatched_count=len(transactions)),
            warnings=[
                "Manual category carry-forward skipped: failed to read "
                f"{master_parquet_path}: {exc}"
            ],
        )

    missing_columns = [column for column in _REQUIRED_COLUMNS if column not in existing.columns]
    if missing_columns:
        joined = ", ".join(sorted(missing_columns))
        return CarryForwardResult(
            transactions=list(transactions),
            diagnostics=CarryForwardDiagnostics(unmatched_count=len(transactions)),
            warnings=[
                "Manual category carry-forward skipped: "
                f"{master_parquet_path} missing columns: {joined}"
            ],
        )

    by_key: dict[tuple[str, str, str, str, str, str, str], list[dict[str, object]]] = {}
    for row in existing.to_dict(orient="records"):
        if not _is_carry_candidate(row):
            continue
        key = _row_key(row)
        by_key.setdefault(key, []).append(row)

    carried: list[Transaction] = []
    applied_count = 0
    ambiguous_count = 0
    unmatched_count = 0

    for transaction in transactions:
        source = (transaction.category_source or "").strip().lower()
        if source in _BLOCKED_CURRENT_SOURCES:
            carried.append(transaction)
            continue

        key = _transaction_key(transaction)
        candidates = by_key.get(key, [])
        if not candidates:
            carried.append(transaction)
            unmatched_count += 1
            continue

        selected, ambiguous = _pick_candidate(transaction, candidates)
        if ambiguous:
            carried.append(transaction)
            ambiguous_count += 1
            continue
        if selected is None:
            carried.append(transaction)
            unmatched_count += 1
            continue

        carried.append(
            replace(
                transaction,
                category=_normalize_text(selected.get("category")),
                subcategory=_normalize_text(selected.get("subcategory")) or None,
                category_confidence=1.0,
                category_source="transaction_override",
                category_rule_id=None,
            )
        )
        applied_count += 1

    warnings: list[str] = []
    if ambiguous_count > 0:
        warnings.append(
            "Manual category carry-forward skipped ambiguous matches for "
            f"{ambiguous_count} transaction(s)."
        )

    return CarryForwardResult(
        transactions=carried,
        diagnostics=CarryForwardDiagnostics(
            applied_count=applied_count,
            ambiguous_skipped_count=ambiguous_count,
            unmatched_count=unmatched_count,
        ),
        warnings=warnings,
    )

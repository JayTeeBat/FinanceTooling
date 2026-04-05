"""Typed canonical transaction schema and dataframe adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import pandas as pd

CANONICAL_TRANSACTION_COLUMNS = (
    "transaction_id",
    "booking_date",
    "description",
    "source_record_index",
    "amount_native",
    "currency",
    "fx_rate_to_eur",
    "fx_rate_date",
    "fx_source",
    "amount_eur",
    "category",
    "subcategory",
    "category_confidence",
    "category_source",
    "category_rule_id",
    "cashflow_type",
    "from_account_ref",
    "to_account_ref",
    "from_account_type",
    "to_account_type",
    "account_inference_source",
    "project",
    "project_tags",
    "project_source",
    "reviewed",
    "bank",
    "account_label",
    "source_document_id",
    "source_file",
    "source_file_mtime",
    "parser",
    "ingested_at",
)


class SupportsCanonicalization(Protocol):
    """Minimal interface needed to canonicalize an enriched transaction."""

    booking_date: date
    description: str
    source_record_index: int | None
    amount_native: Decimal
    currency: str
    fx_rate_to_eur: Decimal | None
    fx_rate_date: date | None
    fx_source: str | None
    amount_eur: Decimal | None
    category: str
    subcategory: str | None
    category_confidence: float | None
    category_source: str | None
    category_rule_id: str | None
    cashflow_type: str | None
    from_account_ref: str | None
    to_account_ref: str | None
    from_account_type: str | None
    to_account_type: str | None
    account_inference_source: str | None
    project: str | None
    project_tags: tuple[str, ...]
    project_source: str | None
    reviewed: bool
    bank: str
    account_label: str | None
    source_document_id: str | None
    source_file: Path
    source_file_mtime: datetime | None
    parser: str


@dataclass(frozen=True)
class CanonicalTransaction:
    """One canonical persisted transaction row."""

    transaction_id: str
    booking_date: date
    description: str
    source_record_index: int | None
    amount_native: Decimal
    currency: str
    fx_rate_to_eur: Decimal | None
    fx_rate_date: date | None
    fx_source: str | None
    amount_eur: Decimal | None
    category: str
    subcategory: str | None
    category_confidence: float | None
    category_source: str | None
    category_rule_id: str | None
    cashflow_type: str | None
    from_account_ref: str | None
    to_account_ref: str | None
    from_account_type: str | None
    to_account_type: str | None
    account_inference_source: str | None
    project: str | None
    project_tags: tuple[str, ...]
    project_source: str | None
    reviewed: bool
    bank: str
    account_label: str | None
    source_document_id: str | None
    source_file: Path
    source_file_mtime: datetime | None
    parser: str
    ingested_at: datetime | None


def _is_missing(value: object) -> bool:
    return value is None or bool(pd.isna(value))


def _optional_str(value: object) -> str | None:
    if _is_missing(value):
        return None
    return str(value)


def _optional_decimal(value: object) -> Decimal | None:
    if _is_missing(value):
        return None
    return Decimal(str(value))


def _optional_date(value: object) -> date | None:
    if _is_missing(value):
        return None
    return date.fromisoformat(str(value))


def _optional_datetime(value: object) -> datetime | None:
    if _is_missing(value):
        return None
    return datetime.fromisoformat(str(value))


def _deserialize_project_tags(value: object) -> tuple[str, ...]:
    if _is_missing(value):
        return ()
    return tuple(json.loads(str(value)))


def _serialize_project_tags(tags: tuple[str, ...]) -> str | None:
    if not tags:
        return None
    return json.dumps(list(tags), separators=(",", ":"), ensure_ascii=False)


def canonical_transaction_from_enriched(
    transaction: SupportsCanonicalization,
    *,
    transaction_id: str,
    ingested_at: datetime | None,
) -> CanonicalTransaction:
    """Build a canonical persisted row from an enriched transaction."""
    return CanonicalTransaction(
        transaction_id=transaction_id,
        booking_date=transaction.booking_date,
        description=transaction.description,
        source_record_index=transaction.source_record_index,
        amount_native=transaction.amount_native,
        currency=transaction.currency,
        fx_rate_to_eur=transaction.fx_rate_to_eur,
        fx_rate_date=transaction.fx_rate_date,
        fx_source=transaction.fx_source,
        amount_eur=transaction.amount_eur,
        category=transaction.category,
        subcategory=transaction.subcategory,
        category_confidence=transaction.category_confidence,
        category_source=transaction.category_source,
        category_rule_id=transaction.category_rule_id,
        cashflow_type=transaction.cashflow_type,
        from_account_ref=transaction.from_account_ref,
        to_account_ref=transaction.to_account_ref,
        from_account_type=transaction.from_account_type,
        to_account_type=transaction.to_account_type,
        account_inference_source=transaction.account_inference_source,
        project=transaction.project,
        project_tags=transaction.project_tags,
        project_source=transaction.project_source,
        reviewed=transaction.reviewed,
        bank=transaction.bank,
        account_label=transaction.account_label,
        source_document_id=transaction.source_document_id,
        source_file=transaction.source_file,
        source_file_mtime=transaction.source_file_mtime,
        parser=transaction.parser,
        ingested_at=ingested_at,
    )


def canonical_dataframe_from_transactions(
    transactions: list[CanonicalTransaction],
) -> pd.DataFrame:
    """Serialize canonical transactions to a dataframe with stable column ordering."""
    rows = [
        {
            "transaction_id": tx.transaction_id,
            "booking_date": tx.booking_date.isoformat(),
            "description": tx.description,
            "source_record_index": tx.source_record_index,
            "amount_native": float(tx.amount_native),
            "currency": tx.currency,
            "fx_rate_to_eur": float(tx.fx_rate_to_eur) if tx.fx_rate_to_eur is not None else None,
            "fx_rate_date": tx.fx_rate_date.isoformat() if tx.fx_rate_date else None,
            "fx_source": tx.fx_source,
            "amount_eur": float(tx.amount_eur) if tx.amount_eur is not None else None,
            "category": tx.category,
            "subcategory": tx.subcategory,
            "category_confidence": tx.category_confidence,
            "category_source": tx.category_source,
            "category_rule_id": tx.category_rule_id,
            "cashflow_type": tx.cashflow_type,
            "from_account_ref": tx.from_account_ref,
            "to_account_ref": tx.to_account_ref,
            "from_account_type": tx.from_account_type,
            "to_account_type": tx.to_account_type,
            "account_inference_source": tx.account_inference_source,
            "project": tx.project,
            "project_tags": _serialize_project_tags(tx.project_tags),
            "project_source": tx.project_source,
            "reviewed": tx.reviewed,
            "bank": tx.bank,
            "account_label": tx.account_label,
            "source_document_id": tx.source_document_id,
            "source_file": str(tx.source_file),
            "source_file_mtime": tx.source_file_mtime.isoformat() if tx.source_file_mtime else None,
            "parser": tx.parser,
            "ingested_at": tx.ingested_at.isoformat() if tx.ingested_at else None,
        }
        for tx in transactions
    ]
    if not rows:
        return pd.DataFrame(columns=list(CANONICAL_TRANSACTION_COLUMNS))
    return pd.DataFrame(rows)[list(CANONICAL_TRANSACTION_COLUMNS)]


def ensure_canonical_dataframe_schema(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Backfill missing canonical columns and enforce stable column ordering."""
    if dataframe.empty:
        return pd.DataFrame(columns=list(CANONICAL_TRANSACTION_COLUMNS))
    normalized = dataframe.copy()
    for column in CANONICAL_TRANSACTION_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = None
    return normalized.loc[:, list(CANONICAL_TRANSACTION_COLUMNS)]


def canonical_transactions_from_dataframe(dataframe: pd.DataFrame) -> list[CanonicalTransaction]:
    """Deserialize canonical rows from a dataframe."""
    normalized = ensure_canonical_dataframe_schema(dataframe)
    if normalized.empty:
        return []

    transactions: list[CanonicalTransaction] = []
    for row in normalized.to_dict(orient="records"):
        transactions.append(
            CanonicalTransaction(
                transaction_id=str(row["transaction_id"]),
                booking_date=date.fromisoformat(str(row["booking_date"])),
                description=str(row["description"]),
                source_record_index=(
                    int(row["source_record_index"])
                    if row.get("source_record_index") not in (None, "")
                    and not pd.isna(row["source_record_index"])
                    else None
                ),
                amount_native=Decimal(str(row["amount_native"])),
                currency=str(row["currency"]),
                fx_rate_to_eur=_optional_decimal(row.get("fx_rate_to_eur")),
                fx_rate_date=_optional_date(row.get("fx_rate_date")),
                fx_source=_optional_str(row.get("fx_source")),
                amount_eur=_optional_decimal(row.get("amount_eur")),
                category=(
                    str(row["category"]) if row.get("category") is not None else "Uncategorized"
                ),
                subcategory=_optional_str(row.get("subcategory")),
                category_confidence=(
                    float(row["category_confidence"])
                    if row.get("category_confidence") is not None
                    and not pd.isna(row["category_confidence"])
                    else None
                ),
                category_source=(
                    str(row["category_source"])
                    if row.get("category_source") is not None
                    and not pd.isna(row["category_source"])
                    else (
                        "rule"
                        if row.get("category") is not None
                        and not pd.isna(row["category"])
                        and str(row["category"]) != "Uncategorized"
                        else None
                    )
                ),
                category_rule_id=_optional_str(row.get("category_rule_id")),
                cashflow_type=_optional_str(row.get("cashflow_type")),
                from_account_ref=_optional_str(row.get("from_account_ref")),
                to_account_ref=_optional_str(row.get("to_account_ref")),
                from_account_type=_optional_str(row.get("from_account_type")),
                to_account_type=_optional_str(row.get("to_account_type")),
                account_inference_source=_optional_str(row.get("account_inference_source")),
                project=_optional_str(row.get("project")),
                project_tags=_deserialize_project_tags(row.get("project_tags")),
                project_source=_optional_str(row.get("project_source")),
                reviewed=bool(row["reviewed"]) if row.get("reviewed") is not None else False,
                bank=str(row["bank"]),
                account_label=_optional_str(row.get("account_label")),
                source_document_id=_optional_str(row.get("source_document_id")),
                source_file=Path(str(row["source_file"])),
                source_file_mtime=_optional_datetime(row.get("source_file_mtime")),
                parser=str(row["parser"]),
                ingested_at=_optional_datetime(row.get("ingested_at")),
            )
        )
    return transactions

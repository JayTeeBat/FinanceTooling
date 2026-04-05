"""Canonical parquet transaction store."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.canonical import (
    CANONICAL_TRANSACTION_COLUMNS,
    CanonicalTransaction,
    SupportsCanonicalization,
    canonical_dataframe_from_transactions,
    canonical_transaction_from_enriched,
    canonical_transactions_from_dataframe,
    ensure_canonical_dataframe_schema,
)
from finance_tooling.models import Transaction


@dataclass(frozen=True)
class UpsertResult:
    """Result metadata for an upsert operation."""

    parquet_path: Path
    dataframe: pd.DataFrame
    new_rows: int
    total_rows: int


def _require_parquet_engine() -> None:
    try:
        __import__("pyarrow")
    except Exception as exc:
        raise RuntimeError(
            "Parquet support requires pyarrow. Install dependencies with `uv sync --all-groups`."
        ) from exc


def _normalize_description(description: str) -> str:
    return " ".join(description.strip().lower().split())


def compute_legacy_transaction_id(transaction: SupportsCanonicalization) -> str:
    """Compute the pre-source-record-index transaction id for migration/audits."""
    key_parts = [
        transaction.booking_date.isoformat(),
        _normalize_description(transaction.description),
        str(transaction.amount_native),
        transaction.currency.upper(),
        transaction.bank,
        transaction.account_label or "",
        str(transaction.source_file),
    ]
    payload = "|".join(key_parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_path_based_transaction_id(transaction: SupportsCanonicalization) -> str:
    """Compute the pre-source-document-id transaction id for migration/audits."""
    key_parts = [
        transaction.booking_date.isoformat(),
        _normalize_description(transaction.description),
        str(transaction.amount_native),
        transaction.currency.upper(),
        transaction.bank,
        transaction.account_label or "",
        str(transaction.source_file),
        "" if transaction.source_record_index is None else str(transaction.source_record_index),
    ]
    payload = "|".join(key_parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_transaction_id(transaction: SupportsCanonicalization) -> str:
    """Compute a stable transaction id used for idempotent upserts."""
    key_parts = [
        transaction.booking_date.isoformat(),
        _normalize_description(transaction.description),
        str(transaction.amount_native),
        transaction.currency.upper(),
        transaction.bank,
        transaction.account_label or "",
        transaction.source_document_id or str(transaction.source_file),
        "" if transaction.source_record_index is None else str(transaction.source_record_index),
    ]
    payload = "|".join(key_parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonicalize_transactions(
    transactions: list[Transaction],
    *,
    ingested_at: datetime | None = None,
) -> list[CanonicalTransaction]:
    """Convert enriched transactions into canonical persisted rows."""
    effective_ingested_at = ingested_at or datetime.now(UTC)
    return [
        canonical_transaction_from_enriched(
            transaction,
            transaction_id=compute_transaction_id(transaction),
            ingested_at=effective_ingested_at,
        )
        for transaction in transactions
    ]


def _read_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=list(CANONICAL_TRANSACTION_COLUMNS))
    _require_parquet_engine()
    data = pd.read_parquet(path)
    return ensure_canonical_dataframe_schema(data)


def transactions_from_dataframe(dataframe: pd.DataFrame) -> list[CanonicalTransaction]:
    """Compatibility helper returning typed canonical rows from a dataframe."""
    return canonical_transactions_from_dataframe(dataframe)


def _atomic_write_parquet(dataframe: pd.DataFrame, destination: Path) -> None:
    _require_parquet_engine()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(".tmp.parquet")
    dataframe.to_parquet(temp_path, index=False)
    temp_path.replace(destination)


def write_canonical_dataframe(parquet_path: Path, dataframe: pd.DataFrame) -> None:
    """Rewrite canonical parquet using the canonical column ordering."""
    normalized = ensure_canonical_dataframe_schema(dataframe)
    _atomic_write_parquet(normalized, parquet_path)


def upsert_transactions(parquet_path: Path, transactions: list[Transaction]) -> UpsertResult:
    """Upsert transactions by stable transaction id and return merged dataframe."""
    incoming = canonical_dataframe_from_transactions(canonicalize_transactions(transactions))
    existing = _read_existing(parquet_path)

    if existing.empty:
        merged = incoming.drop_duplicates(subset=["transaction_id"], keep="first")
        new_rows = len(merged)
    elif incoming.empty:
        merged = existing
        new_rows = 0
    else:
        incoming_deduped = incoming.drop_duplicates(subset=["transaction_id"], keep="first").copy()
        existing_ids = set(existing["transaction_id"])
        incoming_ids = set(incoming_deduped["transaction_id"])
        overlapping_ids = existing_ids & incoming_ids
        new_rows = len(incoming_ids - existing_ids)
        incoming_source_documents = {
            str(value).strip()
            for value in incoming_deduped["source_document_id"].dropna().tolist()
            if str(value).strip()
        }
        incoming_source_files = set(incoming_deduped["source_file"])

        if overlapping_ids:
            existing_ingested_at = (
                existing.loc[
                    existing["transaction_id"].isin(overlapping_ids),
                    ["transaction_id", "ingested_at"],
                ]
                .drop_duplicates(subset=["transaction_id"], keep="first")
                .set_index("transaction_id")["ingested_at"]
            )
            mask = incoming_deduped["transaction_id"].isin(overlapping_ids)
            incoming_deduped.loc[mask, "ingested_at"] = incoming_deduped.loc[
                mask, "transaction_id"
            ].map(existing_ingested_at)

        retained_existing = existing
        if incoming_source_documents:
            retained_existing = retained_existing[
                ~retained_existing["source_document_id"].isin(incoming_source_documents)
            ]
        if incoming_source_files:
            retained_existing = retained_existing[
                ~retained_existing["source_file"].isin(incoming_source_files)
            ]
        merged = pd.concat([retained_existing, incoming_deduped], ignore_index=True)

    merged = merged.sort_values(by=["booking_date", "transaction_id"]).reset_index(drop=True)
    _atomic_write_parquet(merged, parquet_path)

    return UpsertResult(
        parquet_path=parquet_path,
        dataframe=merged,
        new_rows=new_rows,
        total_rows=len(merged),
    )

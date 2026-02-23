"""Canonical parquet transaction store."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.models import CANONICAL_TRANSACTION_COLUMNS, Transaction


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


def compute_transaction_id(transaction: Transaction) -> str:
    """Compute a stable transaction id used for idempotent upserts."""
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


def _frame_from_transactions(transactions: list[Transaction]) -> pd.DataFrame:
    ingested_at = datetime.now(UTC)
    rows = [
        {
            "transaction_id": compute_transaction_id(tx),
            "booking_date": tx.booking_date.isoformat(),
            "description": tx.description,
            "amount_native": float(tx.amount_native),
            "currency": tx.currency,
            "fx_rate_to_eur": float(tx.fx_rate_to_eur) if tx.fx_rate_to_eur is not None else None,
            "fx_rate_date": tx.fx_rate_date.isoformat() if tx.fx_rate_date else None,
            "fx_source": tx.fx_source,
            "amount_eur": float(tx.amount_eur) if tx.amount_eur is not None else None,
            "category": tx.category,
            "bank": tx.bank,
            "account_label": tx.account_label,
            "source_file": str(tx.source_file),
            "source_file_mtime": tx.source_file_mtime.isoformat() if tx.source_file_mtime else None,
            "parser": tx.parser,
            "ingested_at": ingested_at.isoformat(),
        }
        for tx in transactions
    ]

    if not rows:
        return pd.DataFrame(columns=CANONICAL_TRANSACTION_COLUMNS)
    return pd.DataFrame(rows)[CANONICAL_TRANSACTION_COLUMNS]


def _read_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=CANONICAL_TRANSACTION_COLUMNS)
    _require_parquet_engine()
    data = pd.read_parquet(path)
    if data.empty:
        return pd.DataFrame(columns=CANONICAL_TRANSACTION_COLUMNS)
    for column in CANONICAL_TRANSACTION_COLUMNS:
        if column not in data.columns:
            data[column] = None
    return data[CANONICAL_TRANSACTION_COLUMNS]


def _atomic_write_parquet(dataframe: pd.DataFrame, destination: Path) -> None:
    _require_parquet_engine()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(".tmp.parquet")
    dataframe.to_parquet(temp_path, index=False)
    temp_path.replace(destination)


def upsert_transactions(parquet_path: Path, transactions: list[Transaction]) -> UpsertResult:
    """Upsert transactions by stable transaction id and return merged dataframe."""
    incoming = _frame_from_transactions(transactions)
    existing = _read_existing(parquet_path)

    if existing.empty:
        merged = incoming.drop_duplicates(subset=["transaction_id"], keep="first")
    elif incoming.empty:
        merged = existing
    else:
        unseen = incoming[~incoming["transaction_id"].isin(existing["transaction_id"])]
        merged = pd.concat([existing, unseen], ignore_index=True)

    merged = merged.sort_values(by=["booking_date", "transaction_id"]).reset_index(drop=True)
    _atomic_write_parquet(merged, parquet_path)

    new_rows = 0 if incoming.empty else len(merged) - len(existing)
    return UpsertResult(
        parquet_path=parquet_path,
        dataframe=merged,
        new_rows=new_rows,
        total_rows=len(merged),
    )

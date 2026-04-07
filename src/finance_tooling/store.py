"""Canonical parquet transaction store."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
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


def compute_legacy_transaction_id(transaction: Transaction) -> str:
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


def compute_path_based_transaction_id(transaction: Transaction) -> str:
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


def compute_transaction_id(transaction: Transaction) -> str:
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


def _serialize_project_tags(tags: tuple[str, ...]) -> str | None:
    if not tags:
        return None
    return json.dumps(list(tags), separators=(",", ":"), ensure_ascii=False)


def _frame_from_transactions(transactions: list[Transaction]) -> pd.DataFrame:
    ingested_at = datetime.now(UTC)
    rows = [
        {
            "transaction_id": compute_transaction_id(tx),
            "booking_date": tx.booking_date.isoformat(),
            "description": tx.description,
            "source_record_index": tx.source_record_index,
            "amount_native": float(tx.amount_native),
            "currency": tx.currency,
            "fx_rate_to_eur": float(tx.fx_rate_to_eur) if tx.fx_rate_to_eur is not None else None,
            "fx_rate_date": tx.fx_rate_date.isoformat() if tx.fx_rate_date else None,
            "fx_source": tx.fx_source,
            "amount_eur": float(tx.amount_eur) if tx.amount_eur is not None else None,
            "category_id": tx.category_id,
            "reporting_category_id": tx.reporting_category_id,
            "category": tx.category,
            "subcategory": tx.subcategory,
            "category_confidence": tx.category_confidence,
            "category_source": tx.category_source,
            "category_rule_id": tx.category_rule_id,
            "cashflow_type": tx.cashflow_type,
            "economic_role": tx.economic_role,
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


def transactions_from_dataframe(dataframe: pd.DataFrame) -> list[Transaction]:
    """Reconstruct transaction models from canonical dataframe rows."""
    if dataframe.empty:
        return []
    transactions: list[Transaction] = []
    for row in dataframe.to_dict(orient="records"):
        transactions.append(
            Transaction(
                booking_date=datetime.fromisoformat(str(row["booking_date"])).date(),
                description=str(row["description"]),
                source_record_index=(
                    int(row["source_record_index"])
                    if row.get("source_record_index") not in (None, "")
                    and not pd.isna(row["source_record_index"])
                    else None
                ),
                amount_native=Decimal(str(row["amount_native"])),
                currency=str(row["currency"]),
                source_file=Path(str(row["source_file"])),
                bank=str(row["bank"]),
                parser=str(row["parser"]),
                category_id=(
                    str(row["category_id"])
                    if row.get("category_id") is not None and not pd.isna(row["category_id"])
                    else None
                ),
                reporting_category_id=(
                    str(row["reporting_category_id"])
                    if row.get("reporting_category_id") is not None
                    and not pd.isna(row["reporting_category_id"])
                    else None
                ),
                category=str(row["category"])
                if row.get("category") is not None
                else "Uncategorized",
                subcategory=(
                    str(row["subcategory"])
                    if row.get("subcategory") is not None and not pd.isna(row["subcategory"])
                    else None
                ),
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
                category_rule_id=(
                    str(row["category_rule_id"])
                    if row.get("category_rule_id") is not None
                    and not pd.isna(row["category_rule_id"])
                    else None
                ),
                cashflow_type=(
                    str(row["cashflow_type"])
                    if row.get("cashflow_type") is not None and not pd.isna(row["cashflow_type"])
                    else None
                ),
                economic_role=(
                    str(row["economic_role"])
                    if row.get("economic_role") is not None and not pd.isna(row["economic_role"])
                    else None
                ),
                from_account_ref=(
                    str(row["from_account_ref"])
                    if row.get("from_account_ref") is not None
                    and not pd.isna(row["from_account_ref"])
                    else None
                ),
                to_account_ref=(
                    str(row["to_account_ref"])
                    if row.get("to_account_ref") is not None
                    and not pd.isna(row["to_account_ref"])
                    else None
                ),
                from_account_type=(
                    str(row["from_account_type"])
                    if row.get("from_account_type") is not None
                    and not pd.isna(row["from_account_type"])
                    else None
                ),
                to_account_type=(
                    str(row["to_account_type"])
                    if row.get("to_account_type") is not None
                    and not pd.isna(row["to_account_type"])
                    else None
                ),
                account_inference_source=(
                    str(row["account_inference_source"])
                    if row.get("account_inference_source") is not None
                    and not pd.isna(row["account_inference_source"])
                    else None
                ),
                project=(
                    str(row["project"])
                    if row.get("project") is not None and not pd.isna(row["project"])
                    else None
                ),
                project_tags=tuple(json.loads(row["project_tags"]))
                if row.get("project_tags") is not None and not pd.isna(row["project_tags"])
                else (),
                project_source=(
                    str(row["project_source"])
                    if row.get("project_source") is not None and not pd.isna(row["project_source"])
                    else None
                ),
                reviewed=bool(row["reviewed"]) if row.get("reviewed") is not None else False,
                account_label=(
                    str(row["account_label"])
                    if row.get("account_label") is not None and not pd.isna(row["account_label"])
                    else None
                ),
                source_document_id=(
                    str(row["source_document_id"])
                    if row.get("source_document_id") is not None
                    and not pd.isna(row["source_document_id"])
                    else None
                ),
                fx_rate_to_eur=(
                    Decimal(str(row["fx_rate_to_eur"]))
                    if row.get("fx_rate_to_eur") is not None and not pd.isna(row["fx_rate_to_eur"])
                    else None
                ),
                fx_rate_date=(
                    datetime.fromisoformat(str(row["fx_rate_date"])).date()
                    if row.get("fx_rate_date") is not None and not pd.isna(row["fx_rate_date"])
                    else None
                ),
                fx_source=(
                    str(row["fx_source"])
                    if row.get("fx_source") is not None and not pd.isna(row["fx_source"])
                    else None
                ),
                amount_eur=(
                    Decimal(str(row["amount_eur"]))
                    if row.get("amount_eur") is not None and not pd.isna(row["amount_eur"])
                    else None
                ),
                source_file_mtime=(
                    datetime.fromisoformat(str(row["source_file_mtime"]))
                    if row.get("source_file_mtime") is not None
                    and not pd.isna(row["source_file_mtime"])
                    else None
                ),
            )
        )
    return transactions


def _atomic_write_parquet(dataframe: pd.DataFrame, destination: Path) -> None:
    _require_parquet_engine()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(".tmp.parquet")
    dataframe.to_parquet(temp_path, index=False)
    temp_path.replace(destination)


def write_canonical_dataframe(parquet_path: Path, dataframe: pd.DataFrame) -> None:
    """Rewrite canonical parquet using the canonical column ordering."""
    normalized = dataframe.copy()
    for column in CANONICAL_TRANSACTION_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = None
    _atomic_write_parquet(normalized[CANONICAL_TRANSACTION_COLUMNS], parquet_path)


def upsert_transactions(parquet_path: Path, transactions: list[Transaction]) -> UpsertResult:
    """Upsert transactions by stable transaction id and return merged dataframe."""
    incoming = _frame_from_transactions(transactions)
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

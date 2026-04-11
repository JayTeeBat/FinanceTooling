"""Durable review-state store for human review workflow metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.core.models import Transaction
from finance_tooling.core.store import compute_transaction_id
from finance_tooling.review.common import (
    REVIEW_STATUS_COLUMN,
    REVIEWED_COLUMN,
    normalize_review_status_value,
    review_status_is_reviewed,
)

REVIEW_STATE_COLUMNS = (
    "transaction_id",
    REVIEW_STATUS_COLUMN,
    REVIEWED_COLUMN,
    "review_comment",
    "updated_at",
)


@dataclass(frozen=True)
class ReviewStateUpdateResult:
    """Result metadata for a review-state upsert."""

    path: Path
    rows_upserted: int
    rows_updated: int
    rows_inserted: int


def _require_parquet_engine() -> None:
    try:
        __import__("pyarrow")
    except Exception as exc:
        raise RuntimeError(
            "Parquet support requires pyarrow. Install dependencies with `uv sync --all-groups`."
        ) from exc


def _empty_review_state() -> pd.DataFrame:
    return pd.DataFrame(columns=list(REVIEW_STATE_COLUMNS))


def _normalize_reviewed(value: object, *, review_status: object | None = None) -> bool:
    return review_status_is_reviewed(review_status, reviewed_fallback=value)


def _normalize_comment(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def load_review_state(path: Path) -> pd.DataFrame:
    """Load persisted review state from parquet, returning an empty frame when absent."""
    if not path.exists():
        return _empty_review_state()
    _require_parquet_engine()
    dataframe = pd.read_parquet(path)
    if dataframe.empty:
        return _empty_review_state()
    for column in REVIEW_STATE_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = None
    normalized = dataframe.loc[:, list(REVIEW_STATE_COLUMNS)].copy()
    normalized["transaction_id"] = normalized["transaction_id"].astype(str)
    normalized[REVIEW_STATUS_COLUMN] = [
        normalize_review_status_value(status, reviewed_fallback=reviewed)
        for status, reviewed in zip(
            normalized[REVIEW_STATUS_COLUMN],
            normalized[REVIEWED_COLUMN],
            strict=False,
        )
    ]
    normalized[REVIEWED_COLUMN] = [
        _normalize_reviewed(reviewed, review_status=status)
        for reviewed, status in zip(
            normalized[REVIEWED_COLUMN],
            normalized[REVIEW_STATUS_COLUMN],
            strict=False,
        )
    ]
    normalized["review_comment"] = normalized["review_comment"].map(_normalize_comment)
    return normalized.drop_duplicates(subset=["transaction_id"], keep="last").reset_index(drop=True)


def _atomic_write_review_state(path: Path, dataframe: pd.DataFrame) -> None:
    _require_parquet_engine()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.parquet")
    dataframe.to_parquet(temp_path, index=False)
    temp_path.replace(path)


def upsert_review_state(path: Path, updates: pd.DataFrame) -> ReviewStateUpdateResult:
    """Upsert review-state rows by transaction_id."""
    if updates.empty:
        return ReviewStateUpdateResult(path=path, rows_upserted=0, rows_updated=0, rows_inserted=0)

    current = load_review_state(path)
    normalized_updates = updates.copy()
    for column in REVIEW_STATE_COLUMNS:
        if column not in normalized_updates.columns:
            normalized_updates[column] = None
    incoming = normalized_updates.loc[:, list(REVIEW_STATE_COLUMNS)].copy()
    incoming["transaction_id"] = incoming["transaction_id"].astype(str)
    incoming[REVIEW_STATUS_COLUMN] = [
        normalize_review_status_value(status, reviewed_fallback=reviewed)
        for status, reviewed in zip(
            incoming[REVIEW_STATUS_COLUMN],
            incoming[REVIEWED_COLUMN],
            strict=False,
        )
    ]
    incoming[REVIEWED_COLUMN] = [
        _normalize_reviewed(reviewed, review_status=status)
        for reviewed, status in zip(
            incoming[REVIEWED_COLUMN],
            incoming[REVIEW_STATUS_COLUMN],
            strict=False,
        )
    ]
    incoming["review_comment"] = incoming["review_comment"].map(_normalize_comment)
    incoming = incoming.drop_duplicates(subset=["transaction_id"], keep="last")

    current_ids = set(current["transaction_id"])
    incoming_ids = set(incoming["transaction_id"])
    rows_inserted = len(incoming_ids - current_ids)
    rows_updated = len(incoming_ids & current_ids)

    retained = current[~current["transaction_id"].isin(incoming_ids)]
    merged = (
        pd.concat([retained, incoming], ignore_index=True)
        .sort_values(by=["transaction_id"])
        .reset_index(drop=True)
    )
    _atomic_write_review_state(path, merged)
    return ReviewStateUpdateResult(
        path=path,
        rows_upserted=len(incoming),
        rows_updated=rows_updated,
        rows_inserted=rows_inserted,
    )


def build_review_state_updates(
    rows: list[dict[str, object]],
    *,
    reviewed_column: str,
    review_comment_column: str,
    review_status_column: str | None = None,
) -> pd.DataFrame:
    """Build review-state update rows from imported review records."""
    payload_rows: list[dict[str, object]] = []
    timestamp = datetime.now(UTC).isoformat()
    for row in rows:
        transaction_id = row.get("transaction_id")
        if transaction_id is None:
            continue
        normalized_transaction_id = str(transaction_id).strip()
        if not normalized_transaction_id:
            continue
        payload_rows.append(
            {
                "transaction_id": normalized_transaction_id,
                REVIEW_STATUS_COLUMN: normalize_review_status_value(
                    row.get(review_status_column) if review_status_column is not None else None,
                    reviewed_fallback=row.get(reviewed_column),
                ),
                REVIEWED_COLUMN: _normalize_reviewed(
                    row.get(reviewed_column),
                    review_status=(
                        row.get(review_status_column) if review_status_column is not None else None
                    ),
                ),
                "review_comment": _normalize_comment(row.get(review_comment_column)),
                "updated_at": timestamp,
            }
        )
    if not payload_rows:
        return _empty_review_state()
    return pd.DataFrame(payload_rows, columns=list(REVIEW_STATE_COLUMNS))


def apply_review_state(transactions: list[Transaction], path: Path) -> list[Transaction]:
    """Apply persisted review-state flags to transactions by transaction_id."""
    state = load_review_state(path)
    if state.empty:
        return transactions

    reviewed_by_id = (
        state.drop_duplicates(subset=["transaction_id"], keep="last")
        .set_index("transaction_id")[REVIEWED_COLUMN]
        .to_dict()
    )
    updated: list[Transaction] = []
    for transaction in transactions:
        transaction_id = compute_transaction_id(transaction)
        updated.append(
            Transaction(
                booking_date=transaction.booking_date,
                description=transaction.description,
                amount_native=transaction.amount_native,
                currency=transaction.currency,
                source_file=transaction.source_file,
                bank=transaction.bank,
                parser=transaction.parser,
                category_id=transaction.category_id,
                reporting_category_id=transaction.reporting_category_id,
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
                reviewed=bool(reviewed_by_id.get(transaction_id, transaction.reviewed)),
                account_label=transaction.account_label,
                source_document_id=transaction.source_document_id,
                fx_rate_to_eur=transaction.fx_rate_to_eur,
                fx_rate_date=transaction.fx_rate_date,
                fx_source=transaction.fx_source,
                amount_eur=transaction.amount_eur,
                source_record_index=transaction.source_record_index,
                source_file_mtime=transaction.source_file_mtime,
            )
        )
    return updated

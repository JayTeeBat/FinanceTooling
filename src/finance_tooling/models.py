"""Domain models for finance tooling workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

CANONICAL_TRANSACTION_COLUMNS = [
    "transaction_id",
    "booking_date",
    "description",
    "amount_native",
    "currency",
    "fx_rate_to_eur",
    "fx_rate_date",
    "fx_source",
    "amount_eur",
    "category",
    "bank",
    "account_label",
    "source_file",
    "source_file_mtime",
    "parser",
    "ingested_at",
]


@dataclass(frozen=True)
class Transaction:
    """Normalized transaction extracted from a statement."""

    booking_date: date
    description: str
    amount_native: Decimal
    currency: str
    source_file: Path
    bank: str
    parser: str
    category: str = "Uncategorized"
    account_label: str | None = None
    fx_rate_to_eur: Decimal | None = None
    fx_rate_date: date | None = None
    fx_source: str | None = None
    amount_eur: Decimal | None = None
    source_file_mtime: datetime | None = None


@dataclass(frozen=True)
class WorkflowResult:
    """Top-level result of a workflow execution."""

    dashboard_path: Path
    parquet_path: Path
    csv_path: Path
    json_path: Path
    summary_path: Path
    completeness_path: Path
    files_scanned: int
    files_failed: int
    transactions_parsed: int
    new_rows: int
    total_rows: int
    completeness_status: str
    completeness_coverage_ratio: float
    missing_source_file_count: int
    reconciliation_checkable_file_count: int
    reconciliation_fail_count: int
    reconciliation_uncheckable_file_count: int
    reconciliation_pass_ratio: float | None
    warnings: tuple[str, ...]

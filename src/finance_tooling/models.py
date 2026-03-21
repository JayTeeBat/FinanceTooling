"""Domain models for finance tooling workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from finance_tooling.backup import BackupRunResult

CANONICAL_TRANSACTION_COLUMNS = [
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
    subcategory: str | None = None
    category_confidence: float | None = None
    category_source: str | None = None
    category_rule_id: str | None = None
    project: str | None = None
    project_tags: tuple[str, ...] = ()
    project_source: str | None = None
    reviewed: bool = False
    account_label: str | None = None
    source_document_id: str | None = None
    fx_rate_to_eur: Decimal | None = None
    fx_rate_date: date | None = None
    fx_source: str | None = None
    amount_eur: Decimal | None = None
    source_record_index: int | None = None
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
    categorized_count: int
    uncategorized_count: int
    categorized_amount_eur_abs: float
    uncategorized_amount_eur_abs: float
    categorized_amount_eur_abs_ratio: float
    uncategorized_amount_eur_abs_ratio: float
    warnings: tuple[str, ...] = ()
    categorized_count_delta: int | None = None
    uncategorized_count_delta: int | None = None
    categorized_amount_eur_abs_delta: float | None = None
    uncategorized_amount_eur_abs_delta: float | None = None
    backup_run: BackupRunResult | None = None
    run_mode: str = "incremental"
    files_selected_for_processing: int = 0
    files_skipped_already_committed: int = 0
    files_skipped_modified_existing: int = 0
    files_missing_since_last_commit: int = 0
    dataset_stale: bool = False
    stale_reasons: tuple[str, ...] = ()

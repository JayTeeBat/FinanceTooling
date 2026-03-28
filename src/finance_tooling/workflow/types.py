"""Typed stage contracts for workflow orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TypedDict

import pandas as pd

from finance_tooling.classify import ClassificationDiagnostics
from finance_tooling.models import Transaction
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.store import UpsertResult


class ParserCandidate(TypedDict):
    """Single parser score candidate for diagnostics payloads."""

    parser: str
    score: int


class ParserSelectionDiagnostic(TypedDict):
    """Per-file parser selection diagnostics."""

    source_file: str
    selected_parser: str
    selected_score: int
    threshold: int
    top_candidates: list[ParserCandidate]


class HsbcSelectionDiagnostic(TypedDict):
    """Per-month HSBC source-selection diagnostics."""

    statement_date: str
    selected_source: str
    csv_transaction_count: int
    pdf_transaction_count: int
    csv_transaction_sum: str
    pdf_transaction_sum: str
    selected_transaction_sum: str
    csv_abs_difference: float | None
    pdf_abs_difference: float | None
    has_pdf_balance_validation: bool
    statement_period_start: str | None
    statement_period_end: str | None


class HsbcBoundaryDiagnostic(TypedDict):
    """Per-file HSBC boundary-state diagnostics."""

    source_file: str
    table_start_count: int
    table_end_count: int
    rows_seen_in_table: int
    rows_rejected_outside_table: int
    rows_rejected_after_table: int
    transition_anomaly_count: int


class HsbcSignDiagnostic(TypedDict):
    """Per-file HSBC sign-resolution diagnostics."""

    source_file: str
    sign_from_running_balance_count: int
    sign_from_column_position_count: int
    sign_from_token_marker_count: int
    sign_from_description_marker_count: int
    sign_from_fallback_hint_count: int
    sign_default_debit_count: int
    sign_conflict_running_vs_marker_count: int
    sign_unresolved_ambiguous_count: int


class SummaryPayload(TypedDict):
    """Run summary payload persisted to JSON."""

    generated_at: str
    files_scanned: int
    files_failed: int
    transactions_parsed: int
    new_rows: int
    total_rows: int
    parquet_path: str
    dashboard_path: str
    completeness_report_path: str
    completeness_status: str
    file_coverage_ratio: float
    missing_source_file_count: int
    statement_reconciliation_checkable_file_count: int
    statement_reconciliation_fail_count: int
    statement_reconciliation_uncheckable_file_count: int
    statement_reconciliation_pass_ratio: float | None
    statement_reconciliation_median_abs_difference: float | None
    statement_reconciliation_hsbc_median_abs_difference: float | None
    parser_low_confidence_file_count: int
    parser_selection_diagnostics: list[ParserSelectionDiagnostic]
    hsbc_csv_files_scanned: int
    hsbc_csv_statement_replaced_count: int
    hsbc_pdf_fallback_statement_count: int
    hsbc_csv_only_statement_count: int
    hsbc_pdf_balance_validated_count: int
    hsbc_pdf_balance_validation_fail_count: int
    hsbc_selection_policy: str
    hsbc_adaptive_source_switch_count: int
    hsbc_selected_csv_month_count: int
    hsbc_selected_pdf_month_count: int
    hsbc_period_remap_applied_month_count: int
    hsbc_period_remap_reassigned_tx_count: int
    hsbc_period_remap_unassigned_csv_tx_count: int
    hsbc_period_parse_variant_match_count: int
    hsbc_boundary_table_start_count: int
    hsbc_boundary_table_end_count: int
    hsbc_boundary_rows_seen_in_table: int
    hsbc_boundary_rows_rejected_outside_table: int
    hsbc_boundary_rows_rejected_after_table: int
    hsbc_boundary_transition_anomaly_count: int
    hsbc_boundary_diagnostics: list[HsbcBoundaryDiagnostic]
    hsbc_sign_from_running_balance_count: int
    hsbc_sign_from_column_position_count: int
    hsbc_sign_from_token_marker_count: int
    hsbc_sign_from_description_marker_count: int
    hsbc_sign_from_fallback_hint_count: int
    hsbc_sign_default_debit_count: int
    hsbc_sign_conflict_running_vs_marker_count: int
    hsbc_sign_unresolved_ambiguous_count: int
    hsbc_sign_diagnostics: list[HsbcSignDiagnostic]
    hsbc_selection_diagnostics: list[HsbcSelectionDiagnostic]
    ingest_parser_duration_seconds_by_parser: dict[str, float]
    ingest_duration_seconds_by_bank: dict[str, float]
    ingest_text_cache_enabled: bool
    ingest_text_cache_hits: int
    ingest_text_cache_misses: int
    ingest_text_cache_write_count: int
    categorized_count: int
    uncategorized_count: int
    uncategorized_ratio: float
    categorized_amount_eur_abs: float
    uncategorized_amount_eur_abs: float
    total_amount_eur_abs: float
    categorized_amount_eur_abs_ratio: float
    uncategorized_amount_eur_abs_ratio: float
    reviewed_count: int
    reviewed_ratio: float
    manual_category_carry_forward_applied_count: int
    manual_category_carry_forward_ambiguous_skipped_count: int
    manual_category_carry_forward_unmatched_count: int
    category_source_counts: dict[str, int]
    category_metrics_by_bank: list[dict[str, object]]
    top_uncategorized_descriptions: list[dict[str, object]]
    top_rules_by_hits: list[dict[str, object]]
    category_rules_path: str
    project_rules_path: str
    budget_targets_path: str
    project_overrides_path: str
    transaction_overrides_path: str
    review_state_path: str
    fx_cache_path: str
    source_inventory_path: str
    backup_run_id: str | None
    backup_processed_dir: str | None
    backup_config_dir: str | None
    backup_manifest_paths: list[str]
    backup_copied_file_count: int
    backup_missing_file_count: int
    backup_pruned_run_ids: list[str]
    run_mode: str
    files_selected_for_processing: int
    files_skipped_already_committed: int
    files_skipped_modified_existing: int
    files_missing_since_last_commit: int
    dataset_stale: bool
    stale_reasons: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class IngestResult:
    """Outputs of statement discovery and parsing ingestion."""

    source_files: list[Path]
    raw_file_count: int
    duplicate_raw_file_count: int
    source_inventory_path: Path | None
    all_source_files: list[Path]
    selected_source_files: list[Path]
    transactions: list[Transaction]
    validations: list[StatementValidation]
    warnings: list[str]
    files_failed: int
    processed_source_files: list[Path]
    parser_selection_diagnostics: list[ParserSelectionDiagnostic]
    parser_low_confidence_file_count: int
    hsbc_statement_periods_by_date: dict[str, tuple[date, date]]
    hsbc_period_parse_variant_match_count: int
    hsbc_boundary_metrics: dict[str, int]
    hsbc_boundary_diagnostics: list[HsbcBoundaryDiagnostic]
    hsbc_sign_metrics: dict[str, int]
    hsbc_sign_diagnostics: list[HsbcSignDiagnostic]
    hsbc_csv_files_scanned: int
    parser_duration_seconds_by_parser: dict[str, float]
    duration_seconds_by_bank: dict[str, float]
    text_cache_enabled: bool
    text_cache_hits: int
    text_cache_misses: int
    text_cache_write_count: int
    run_mode: str = "incremental"
    files_selected_for_processing: int = 0
    files_skipped_already_committed: int = 0
    files_skipped_modified_existing: int = 0
    files_missing_since_last_commit: int = 0
    dataset_stale: bool = False
    stale_reasons: tuple[str, ...] = ()
    staged_batch_manifest_path: Path | None = None


@dataclass(frozen=True)
class HsbcMergeResult:
    """Outputs of HSBC merge/reconciliation source selection stage."""

    transactions: list[Transaction]
    validations: list[StatementValidation]
    warnings: list[str]
    metrics: dict[str, int]
    selection_diagnostics: list[HsbcSelectionDiagnostic]


@dataclass(frozen=True)
class EnrichmentResult:
    """Outputs of classification and FX enrichment stage."""

    transactions: list[Transaction]
    warnings: list[str]
    classification_diagnostics: ClassificationDiagnostics
    manual_category_carry_forward_applied_count: int
    manual_category_carry_forward_ambiguous_skipped_count: int
    manual_category_carry_forward_unmatched_count: int


@dataclass(frozen=True)
class PersistResult:
    """Outputs of persistence and reporting stage."""

    upsert: UpsertResult
    dashboard_path: Path
    completeness_report: dict[str, object]
    completeness_status: str
    completeness_coverage_ratio: float
    missing_source_file_count: int
    reconciliation_checkable_count: int
    reconciliation_fail_count: int
    reconciliation_uncheckable_count: int
    reconciliation_pass_ratio: float | None
    reconciliation_median_abs_difference: float | None
    hsbc_abs_difference: float | None


@dataclass(frozen=True)
class StagingWriteResult:
    """Metadata for a staged transaction parquet write."""

    path: Path
    rows_written: int
    columns: tuple[str, ...]


@dataclass(frozen=True)
class ExportResult:
    """File export metadata for downstream reporting."""

    dataframe: pd.DataFrame

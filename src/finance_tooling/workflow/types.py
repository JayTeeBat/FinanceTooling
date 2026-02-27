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
    category_source_counts: dict[str, int]
    category_metrics_by_bank: list[dict[str, object]]
    top_uncategorized_descriptions: list[dict[str, object]]
    top_rules_by_hits: list[dict[str, object]]
    category_rules_path: str
    category_overrides_path: str
    fx_cache_path: str
    warnings: list[str]


@dataclass(frozen=True)
class IngestResult:
    """Outputs of statement discovery and parsing ingestion."""

    source_files: list[Path]
    transactions: list[Transaction]
    validations: list[StatementValidation]
    warnings: list[str]
    files_failed: int
    parser_selection_diagnostics: list[ParserSelectionDiagnostic]
    parser_low_confidence_file_count: int
    hsbc_statement_periods_by_date: dict[str, tuple[date, date]]
    hsbc_period_parse_variant_match_count: int
    hsbc_csv_files_scanned: int
    parser_duration_seconds_by_parser: dict[str, float]
    duration_seconds_by_bank: dict[str, float]
    text_cache_enabled: bool
    text_cache_hits: int
    text_cache_misses: int
    text_cache_write_count: int


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
class ExportResult:
    """File export metadata for downstream reporting."""

    dataframe: pd.DataFrame

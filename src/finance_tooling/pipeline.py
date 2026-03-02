"""Workflow orchestration for scanning, extracting, classifying, and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from finance_tooling.config import Settings
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.extract import extract_text_from_pdf
from finance_tooling.models import WorkflowResult
from finance_tooling.parsers import select_parser_with_diagnostics
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.scanner import discover_statement_pdfs
from finance_tooling.store import upsert_transactions
from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.hsbc_merge import merge_hsbc_sources
from finance_tooling.workflow.ingest import ingest_statements as ingest_workflow_stage
from finance_tooling.workflow.ingest import parse_hsbc_statement_period
from finance_tooling.workflow.reporting import persist_and_report, write_json
from finance_tooling.workflow.staging import read_staged_transactions, write_staged_transactions
from finance_tooling.workflow.types import (
    HsbcBoundaryDiagnostic,
    HsbcSelectionDiagnostic,
    HsbcSignDiagnostic,
    ParserSelectionDiagnostic,
)


@dataclass(frozen=True)
class IngestExecutionResult:
    """Outputs of ingest stage execution and staged handoff metadata."""

    staged_path: Path
    ingest_summary_path: Path
    files_scanned: int
    files_failed: int
    transactions_parsed: int
    hsbc_csv_files_scanned: int
    parser_low_confidence_file_count: int
    warnings: tuple[str, ...]
    source_files: tuple[Path, ...]
    validations: tuple[StatementValidation, ...]
    parser_selection_diagnostics: tuple[ParserSelectionDiagnostic, ...]
    hsbc_merge_metrics: dict[str, int]
    hsbc_period_parse_variant_match_count: int
    hsbc_boundary_metrics: dict[str, int]
    hsbc_boundary_diagnostics: tuple[HsbcBoundaryDiagnostic, ...]
    hsbc_sign_metrics: dict[str, int]
    hsbc_sign_diagnostics: tuple[HsbcSignDiagnostic, ...]
    hsbc_selection_diagnostics: tuple[HsbcSelectionDiagnostic, ...]
    ingest_parser_duration_seconds_by_parser: dict[str, float]
    ingest_duration_seconds_by_bank: dict[str, float]
    ingest_text_cache_enabled: bool
    ingest_text_cache_hits: int
    ingest_text_cache_misses: int
    ingest_text_cache_write_count: int


def _default_hsbc_merge_metrics() -> dict[str, int]:
    return {
        "hsbc_csv_statement_replaced_count": 0,
        "hsbc_pdf_fallback_statement_count": 0,
        "hsbc_csv_only_statement_count": 0,
        "hsbc_pdf_balance_validated_count": 0,
        "hsbc_pdf_balance_validation_fail_count": 0,
        "hsbc_adaptive_source_switch_count": 0,
        "hsbc_selected_csv_month_count": 0,
        "hsbc_selected_pdf_month_count": 0,
        "hsbc_period_remap_applied_month_count": 0,
        "hsbc_period_remap_reassigned_tx_count": 0,
        "hsbc_period_remap_unassigned_csv_tx_count": 0,
    }


def _default_hsbc_boundary_metrics() -> dict[str, int]:
    return {
        "table_start_count": 0,
        "table_end_count": 0,
        "rows_seen_in_table": 0,
        "rows_rejected_outside_table": 0,
        "rows_rejected_after_table": 0,
        "transition_anomaly_count": 0,
    }


def _default_hsbc_sign_metrics() -> dict[str, int]:
    return {
        "sign_from_running_balance_count": 0,
        "sign_from_column_position_count": 0,
        "sign_from_token_marker_count": 0,
        "sign_from_description_marker_count": 0,
        "sign_from_fallback_hint_count": 0,
        "sign_default_debit_count": 0,
        "sign_conflict_running_vs_marker_count": 0,
        "sign_unresolved_ambiguous_count": 0,
    }


def _parse_hsbc_statement_period(full_text: str) -> tuple[date, date] | None:
    """Compatibility wrapper for HSBC statement period parser."""
    return parse_hsbc_statement_period(full_text)


def run_ingest(settings: Settings) -> IngestExecutionResult:
    """Execute ingest stage and write staged transaction artifacts."""
    ingest = ingest_workflow_stage(
        settings,
        discover_statement_pdfs=discover_statement_pdfs,
        extract_text_from_pdf=extract_text_from_pdf,
        select_parser_with_diagnostics=select_parser_with_diagnostics,
    )

    hsbc_merge = merge_hsbc_sources(
        ingest.transactions,
        ingest.validations,
        ingest.source_files,
        ingest.hsbc_statement_periods_by_date,
    )
    warnings = [
        *ingest.warnings,
        *hsbc_merge.warnings,
    ]
    staging = write_staged_transactions(settings.staged_transactions_path, hsbc_merge.transactions)
    ingest_summary_path = settings.summary_json_path.parent / "ingest_summary.json"
    ingest_summary_payload: dict[str, object] = {
        "generated_at": date.today().isoformat(),
        "files_scanned": len(ingest.source_files),
        "files_failed": ingest.files_failed,
        "transactions_parsed": len(hsbc_merge.transactions),
        "staged_transactions_path": str(staging.path),
        "hsbc_csv_files_scanned": ingest.hsbc_csv_files_scanned,
        "parser_low_confidence_file_count": ingest.parser_low_confidence_file_count,
        "warnings": warnings,
        "ingest_parser_duration_seconds_by_parser": ingest.parser_duration_seconds_by_parser,
        "ingest_duration_seconds_by_bank": ingest.duration_seconds_by_bank,
        "ingest_text_cache_enabled": ingest.text_cache_enabled,
        "ingest_text_cache_hits": ingest.text_cache_hits,
        "ingest_text_cache_misses": ingest.text_cache_misses,
        "ingest_text_cache_write_count": ingest.text_cache_write_count,
    }
    write_json(ingest_summary_path, ingest_summary_payload)

    return IngestExecutionResult(
        staged_path=staging.path,
        ingest_summary_path=ingest_summary_path,
        files_scanned=len(ingest.source_files),
        files_failed=ingest.files_failed,
        transactions_parsed=len(hsbc_merge.transactions),
        hsbc_csv_files_scanned=ingest.hsbc_csv_files_scanned,
        parser_low_confidence_file_count=ingest.parser_low_confidence_file_count,
        warnings=tuple(warnings),
        source_files=tuple(ingest.source_files),
        validations=tuple(hsbc_merge.validations),
        parser_selection_diagnostics=tuple(ingest.parser_selection_diagnostics),
        hsbc_merge_metrics=hsbc_merge.metrics,
        hsbc_period_parse_variant_match_count=ingest.hsbc_period_parse_variant_match_count,
        hsbc_boundary_metrics=ingest.hsbc_boundary_metrics,
        hsbc_boundary_diagnostics=tuple(ingest.hsbc_boundary_diagnostics),
        hsbc_sign_metrics=ingest.hsbc_sign_metrics,
        hsbc_sign_diagnostics=tuple(ingest.hsbc_sign_diagnostics),
        hsbc_selection_diagnostics=tuple(hsbc_merge.selection_diagnostics),
        ingest_parser_duration_seconds_by_parser=ingest.parser_duration_seconds_by_parser,
        ingest_duration_seconds_by_bank=ingest.duration_seconds_by_bank,
        ingest_text_cache_enabled=ingest.text_cache_enabled,
        ingest_text_cache_hits=ingest.text_cache_hits,
        ingest_text_cache_misses=ingest.text_cache_misses,
        ingest_text_cache_write_count=ingest.text_cache_write_count,
    )


def run_transform(
    settings: Settings,
    *,
    staged_path: Path | None = None,
    ingest_result: IngestExecutionResult | None = None,
) -> WorkflowResult:
    """Execute transform stage from staged transaction artifact."""
    input_staged_path = staged_path or settings.staged_transactions_path
    staged_transactions = read_staged_transactions(input_staged_path)
    enrichment = enrich_transactions(staged_transactions, settings)

    if ingest_result is not None:
        source_files = list(ingest_result.source_files)
        files_failed = ingest_result.files_failed
        validations = list(ingest_result.validations)
        parser_selection_diagnostics = list(ingest_result.parser_selection_diagnostics)
        parser_low_confidence_file_count = ingest_result.parser_low_confidence_file_count
        hsbc_csv_files_scanned = ingest_result.hsbc_csv_files_scanned
        hsbc_merge_metrics = ingest_result.hsbc_merge_metrics
        hsbc_period_parse_variant_match_count = ingest_result.hsbc_period_parse_variant_match_count
        hsbc_boundary_metrics = ingest_result.hsbc_boundary_metrics
        hsbc_boundary_diagnostics = list(ingest_result.hsbc_boundary_diagnostics)
        hsbc_sign_metrics = ingest_result.hsbc_sign_metrics
        hsbc_sign_diagnostics = list(ingest_result.hsbc_sign_diagnostics)
        hsbc_selection_diagnostics = list(ingest_result.hsbc_selection_diagnostics)
        ingest_parser_duration_seconds_by_parser = (
            ingest_result.ingest_parser_duration_seconds_by_parser
        )
        ingest_duration_seconds_by_bank = ingest_result.ingest_duration_seconds_by_bank
        ingest_text_cache_enabled = ingest_result.ingest_text_cache_enabled
        ingest_text_cache_hits = ingest_result.ingest_text_cache_hits
        ingest_text_cache_misses = ingest_result.ingest_text_cache_misses
        ingest_text_cache_write_count = ingest_result.ingest_text_cache_write_count
        warnings = [
            *ingest_result.warnings,
            *enrichment.warnings,
        ]
    else:
        source_files = sorted({transaction.source_file for transaction in staged_transactions})
        files_failed = 0
        validations = []
        parser_selection_diagnostics = []
        parser_low_confidence_file_count = 0
        hsbc_csv_files_scanned = 0
        hsbc_merge_metrics = _default_hsbc_merge_metrics()
        hsbc_period_parse_variant_match_count = 0
        hsbc_boundary_metrics = _default_hsbc_boundary_metrics()
        hsbc_boundary_diagnostics = []
        hsbc_sign_metrics = _default_hsbc_sign_metrics()
        hsbc_sign_diagnostics = []
        hsbc_selection_diagnostics = []
        ingest_parser_duration_seconds_by_parser = {}
        ingest_duration_seconds_by_bank = {}
        ingest_text_cache_enabled = False
        ingest_text_cache_hits = 0
        ingest_text_cache_misses = 0
        ingest_text_cache_write_count = 0
        warnings = [*enrichment.warnings]

    result, _summary_payload = persist_and_report(
        settings=settings,
        source_files=source_files,
        files_failed=files_failed,
        transactions=enrichment.transactions,
        validations=validations,
        parser_selection_diagnostics=parser_selection_diagnostics,
        parser_low_confidence_file_count=parser_low_confidence_file_count,
        hsbc_csv_files_scanned=hsbc_csv_files_scanned,
        hsbc_merge_metrics=hsbc_merge_metrics,
        hsbc_period_parse_variant_match_count=hsbc_period_parse_variant_match_count,
        hsbc_boundary_metrics=hsbc_boundary_metrics,
        hsbc_boundary_diagnostics=hsbc_boundary_diagnostics,
        hsbc_sign_metrics=hsbc_sign_metrics,
        hsbc_sign_diagnostics=hsbc_sign_diagnostics,
        hsbc_selection_diagnostics=hsbc_selection_diagnostics,
        ingest_parser_duration_seconds_by_parser=ingest_parser_duration_seconds_by_parser,
        ingest_duration_seconds_by_bank=ingest_duration_seconds_by_bank,
        ingest_text_cache_enabled=ingest_text_cache_enabled,
        ingest_text_cache_hits=ingest_text_cache_hits,
        ingest_text_cache_misses=ingest_text_cache_misses,
        ingest_text_cache_write_count=ingest_text_cache_write_count,
        classification_diagnostics=enrichment.classification_diagnostics,
        warnings=warnings,
        upsert_transactions_fn=upsert_transactions,
        render_dashboard_html_fn=render_dashboard_html,
    )
    return result


def run_update(
    settings: Settings,
    *,
    ingest_only: bool = False,
    transform_only: bool = False,
) -> WorkflowResult | IngestExecutionResult:
    """Run ingest+transform orchestration with optional stage-only execution."""
    if ingest_only and transform_only:
        raise ValueError("--ingest-only and --transform-only are mutually exclusive.")

    if transform_only:
        return run_transform(settings)

    ingest_result = run_ingest(settings)
    if ingest_only:
        return ingest_result

    return run_transform(
        settings,
        staged_path=ingest_result.staged_path,
        ingest_result=ingest_result,
    )


def run_workflow(settings: Settings) -> WorkflowResult:
    """Compatibility wrapper for the combined update workflow."""
    result = run_update(settings)
    if isinstance(result, IngestExecutionResult):
        raise RuntimeError("run_workflow expects a full workflow result, not ingest-only output.")
    return result

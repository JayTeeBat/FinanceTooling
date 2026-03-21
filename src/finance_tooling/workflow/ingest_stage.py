"""Ingest stage orchestration and staged artifact writing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from finance_tooling.backup import BackupRunResult, create_stage_backup_run
from finance_tooling.config import Settings
from finance_tooling.extract import extract_text_from_pdf
from finance_tooling.parsers import select_parser_with_diagnostics
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.scanner import discover_statement_pdfs
from finance_tooling.workflow.hsbc_merge import merge_hsbc_sources
from finance_tooling.workflow.ingest import ingest_statements as ingest_workflow_stage
from finance_tooling.workflow.ingest import parse_hsbc_statement_period
from finance_tooling.workflow.reporting import write_json
from finance_tooling.workflow.staging import write_staged_transactions
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
    raw_files_discovered: int
    duplicate_raw_file_count: int
    source_inventory_path: Path
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
    backup_run: BackupRunResult | None = None


def parse_hsbc_statement_period_compat(full_text: str) -> tuple[date, date] | None:
    """Compatibility wrapper for HSBC statement period parser."""
    return parse_hsbc_statement_period(full_text)


def run_ingest(
    settings: Settings,
    *,
    backup_command: str = "ingest",
) -> IngestExecutionResult:
    """Execute ingest stage and write staged transaction artifacts."""
    backup_run = create_stage_backup_run(
        stage="ingest",
        command=backup_command,
        processed_dir=settings.summary_json_path.parent,
        processed_targets=(settings.staged_transactions_path,),
    )
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
        "raw_files_discovered": ingest.raw_file_count,
        "duplicate_raw_file_count": ingest.duplicate_raw_file_count,
        "files_failed": ingest.files_failed,
        "transactions_parsed": len(hsbc_merge.transactions),
        "staged_transactions_path": str(staging.path),
        "source_inventory_path": str(ingest.source_inventory_path),
        "hsbc_csv_files_scanned": ingest.hsbc_csv_files_scanned,
        "parser_low_confidence_file_count": ingest.parser_low_confidence_file_count,
        "backup_run_id": backup_run.run_id,
        "backup_processed_dir": (
            str(backup_run.processed_backup_dir) if backup_run.processed_backup_dir else None
        ),
        "backup_config_dir": str(backup_run.config_backup_dir)
        if backup_run.config_backup_dir
        else None,
        "backup_manifest_paths": [str(path) for path in backup_run.manifest_paths],
        "backup_copied_file_count": len(backup_run.copied_files),
        "backup_missing_file_count": len(backup_run.skipped_missing_files),
        "backup_pruned_run_ids": list(backup_run.pruned_run_ids),
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
        raw_files_discovered=ingest.raw_file_count,
        duplicate_raw_file_count=ingest.duplicate_raw_file_count,
        source_inventory_path=ingest.source_inventory_path,
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
        backup_run=backup_run,
    )

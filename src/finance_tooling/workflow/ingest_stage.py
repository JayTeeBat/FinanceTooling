"""Ingest stage orchestration and staged artifact writing."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from tqdm import tqdm

from finance_tooling.core.backup import BackupRunResult, create_stage_backup_run
from finance_tooling.core.config import INGEST_SUMMARY_FILENAME, Settings, ingest_state_path
from finance_tooling.core.extract import extract_text_from_pdf
from finance_tooling.core.scanner import discover_statement_pdfs
from finance_tooling.core.source_inventory import build_source_inventory
from finance_tooling.parsers import select_parser_with_diagnostics
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.workflow.hsbc_diagnostics import analyze_hsbc_parser_outputs
from finance_tooling.workflow.incremental_state import (
    build_incremental_selection_plan,
    build_manifest_from_selection_plan,
    load_source_registry,
    resolve_staged_batch_manifest_path,
    source_registry_path,
    staged_batch_manifest_path,
    write_staged_batch_manifest,
)
from finance_tooling.workflow.ingest import ingest_statements as ingest_workflow_stage
from finance_tooling.workflow.ingest import parse_hsbc_statement_period
from finance_tooling.workflow.reporting import write_json
from finance_tooling.workflow.staging import (
    resolve_staged_transactions_path,
    write_staged_transactions,
)
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
    files_scanned: int
    raw_files_discovered: int
    duplicate_raw_file_count: int
    files_failed: int
    transactions_parsed: int
    hsbc_csv_files_scanned: int
    parser_low_confidence_file_count: int
    warnings: tuple[str, ...]
    source_files: tuple[Path, ...]
    selected_source_files: tuple[Path, ...]
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
    effective_ingest_workers: int = 1
    newly_covered_months: tuple[str, ...] = ()
    ingest_summary_path: Path | None = None
    run_mode: str = "incremental"
    files_selected_for_processing: int = 0
    files_skipped_already_committed: int = 0
    files_skipped_modified_existing: int = 0
    files_missing_since_last_commit: int = 0
    dataset_stale: bool = False
    stale_reasons: tuple[str, ...] = ()
    staged_batch_manifest_path: Path | None = None
    backup_run: BackupRunResult | None = None


def parse_hsbc_statement_period_compat(full_text: str) -> tuple[date, date] | None:
    """Compatibility wrapper for HSBC statement period parser."""
    return parse_hsbc_statement_period(full_text)


def run_ingest(
    settings: Settings,
    *,
    backup_command: str = "ingest",
    run_mode: str = "incremental",
    emit_ingest_summary: bool = False,
    backup_run: BackupRunResult | None = None,
) -> IngestExecutionResult:
    """Execute ingest stage and write staged transaction artifacts."""
    registry = load_source_registry(source_registry_path(settings))
    selection_plan = build_incremental_selection_plan(
        settings=settings,
        run_mode=run_mode,  # type: ignore[arg-type]
        current_inventory=build_source_inventory(discover_statement_pdfs(settings.input_path)),
        registry=registry,
    )
    existing_staged_path = resolve_staged_transactions_path(settings)
    existing_manifest_path = resolve_staged_batch_manifest_path(settings)
    if (
        run_mode == "incremental"
        and not selection_plan.selected_entries
        and not selection_plan.dataset_stale
        and existing_staged_path.exists()
        and existing_manifest_path.exists()
    ):
        ingest_summary_path: Path | None = None
        warnings = ("No-op ingest: raw files unchanged; reused existing staged batch.",)
        if emit_ingest_summary:
            ingest_summary_path = ingest_state_path(settings) / INGEST_SUMMARY_FILENAME
            ingest_summary_payload: dict[str, object] = {
                "generated_at": datetime.now(UTC).isoformat(),
                "stage": "ingest",
                "files_scanned": len(selection_plan.all_representative_source_files),
                "run_mode": "incremental",
                "files_selected_for_processing": 0,
                "files_skipped_already_committed": selection_plan.files_skipped_already_committed,
                "files_skipped_modified_existing": 0,
                "files_missing_since_last_commit": 0,
                "dataset_stale": False,
                "stale_reasons": [],
                "raw_files_discovered": selection_plan.current_inventory.raw_file_count,
                "duplicate_raw_file_count": (
                    selection_plan.current_inventory.ignored_duplicate_file_count
                ),
                "files_failed": 0,
                "transactions_parsed": 0,
                "newly_covered_months": [],
                "staged_transactions_path": str(existing_staged_path),
                "staged_batch_manifest_path": str(existing_manifest_path),
                "hsbc_csv_files_scanned": 0,
                "parser_low_confidence_file_count": 0,
                "backup_run_id": None,
                "backup_root": None,
                "backup_snapshot_dir": None,
                "backup_processed_dir": None,
                "backup_config_dir": None,
                "backup_manifest_paths": [],
                "backup_copied_file_count": 0,
                "backup_missing_file_count": 0,
                "backup_pruned_run_ids": [],
                "warnings": list(warnings),
                "ingest_parser_duration_seconds_by_parser": {},
                "ingest_duration_seconds_by_bank": {},
                "ingest_text_cache_enabled": settings.ingest_text_cache_enabled,
                "ingest_text_cache_hits": 0,
                "ingest_text_cache_misses": 0,
                "ingest_text_cache_write_count": 0,
                "effective_ingest_workers": 1,
                "source_inventory": {
                    "raw_file_count": selection_plan.current_inventory.raw_file_count,
                    "unique_document_count": selection_plan.current_inventory.unique_document_count,
                    "ignored_duplicate_file_count": (
                        selection_plan.current_inventory.ignored_duplicate_file_count
                    ),
                },
            }
            write_json(ingest_summary_path, ingest_summary_payload)

        return IngestExecutionResult(
            staged_path=existing_staged_path,
            files_scanned=len(selection_plan.all_representative_source_files),
            raw_files_discovered=selection_plan.current_inventory.raw_file_count,
            duplicate_raw_file_count=selection_plan.current_inventory.ignored_duplicate_file_count,
            files_failed=0,
            transactions_parsed=0,
            hsbc_csv_files_scanned=0,
            parser_low_confidence_file_count=0,
            warnings=warnings,
            source_files=tuple(selection_plan.all_representative_source_files),
            selected_source_files=(),
            validations=(),
            parser_selection_diagnostics=(),
            hsbc_merge_metrics={},
            hsbc_period_parse_variant_match_count=0,
            hsbc_boundary_metrics={},
            hsbc_boundary_diagnostics=(),
            hsbc_sign_metrics={},
            hsbc_sign_diagnostics=(),
            hsbc_selection_diagnostics=(),
            ingest_parser_duration_seconds_by_parser={},
            ingest_duration_seconds_by_bank={},
            ingest_text_cache_enabled=settings.ingest_text_cache_enabled,
            ingest_text_cache_hits=0,
            ingest_text_cache_misses=0,
            ingest_text_cache_write_count=0,
            effective_ingest_workers=1,
            newly_covered_months=(),
            ingest_summary_path=ingest_summary_path,
            run_mode="incremental",
            files_selected_for_processing=0,
            files_skipped_already_committed=selection_plan.files_skipped_already_committed,
            files_skipped_modified_existing=0,
            files_missing_since_last_commit=0,
            dataset_stale=False,
            stale_reasons=(),
            staged_batch_manifest_path=existing_manifest_path,
            backup_run=None,
        )

    progress = tqdm(
        total=5,
        desc="Ingest",
        unit="step",
        disable=not sys.stderr.isatty(),
        leave=False,
    )
    progress.set_postfix_str("backup")
    if backup_run is None:
        backup_run = create_stage_backup_run(
            stage="ingest",
            command=backup_command,
            processed_dir=settings.processed_path,
            processed_targets=(settings.staged_transactions_path,),
            config_targets=(
                settings.category_rules_path,
                settings.project_rules_path,
                settings.budget_targets_path,
                settings.account_rules_path,
                settings.project_overrides_path,
                settings.transaction_overrides_path,
            ),
        )
    progress.update()
    progress.set_postfix_str("selection plan")
    progress.update()
    progress.set_postfix_str("parse statements")
    ingest = ingest_workflow_stage(
        settings,
        discover_statement_pdfs=discover_statement_pdfs,
        extract_text_from_pdf=extract_text_from_pdf,
        select_parser_with_diagnostics=select_parser_with_diagnostics,
        source_inventory=selection_plan.current_inventory,
        selected_source_files=selection_plan.selected_source_files,
        run_mode=selection_plan.run_mode,
        files_skipped_already_committed=selection_plan.files_skipped_already_committed,
        files_skipped_modified_existing=len(selection_plan.modified_existing_entries),
        files_missing_since_last_commit=len(selection_plan.missing_committed_entries),
        dataset_stale=selection_plan.dataset_stale,
        stale_reasons=list(selection_plan.stale_reasons),
    )
    progress.update()
    progress.set_postfix_str("diagnostics and stage")
    hsbc_diagnostics = analyze_hsbc_parser_outputs(
        ingest.transactions,
        ingest.validations,
        ingest.hsbc_statement_periods_by_date,
    )
    warnings = [
        *ingest.warnings,
        *hsbc_diagnostics.warnings,
    ]
    staging = write_staged_transactions(settings.staged_transactions_path, ingest.transactions)
    progress.update()
    progress.set_postfix_str("write manifest")
    staged_manifest = build_manifest_from_selection_plan(
        selection_plan=selection_plan,
        source_inventory=selection_plan.current_inventory,
    )
    staged_manifest = replace(
        staged_manifest,
        context={
            "all_source_files": [str(path) for path in ingest.all_source_files],
            "selected_source_files": [str(path) for path in ingest.selected_source_files],
            "files_failed": ingest.files_failed,
            "validations": [
                {
                    "source_file": str(validation.source_file),
                    "bank": validation.bank,
                    "parser": validation.parser,
                    "statement_type": validation.statement_type,
                    "opening_balance": (
                        str(validation.opening_balance)
                        if validation.opening_balance is not None
                        else None
                    ),
                    "closing_balance": (
                        str(validation.closing_balance)
                        if validation.closing_balance is not None
                        else None
                    ),
                    "transaction_sum": (
                        str(validation.transaction_sum)
                        if validation.transaction_sum is not None
                        else None
                    ),
                    "expected_closing_balance": (
                        str(validation.expected_closing_balance)
                        if validation.expected_closing_balance is not None
                        else None
                    ),
                    "difference": (
                        str(validation.difference) if validation.difference is not None else None
                    ),
                    "status": validation.status,
                    "reason": validation.reason,
                    "severity": validation.severity,
                }
                for validation in ingest.validations
            ],
            "parser_selection_diagnostics": ingest.parser_selection_diagnostics,
            "parser_low_confidence_file_count": ingest.parser_low_confidence_file_count,
            "hsbc_csv_files_scanned": ingest.hsbc_csv_files_scanned,
            "hsbc_merge_metrics": hsbc_diagnostics.metrics,
            "hsbc_period_parse_variant_match_count": ingest.hsbc_period_parse_variant_match_count,
            "hsbc_boundary_metrics": ingest.hsbc_boundary_metrics,
            "hsbc_boundary_diagnostics": ingest.hsbc_boundary_diagnostics,
            "hsbc_sign_metrics": ingest.hsbc_sign_metrics,
            "hsbc_sign_diagnostics": ingest.hsbc_sign_diagnostics,
            "hsbc_selection_diagnostics": hsbc_diagnostics.selection_diagnostics,
            "ingest_parser_duration_seconds_by_parser": ingest.parser_duration_seconds_by_parser,
            "ingest_duration_seconds_by_bank": ingest.duration_seconds_by_bank,
            "ingest_text_cache_enabled": ingest.text_cache_enabled,
            "ingest_text_cache_hits": ingest.text_cache_hits,
            "ingest_text_cache_misses": ingest.text_cache_misses,
            "ingest_text_cache_write_count": ingest.text_cache_write_count,
            "effective_ingest_workers": ingest.effective_ingest_workers,
        },
    )
    staged_manifest_path = staged_batch_manifest_path(settings)
    write_staged_batch_manifest(staged_manifest_path, staged_manifest)
    ingest_summary_path: Path | None = None
    if emit_ingest_summary:
        ingest_summary_path = ingest_state_path(settings) / INGEST_SUMMARY_FILENAME
        ingest_summary_payload: dict[str, object] = {
            "generated_at": datetime.now(UTC).isoformat(),
            "stage": "ingest",
            "files_scanned": len(ingest.all_source_files),
            "run_mode": ingest.run_mode,
            "files_selected_for_processing": ingest.files_selected_for_processing,
            "files_skipped_already_committed": ingest.files_skipped_already_committed,
            "files_skipped_modified_existing": ingest.files_skipped_modified_existing,
            "files_missing_since_last_commit": ingest.files_missing_since_last_commit,
            "dataset_stale": ingest.dataset_stale,
            "stale_reasons": list(ingest.stale_reasons),
            "raw_files_discovered": ingest.raw_file_count,
            "duplicate_raw_file_count": ingest.duplicate_raw_file_count,
            "files_failed": ingest.files_failed,
            "transactions_parsed": len(ingest.transactions),
            "newly_covered_months": sorted(
                {tx.booking_date.strftime("%Y-%m") for tx in ingest.transactions}
            ),
            "staged_transactions_path": str(staging.path),
            "staged_batch_manifest_path": str(staged_manifest_path),
            "hsbc_csv_files_scanned": ingest.hsbc_csv_files_scanned,
            "parser_low_confidence_file_count": ingest.parser_low_confidence_file_count,
            "backup_run_id": backup_run.run_id,
            "backup_root": str(backup_run.backup_root) if backup_run.backup_root else None,
            "backup_snapshot_dir": (
                str(backup_run.snapshot_dir) if backup_run.snapshot_dir else None
            ),
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
            "effective_ingest_workers": ingest.effective_ingest_workers,
            "source_inventory": {
                "raw_file_count": selection_plan.current_inventory.raw_file_count,
                "unique_document_count": selection_plan.current_inventory.unique_document_count,
                "ignored_duplicate_file_count": (
                    selection_plan.current_inventory.ignored_duplicate_file_count
                ),
            },
        }
        write_json(ingest_summary_path, ingest_summary_payload)
    progress.update()
    progress.close()

    return IngestExecutionResult(
        staged_path=staging.path,
        files_scanned=len(ingest.all_source_files),
        raw_files_discovered=ingest.raw_file_count,
        duplicate_raw_file_count=ingest.duplicate_raw_file_count,
        files_failed=ingest.files_failed,
        transactions_parsed=len(ingest.transactions),
        hsbc_csv_files_scanned=ingest.hsbc_csv_files_scanned,
        parser_low_confidence_file_count=ingest.parser_low_confidence_file_count,
        warnings=tuple(warnings),
        source_files=tuple(ingest.source_files),
        selected_source_files=tuple(ingest.selected_source_files),
        validations=tuple(ingest.validations),
        parser_selection_diagnostics=tuple(ingest.parser_selection_diagnostics),
        hsbc_merge_metrics=hsbc_diagnostics.metrics,
        hsbc_period_parse_variant_match_count=ingest.hsbc_period_parse_variant_match_count,
        hsbc_boundary_metrics=ingest.hsbc_boundary_metrics,
        hsbc_boundary_diagnostics=tuple(ingest.hsbc_boundary_diagnostics),
        hsbc_sign_metrics=ingest.hsbc_sign_metrics,
        hsbc_sign_diagnostics=tuple(ingest.hsbc_sign_diagnostics),
        hsbc_selection_diagnostics=tuple(hsbc_diagnostics.selection_diagnostics),
        ingest_parser_duration_seconds_by_parser=ingest.parser_duration_seconds_by_parser,
        ingest_duration_seconds_by_bank=ingest.duration_seconds_by_bank,
        ingest_text_cache_enabled=ingest.text_cache_enabled,
        ingest_text_cache_hits=ingest.text_cache_hits,
        ingest_text_cache_misses=ingest.text_cache_misses,
        ingest_text_cache_write_count=ingest.text_cache_write_count,
        effective_ingest_workers=ingest.effective_ingest_workers,
        newly_covered_months=tuple(
            sorted({tx.booking_date.strftime("%Y-%m") for tx in ingest.transactions})
        ),
        ingest_summary_path=ingest_summary_path,
        run_mode=ingest.run_mode,
        files_selected_for_processing=ingest.files_selected_for_processing,
        files_skipped_already_committed=ingest.files_skipped_already_committed,
        files_skipped_modified_existing=ingest.files_skipped_modified_existing,
        files_missing_since_last_commit=ingest.files_missing_since_last_commit,
        dataset_stale=ingest.dataset_stale,
        stale_reasons=ingest.stale_reasons,
        staged_batch_manifest_path=staged_manifest_path,
        backup_run=backup_run,
    )

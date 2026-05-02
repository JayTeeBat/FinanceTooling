"""Combined workflow orchestration across ingest and transform stages."""

from __future__ import annotations

from finance_tooling.core.backup import create_stage_backup_run
from finance_tooling.core.config import Settings
from finance_tooling.core.models import WorkflowResult
from finance_tooling.core.scanner import discover_statement_pdfs
from finance_tooling.core.source_inventory import build_source_inventory
from finance_tooling.workflow.incremental_state import (
    build_incremental_selection_plan,
    load_source_registry,
    source_registry_path,
)
from finance_tooling.workflow.ingest_stage import IngestExecutionResult, run_ingest
from finance_tooling.workflow.planning_stage import run_planning
from finance_tooling.workflow.transform_stage import load_cached_transform_result, run_transform


def _planning_inputs_ready(settings: Settings) -> bool:
    """Return whether canonical transform outputs exist for planning."""
    return settings.master_parquet_path.exists()


def run_update(
    settings: Settings,
    *,
    ingest_only: bool = False,
    transform_only: bool = False,
    full_refresh: bool = False,
    emit_ingest_summary: bool = False,
    skip_planning: bool = False,
) -> WorkflowResult | IngestExecutionResult:
    """Run ingest+transform orchestration with optional stage-only execution."""
    if ingest_only and transform_only:
        raise ValueError("--ingest-only and --transform-only are mutually exclusive.")
    if transform_only and full_refresh:
        raise ValueError("--transform-only cannot be combined with --full-refresh.")

    if transform_only:
        backup_run = create_stage_backup_run(
            stage="update",
            command="update",
            processed_dir=settings.processed_path,
            config_targets=(
                settings.category_rules_path,
                settings.project_rules_path,
                settings.budget_targets_path,
                settings.account_rules_path,
                settings.project_overrides_path,
                settings.transaction_overrides_path,
            ),
        )
        transform_result = run_transform(settings, backup_command="update", backup_run=backup_run)
        if not skip_planning and _planning_inputs_ready(settings):
            run_planning(settings)
        return transform_result

    if not full_refresh:
        registry = load_source_registry(source_registry_path(settings))
        selection_plan = build_incremental_selection_plan(
            settings=settings,
            run_mode="incremental",
            current_inventory=build_source_inventory(discover_statement_pdfs(settings.input_path)),
            registry=registry,
        )
        if not selection_plan.selected_entries and not selection_plan.dataset_stale:
            cached_result = load_cached_transform_result(
                settings,
                transactions_parsed=0,
                new_rows=0,
                warnings=(
                    "No-op update: raw files, staged data, review state, and config are unchanged; "
                    "reused existing outputs.",
                ),
                run_mode="incremental",
                files_selected_for_processing=0,
                files_skipped_already_committed=selection_plan.files_skipped_already_committed,
                files_skipped_modified_existing=0,
                files_missing_since_last_commit=0,
                dataset_stale=False,
                stale_reasons=(),
            )
            if cached_result is not None:
                if not skip_planning and _planning_inputs_ready(settings):
                    run_planning(settings)
                return cached_result
            backup_run = create_stage_backup_run(
                stage="update",
                command="update",
                processed_dir=settings.processed_path,
                config_targets=(
                    settings.category_rules_path,
                    settings.project_rules_path,
                    settings.budget_targets_path,
                    settings.account_rules_path,
                    settings.project_overrides_path,
                    settings.transaction_overrides_path,
                ),
            )
            transform_result = run_transform(
                settings,
                backup_command="update",
                backup_run=backup_run,
            )
            if not skip_planning and _planning_inputs_ready(settings):
                run_planning(settings)
            return transform_result

    backup_run = create_stage_backup_run(
        stage="update",
        command="update",
        processed_dir=settings.processed_path,
        config_targets=(
            settings.category_rules_path,
            settings.project_rules_path,
            settings.budget_targets_path,
            settings.account_rules_path,
            settings.project_overrides_path,
            settings.transaction_overrides_path,
        ),
    )

    ingest_result = run_ingest(
        settings,
        backup_command="update",
        run_mode="full_refresh" if full_refresh else "incremental",
        emit_ingest_summary=emit_ingest_summary,
        backup_run=backup_run,
    )
    if ingest_only:
        return ingest_result

    transform_result = run_transform(
        settings,
        staged_path=ingest_result.staged_path,
        ingest_result=ingest_result,
        backup_command="update",
        backup_run=backup_run,
    )
    if not skip_planning and _planning_inputs_ready(settings):
        run_planning(settings)
    return transform_result


def run_workflow(settings: Settings) -> WorkflowResult:
    """Compatibility wrapper for the combined update workflow."""
    result = run_update(settings)
    if isinstance(result, IngestExecutionResult):
        raise RuntimeError("run_workflow expects a full workflow result, not ingest-only output.")
    return result

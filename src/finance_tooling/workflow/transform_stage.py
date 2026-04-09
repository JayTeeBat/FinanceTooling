"""Transform stage orchestration from staged transactions to final outputs."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

import pandas as pd
from tqdm import tqdm

from finance_tooling.categorization.account_inference import infer_accounts_for_transactions
from finance_tooling.core.backup import BackupRunResult, create_stage_backup_run
from finance_tooling.core.config import HOUSEHOLD_HEALTHCHECK_FILENAME, Settings
from finance_tooling.core.fx import FX_RATE_SEMANTICS_VERSION
from finance_tooling.core.models import WorkflowResult
from finance_tooling.core.source_inventory import load_source_inventory
from finance_tooling.core.store import upsert_transactions
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.reporting.dashboard import render_dashboard_html
from finance_tooling.reporting.household_healthcheck import render_household_healthcheck_html
from finance_tooling.review.state import apply_review_state
from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.incremental_state import (
    build_incremental_selection_plan,
    committed_validations_for_current_inventory,
    compute_config_fingerprint,
    load_source_registry,
    load_staged_batch_manifest,
    resolve_staged_batch_manifest_path,
    source_registry_path,
    update_source_registry,
    write_source_registry,
)
from finance_tooling.workflow.ingest_stage import IngestExecutionResult
from finance_tooling.workflow.reporting import persist_and_report
from finance_tooling.workflow.staging import (
    read_staged_transactions,
    resolve_staged_transactions_path,
)
from finance_tooling.workflow.types import (
    HsbcBoundaryDiagnostic,
    HsbcSelectionDiagnostic,
    HsbcSignDiagnostic,
    ParserSelectionDiagnostic,
)


def _load_previous_summary(summary_path: Path) -> dict[str, object] | None:
    if not summary_path.exists():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _summary_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _summary_float(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key, 0.0)
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0


def _load_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _required_transform_outputs(settings: Settings) -> tuple[Path, ...]:
    outputs = [
        settings.master_parquet_path,
        settings.export_csv_path,
        settings.summary_json_path,
        settings.output_path,
        settings.completeness_json_path,
    ]
    if settings.export_json_enabled:
        outputs.append(settings.export_json_path)
    return tuple(outputs)


def _is_transform_output_current(
    settings: Settings,
    *,
    staged_path: Path,
    manifest_path: Path,
    manifest_config_fingerprint: str,
) -> bool:
    required_outputs = _required_transform_outputs(settings)
    if any(not path.exists() for path in required_outputs):
        return False
    if manifest_config_fingerprint != compute_config_fingerprint(settings):
        return False

    inputs = (
        staged_path,
        manifest_path,
        settings.category_rules_path,
        settings.project_rules_path,
        settings.account_rules_path,
        settings.project_overrides_path,
        settings.transaction_overrides_path,
        settings.review_state_path,
    )
    latest_input_mtime_ns = max(
        (path.stat().st_mtime_ns for path in inputs if path.exists()),
        default=-1,
    )
    earliest_output_mtime_ns = min(path.stat().st_mtime_ns for path in required_outputs)
    if earliest_output_mtime_ns < latest_input_mtime_ns:
        return False
    summary_payload = _load_previous_summary(settings.summary_json_path)
    if summary_payload is None:
        return False
    if _summary_int(summary_payload, "fx_rate_semantics_version") != FX_RATE_SEMANTICS_VERSION:
        return False
    try:
        canonical_columns = set(pd.read_parquet(settings.master_parquet_path).columns)
    except Exception:
        return False
    required_columns = {
        "category_id",
        "reporting_category_id",
        "cashflow_type",
        "economic_role",
        "from_account_ref",
        "to_account_ref",
        "from_account_type",
        "to_account_type",
        "account_inference_source",
    }
    return required_columns.issubset(canonical_columns)


def _workflow_result_from_summary(
    settings: Settings,
    summary_payload: Mapping[str, object],
    *,
    transactions_parsed: int,
    new_rows: int,
    warnings: tuple[str, ...],
    run_mode: str,
    files_selected_for_processing: int,
    files_skipped_already_committed: int,
    files_skipped_modified_existing: int,
    files_missing_since_last_commit: int,
    dataset_stale: bool,
    stale_reasons: tuple[str, ...],
) -> WorkflowResult:
    completeness_payload = _load_json(settings.completeness_json_path) or {}
    completeness_status = str(completeness_payload.get("status", "pass"))
    completeness_coverage_ratio = _summary_float(completeness_payload, "file_coverage_ratio")
    missing_source_file_count = _summary_int(completeness_payload, "missing_source_file_count")
    reconciliation = completeness_payload.get("statement_reconciliation", {})
    if not isinstance(reconciliation, dict):
        reconciliation = {}
    reconciliation_payload = cast(Mapping[str, object], reconciliation)
    return WorkflowResult(
        dashboard_path=settings.output_path,
        parquet_path=settings.master_parquet_path,
        csv_path=settings.export_csv_path,
        json_path=settings.export_json_path,
        summary_path=settings.summary_json_path,
        completeness_path=settings.completeness_json_path,
        files_scanned=_summary_int(summary_payload, "files_scanned"),
        files_failed=0,
        transactions_parsed=transactions_parsed,
        new_rows=new_rows,
        total_rows=_summary_int(summary_payload, "total_rows"),
        completeness_status=completeness_status,
        completeness_coverage_ratio=completeness_coverage_ratio,
        missing_source_file_count=missing_source_file_count,
        reconciliation_checkable_file_count=_summary_int(
            reconciliation_payload, "checkable_file_count"
        ),
        reconciliation_fail_count=_summary_int(reconciliation_payload, "fail_count"),
        reconciliation_uncheckable_file_count=_summary_int(
            reconciliation_payload, "uncheckable_file_count"
        ),
        reconciliation_pass_ratio=_summary_float(reconciliation_payload, "pass_ratio"),
        categorized_count=_summary_int(summary_payload, "categorized_count"),
        uncategorized_count=_summary_int(summary_payload, "uncategorized_count"),
        categorized_amount_eur_abs=_summary_float(summary_payload, "categorized_amount_eur_abs"),
        uncategorized_amount_eur_abs=_summary_float(
            summary_payload, "uncategorized_amount_eur_abs"
        ),
        categorized_amount_eur_abs_ratio=_summary_float(
            summary_payload, "categorized_amount_eur_abs_ratio"
        ),
        uncategorized_amount_eur_abs_ratio=_summary_float(
            summary_payload, "uncategorized_amount_eur_abs_ratio"
        ),
        warnings=warnings,
        categorized_count_delta=0,
        uncategorized_count_delta=0,
        categorized_amount_eur_abs_delta=0.0,
        uncategorized_amount_eur_abs_delta=0.0,
        backup_run=None,
        run_mode=run_mode,
        files_selected_for_processing=files_selected_for_processing,
        files_skipped_already_committed=files_skipped_already_committed,
        files_skipped_modified_existing=files_skipped_modified_existing,
        files_missing_since_last_commit=files_missing_since_last_commit,
        dataset_stale=dataset_stale,
        stale_reasons=stale_reasons,
        household_healthcheck_path=Path(
            str(
                summary_payload.get(
                    "household_healthcheck_path",
                    settings.output_path.parent / HOUSEHOLD_HEALTHCHECK_FILENAME,
                )
            )
        ),
    )


def load_cached_transform_result(
    settings: Settings,
    *,
    staged_path: Path | None = None,
    transactions_parsed: int = 0,
    new_rows: int = 0,
    warnings: tuple[str, ...] = (),
    run_mode: str | None = None,
    files_selected_for_processing: int | None = None,
    files_skipped_already_committed: int | None = None,
    files_skipped_modified_existing: int | None = None,
    files_missing_since_last_commit: int | None = None,
    dataset_stale: bool | None = None,
    stale_reasons: tuple[str, ...] | None = None,
) -> WorkflowResult | None:
    """Return a cached workflow result when current outputs are already up to date."""
    previous_summary = _load_previous_summary(settings.summary_json_path)
    if previous_summary is None:
        return None

    input_staged_path = resolve_staged_transactions_path(settings, staged_path=staged_path)
    manifest_path = resolve_staged_batch_manifest_path(settings)
    manifest = load_staged_batch_manifest(manifest_path)
    if manifest is None:
        return None
    if not _is_transform_output_current(
        settings,
        staged_path=input_staged_path,
        manifest_path=manifest_path,
        manifest_config_fingerprint=manifest.config_fingerprint,
    ):
        return None

    return _workflow_result_from_summary(
        settings,
        previous_summary,
        transactions_parsed=transactions_parsed,
        new_rows=new_rows,
        warnings=warnings,
        run_mode=run_mode or manifest.run_mode,
        files_selected_for_processing=(
            manifest.files_selected_for_processing
            if files_selected_for_processing is None
            else files_selected_for_processing
        ),
        files_skipped_already_committed=(
            manifest.files_skipped_already_committed
            if files_skipped_already_committed is None
            else files_skipped_already_committed
        ),
        files_skipped_modified_existing=(
            manifest.files_skipped_modified_existing
            if files_skipped_modified_existing is None
            else files_skipped_modified_existing
        ),
        files_missing_since_last_commit=(
            manifest.files_missing_since_last_commit
            if files_missing_since_last_commit is None
            else files_missing_since_last_commit
        ),
        dataset_stale=manifest.dataset_stale if dataset_stale is None else dataset_stale,
        stale_reasons=manifest.stale_reasons if stale_reasons is None else stale_reasons,
    )


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


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _deserialize_validation(payload: object) -> StatementValidation | None:
    if not isinstance(payload, dict):
        return None
    payload_dict = cast(dict[str, object], payload)
    transaction_sum_value = payload_dict.get("transaction_sum")
    if transaction_sum_value is None:
        return None
    return StatementValidation(
        source_file=Path(str(payload_dict["source_file"])),
        bank=str(payload_dict["bank"]),
        parser=str(payload_dict["parser"]),
        statement_type=str(payload_dict["statement_type"]),
        opening_balance=_decimal_or_none(payload_dict.get("opening_balance")),
        closing_balance=_decimal_or_none(payload_dict.get("closing_balance")),
        transaction_sum=Decimal(str(transaction_sum_value)),
        expected_closing_balance=_decimal_or_none(payload_dict.get("expected_closing_balance")),
        difference=_decimal_or_none(payload_dict.get("difference")),
        status=str(payload_dict["status"]),
        reason=str(payload_dict["reason"]) if payload_dict.get("reason") is not None else None,
        severity=str(payload_dict["severity"]),
    )


def _manifest_validations(manifest_context: Mapping[str, object]) -> list[StatementValidation]:
    raw_validations = manifest_context.get("validations")
    if not isinstance(raw_validations, list):
        return []
    validations: list[StatementValidation] = []
    for item in raw_validations:
        validation = _deserialize_validation(item)
        if validation is not None:
            validations.append(validation)
    return validations


def _manifest_list(context: Mapping[str, object], key: str) -> list[object]:
    value = context.get(key)
    return cast(list[object], value) if isinstance(value, list) else []


def _manifest_int_dict(context: Mapping[str, object], key: str) -> dict[str, int]:
    value = context.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(item_key): int(item_value)
        for item_key, item_value in value.items()
        if isinstance(item_key, str) and isinstance(item_value, int | float)
    }


def _manifest_float_dict(context: Mapping[str, object], key: str) -> dict[str, float]:
    value = context.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(item_key): float(item_value)
        for item_key, item_value in value.items()
        if isinstance(item_key, str) and isinstance(item_value, int | float)
    }


def _manifest_int(context: Mapping[str, object], key: str, default: int = 0) -> int:
    value = context.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _manifest_bool(context: Mapping[str, object], key: str, default: bool = False) -> bool:
    value = context.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def run_transform(
    settings: Settings,
    *,
    staged_path: Path | None = None,
    ingest_result: IngestExecutionResult | None = None,
    backup_command: str = "transform",
    backup_run: BackupRunResult | None = None,
) -> WorkflowResult:
    """Execute transform stage from staged transaction artifact."""
    cached_result = None
    if ingest_result is None:
        cached_result = load_cached_transform_result(
            settings,
            staged_path=staged_path,
            transactions_parsed=0,
            new_rows=0,
            warnings=(
                "No-op transform: staged data, review state, and config are unchanged; "
                "reused existing outputs.",
            ),
        )
    if cached_result is not None:
        return cached_result

    previous_summary = _load_previous_summary(settings.summary_json_path)
    input_staged_path = resolve_staged_transactions_path(settings, staged_path=staged_path)
    manifest_path = resolve_staged_batch_manifest_path(settings)
    manifest = load_staged_batch_manifest(manifest_path)
    if manifest is None:
        raise RuntimeError(
            "Missing staged batch manifest; run ingest before transform so the staged batch "
            "is self-describing."
        )

    progress = tqdm(
        total=5,
        desc="Transform",
        unit="step",
        disable=not sys.stderr.isatty(),
        leave=False,
    )
    progress.set_postfix_str("backup")
    if backup_run is None:
        try:
            backup_run = create_stage_backup_run(
                stage="transform",
                command=backup_command,
                processed_dir=settings.processed_path,
                processed_targets=(settings.master_parquet_path,),
                config_dir=settings.category_rules_path.parent,
                config_targets=(
                    settings.category_rules_path,
                    settings.project_rules_path,
                    settings.budget_targets_path,
                    settings.account_rules_path,
                    settings.project_overrides_path,
                    settings.transaction_overrides_path,
                ),
            )
        except OSError as exc:
            progress.close()
            raise RuntimeError("Failed to back up transform inputs before transform.") from exc
    progress.update()
    progress.set_postfix_str("load staged batch")
    staged_transactions = read_staged_transactions(input_staged_path)
    progress.update()
    progress.set_postfix_str("enrich")
    enrichment = enrich_transactions(staged_transactions, settings)
    reviewed_transactions = apply_review_state(
        enrichment.transactions,
        settings.review_state_path,
    )
    inferred_transactions = infer_accounts_for_transactions(
        reviewed_transactions,
        config=enrichment.account_inference_config,
    )
    manifest_context = manifest.context
    registry = load_source_registry(source_registry_path(settings))
    inventory = manifest.source_inventory
    if inventory is None and manifest.source_inventory_path is not None:
        inventory = load_source_inventory(Path(manifest.source_inventory_path))
    if inventory is None:
        progress.close()
        raise RuntimeError(
            "Missing source inventory snapshot referenced by the staged batch manifest; "
            "rerun ingest before transform."
        )
    selection_plan = build_incremental_selection_plan(
        settings=settings,
        run_mode=manifest.run_mode,
        current_inventory=inventory,
        registry=registry,
    )

    if ingest_result is not None:
        source_files = list(ingest_result.source_files)
        processed_source_files = list(ingest_result.selected_source_files)
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
        effective_ingest_workers = ingest_result.effective_ingest_workers
        warnings = [
            *ingest_result.warnings,
            *enrichment.warnings,
        ]
        run_mode = ingest_result.run_mode
        files_selected_for_processing = ingest_result.files_selected_for_processing
        files_skipped_already_committed = ingest_result.files_skipped_already_committed
        files_skipped_modified_existing = ingest_result.files_skipped_modified_existing
        files_missing_since_last_commit = ingest_result.files_missing_since_last_commit
        dataset_stale = ingest_result.dataset_stale
        stale_reasons = list(ingest_result.stale_reasons)
    else:
        source_files = selection_plan.all_representative_source_files
        processed_source_files = [Path(path) for path in manifest.selected_source_files]
        files_failed = _manifest_int(manifest_context, "files_failed")
        validations = _manifest_validations(manifest_context)
        parser_selection_diagnostics = cast(
            list[ParserSelectionDiagnostic],
            _manifest_list(manifest_context, "parser_selection_diagnostics"),
        )
        parser_low_confidence_file_count = _manifest_int(
            manifest_context, "parser_low_confidence_file_count"
        )
        hsbc_csv_files_scanned = _manifest_int(manifest_context, "hsbc_csv_files_scanned")
        hsbc_merge_metrics = {
            **_default_hsbc_merge_metrics(),
            **_manifest_int_dict(manifest_context, "hsbc_merge_metrics"),
        }
        hsbc_period_parse_variant_match_count = _manifest_int(
            manifest_context, "hsbc_period_parse_variant_match_count"
        )
        hsbc_boundary_metrics = {
            **_default_hsbc_boundary_metrics(),
            **_manifest_int_dict(manifest_context, "hsbc_boundary_metrics"),
        }
        hsbc_boundary_diagnostics = cast(
            list[HsbcBoundaryDiagnostic],
            _manifest_list(manifest_context, "hsbc_boundary_diagnostics"),
        )
        hsbc_sign_metrics = {
            **_default_hsbc_sign_metrics(),
            **_manifest_int_dict(manifest_context, "hsbc_sign_metrics"),
        }
        hsbc_sign_diagnostics = cast(
            list[HsbcSignDiagnostic],
            _manifest_list(manifest_context, "hsbc_sign_diagnostics"),
        )
        hsbc_selection_diagnostics = cast(
            list[HsbcSelectionDiagnostic],
            _manifest_list(manifest_context, "hsbc_selection_diagnostics"),
        )
        ingest_parser_duration_seconds_by_parser = _manifest_float_dict(
            manifest_context, "ingest_parser_duration_seconds_by_parser"
        )
        ingest_duration_seconds_by_bank = _manifest_float_dict(
            manifest_context, "ingest_duration_seconds_by_bank"
        )
        ingest_text_cache_enabled = _manifest_bool(manifest_context, "ingest_text_cache_enabled")
        ingest_text_cache_hits = _manifest_int(manifest_context, "ingest_text_cache_hits")
        ingest_text_cache_misses = _manifest_int(manifest_context, "ingest_text_cache_misses")
        ingest_text_cache_write_count = _manifest_int(
            manifest_context, "ingest_text_cache_write_count"
        )
        effective_ingest_workers = _manifest_int(manifest_context, "effective_ingest_workers")
        warnings = [*enrichment.warnings]
        run_mode = manifest.run_mode
        files_selected_for_processing = manifest.files_selected_for_processing
        files_skipped_already_committed = manifest.files_skipped_already_committed
        files_skipped_modified_existing = manifest.files_skipped_modified_existing
        files_missing_since_last_commit = manifest.files_missing_since_last_commit
        dataset_stale = manifest.dataset_stale
        stale_reasons = list(manifest.stale_reasons)

    if run_mode == "incremental":
        committed_validations = committed_validations_for_current_inventory(
            registry=registry,
            current_inventory=selection_plan.current_inventory,
        )
        selected_validation_paths = {validation.source_file for validation in validations}
        validations = [
            validation
            for validation in committed_validations
            if validation.source_file not in selected_validation_paths
        ] + validations

    progress.update()
    progress.set_postfix_str("persist outputs")
    result, summary_payload = persist_and_report(
        settings=settings,
        source_files=source_files,
        files_failed=files_failed,
        transactions=inferred_transactions,
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
        effective_ingest_workers=effective_ingest_workers,
        manual_category_carry_forward_applied_count=(
            enrichment.manual_category_carry_forward_applied_count
        ),
        manual_category_carry_forward_ambiguous_skipped_count=(
            enrichment.manual_category_carry_forward_ambiguous_skipped_count
        ),
        manual_category_carry_forward_unmatched_count=(
            enrichment.manual_category_carry_forward_unmatched_count
        ),
        warnings=warnings,
        run_mode=run_mode,
        files_selected_for_processing=files_selected_for_processing,
        files_skipped_already_committed=files_skipped_already_committed,
        files_skipped_modified_existing=files_skipped_modified_existing,
        files_missing_since_last_commit=files_missing_since_last_commit,
        dataset_stale=dataset_stale,
        stale_reasons=stale_reasons,
        backup_run=backup_run,
        classification_rules=enrichment.classification_rules,
        transaction_override_store=enrichment.transaction_override_store,
        account_inference_config=enrichment.account_inference_config,
        upsert_transactions_fn=upsert_transactions,
        render_dashboard_html_fn=render_dashboard_html,
        render_household_healthcheck_html_fn=render_household_healthcheck_html,
    )
    progress.update()
    progress.set_postfix_str("update state")
    next_registry = update_source_registry(
        existing=registry,
        selection_plan=selection_plan,
        processed_source_files=processed_source_files,
        validations=validations,
        transactions=inferred_transactions,
    )
    write_source_registry(source_registry_path(settings), next_registry)
    progress.update()
    progress.close()
    if previous_summary is None:
        return result

    return replace(
        result,
        categorized_count_delta=(
            _summary_int(summary_payload, "categorized_count")
            - _summary_int(previous_summary, "categorized_count")
        ),
        uncategorized_count_delta=(
            _summary_int(summary_payload, "uncategorized_count")
            - _summary_int(previous_summary, "uncategorized_count")
        ),
        categorized_amount_eur_abs_delta=(
            _summary_float(summary_payload, "categorized_amount_eur_abs")
            - _summary_float(previous_summary, "categorized_amount_eur_abs")
        ),
        uncategorized_amount_eur_abs_delta=(
            _summary_float(summary_payload, "uncategorized_amount_eur_abs")
            - _summary_float(previous_summary, "uncategorized_amount_eur_abs")
        ),
    )

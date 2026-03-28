"""Transform stage orchestration from staged transactions to final outputs."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

from tqdm import tqdm

from finance_tooling.backup import create_stage_backup_run
from finance_tooling.config import Settings
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.models import WorkflowResult
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.review_state import apply_review_state
from finance_tooling.source_inventory import load_source_inventory
from finance_tooling.store import upsert_transactions
from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.incremental_state import (
    build_incremental_selection_plan,
    committed_validations_for_current_inventory,
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
) -> WorkflowResult:
    """Execute transform stage from staged transaction artifact."""
    previous_summary = _load_previous_summary(settings.summary_json_path)
    progress = tqdm(
        total=5,
        desc="Transform",
        unit="step",
        disable=not sys.stderr.isatty(),
        leave=False,
    )
    progress.set_postfix_str("backup")
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
                settings.project_overrides_path,
                settings.transaction_overrides_path,
            ),
        )
    except OSError as exc:
        progress.close()
        raise RuntimeError("Failed to back up transform inputs before transform.") from exc
    progress.update()
    progress.set_postfix_str("load staged batch")
    input_staged_path = resolve_staged_transactions_path(settings, staged_path=staged_path)
    manifest = load_staged_batch_manifest(resolve_staged_batch_manifest_path(settings))
    if manifest is None:
        progress.close()
        raise RuntimeError(
            "Missing staged batch manifest; run ingest before transform so the staged batch "
            "is self-describing."
        )
    staged_transactions = read_staged_transactions(input_staged_path)
    progress.update()
    progress.set_postfix_str("enrich")
    enrichment = enrich_transactions(staged_transactions, settings)
    reviewed_transactions = apply_review_state(
        enrichment.transactions,
        settings.review_state_path,
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
        transactions=reviewed_transactions,
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
        upsert_transactions_fn=upsert_transactions,
        render_dashboard_html_fn=render_dashboard_html,
    )
    progress.update()
    progress.set_postfix_str("update state")
    next_registry = update_source_registry(
        existing=registry,
        selection_plan=selection_plan,
        processed_source_files=processed_source_files,
        validations=validations,
        transactions=reviewed_transactions,
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

"""Transform stage orchestration from staged transactions to final outputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from finance_tooling.backup import create_backup
from finance_tooling.config import Settings
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.models import WorkflowResult
from finance_tooling.review_state import apply_review_state
from finance_tooling.store import upsert_transactions
from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.ingest_stage import IngestExecutionResult
from finance_tooling.workflow.reporting import persist_and_report
from finance_tooling.workflow.staging import read_staged_transactions


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


def run_transform(
    settings: Settings,
    *,
    staged_path: Path | None = None,
    ingest_result: IngestExecutionResult | None = None,
) -> WorkflowResult:
    """Execute transform stage from staged transaction artifact."""
    previous_summary = _load_previous_summary(settings.summary_json_path)
    try:
        create_backup(settings.category_rules_path)
    except OSError as exc:
        raise RuntimeError(
            f"Failed to back up category rules before transform: {settings.category_rules_path}"
        ) from exc
    input_staged_path = staged_path or settings.staged_transactions_path
    staged_transactions = read_staged_transactions(input_staged_path)
    enrichment = enrich_transactions(staged_transactions, settings)
    reviewed_transactions = apply_review_state(
        enrichment.transactions,
        settings.review_state_path,
    )

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
        classification_diagnostics=enrichment.classification_diagnostics,
        warnings=warnings,
        upsert_transactions_fn=upsert_transactions,
        render_dashboard_html_fn=render_dashboard_html,
    )
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

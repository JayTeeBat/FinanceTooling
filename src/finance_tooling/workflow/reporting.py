"""Persistence and reporting stage."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pandas import DataFrame

from finance_tooling.classify import ClassificationDiagnostics
from finance_tooling.completeness import build_completeness_report
from finance_tooling.config import Settings
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.models import Transaction, WorkflowResult
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.store import UpsertResult, upsert_transactions
from finance_tooling.workflow.types import (
    HsbcBoundaryDiagnostic,
    HsbcSelectionDiagnostic,
    HsbcSignDiagnostic,
    ParserSelectionDiagnostic,
    SummaryPayload,
)


def write_json(path: Path, payload: dict[str, object] | SummaryPayload) -> None:
    """Write JSON payload with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def persist_and_report(
    *,
    settings: Settings,
    source_files: list[Path],
    files_failed: int,
    transactions: list[Transaction],
    validations: list[StatementValidation],
    parser_selection_diagnostics: list[ParserSelectionDiagnostic],
    parser_low_confidence_file_count: int,
    hsbc_csv_files_scanned: int,
    hsbc_merge_metrics: dict[str, int],
    hsbc_period_parse_variant_match_count: int,
    hsbc_boundary_metrics: dict[str, int],
    hsbc_boundary_diagnostics: list[HsbcBoundaryDiagnostic],
    hsbc_sign_metrics: dict[str, int],
    hsbc_sign_diagnostics: list[HsbcSignDiagnostic],
    hsbc_selection_diagnostics: list[HsbcSelectionDiagnostic],
    ingest_parser_duration_seconds_by_parser: dict[str, float],
    ingest_duration_seconds_by_bank: dict[str, float],
    ingest_text_cache_enabled: bool,
    ingest_text_cache_hits: int,
    ingest_text_cache_misses: int,
    ingest_text_cache_write_count: int,
    classification_diagnostics: ClassificationDiagnostics,
    warnings: list[str],
    upsert_transactions_fn: Callable[[Path, list[Transaction]], UpsertResult] = upsert_transactions,
    render_dashboard_html_fn: Callable[..., Path] = render_dashboard_html,
) -> tuple[WorkflowResult, SummaryPayload]:
    """Persist artifacts and return final workflow result plus summary payload."""
    completeness_report = build_completeness_report(
        source_files,
        transactions,
        validations=validations,
    )
    completeness_status = cast(str, completeness_report["status"])
    completeness_coverage_ratio = cast(float, completeness_report["file_coverage_ratio"])
    missing_source_file_count = cast(int, completeness_report["missing_source_file_count"])
    reconciliation = cast(dict[str, object], completeness_report["statement_reconciliation"])
    reconciliation_checkable_count = cast(int, reconciliation["checkable_file_count"])
    reconciliation_fail_count = cast(int, reconciliation["fail_count"])
    reconciliation_uncheckable_count = cast(int, reconciliation["uncheckable_file_count"])
    reconciliation_pass_ratio = cast(float | None, reconciliation["pass_ratio"])
    reconciliation_median_abs_difference = cast(
        float | None, reconciliation["median_abs_difference"]
    )
    by_bank_abs_difference = cast(list[dict[str, object]], reconciliation["by_bank_abs_difference"])
    hsbc_abs_difference = next(
        (
            cast(float | None, item.get("median_abs_difference"))
            for item in by_bank_abs_difference
            if cast(str, item.get("bank")) == "HSBC"
        ),
        None,
    )

    write_json(settings.completeness_json_path, completeness_report)

    upsert = upsert_transactions_fn(settings.master_parquet_path, transactions)

    settings.export_csv_path.parent.mkdir(parents=True, exist_ok=True)
    settings.export_json_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe: DataFrame = upsert.dataframe
    dataframe.to_csv(settings.export_csv_path, index=False)
    dataframe.to_json(settings.export_json_path, orient="records", indent=2)

    dashboard_path = render_dashboard_html_fn(
        dataframe,
        settings.output_path,
        base_currency=settings.base_currency,
        files_scanned=len(source_files),
        files_failed=files_failed,
        new_rows=upsert.new_rows,
        project_rules_path=settings.project_rules_path,
        budget_targets_path=settings.budget_targets_path,
    )

    category_metrics_by_bank_counters: dict[str, dict[str, int]] = defaultdict(
        lambda: {"transactions_count": 0, "categorized_count": 0, "uncategorized_count": 0}
    )
    for tx in transactions:
        bank = tx.bank.strip() if tx.bank.strip() else "UNKNOWN"
        counters = category_metrics_by_bank_counters[bank]
        counters["transactions_count"] += 1
        is_uncategorized = tx.category.strip().lower() == "uncategorized" or (
            (tx.category_source or "").strip().lower() == "fallback"
        )
        if is_uncategorized:
            counters["uncategorized_count"] += 1
        else:
            counters["categorized_count"] += 1

    category_metrics_by_bank = []
    for bank in sorted(category_metrics_by_bank_counters):
        counters = category_metrics_by_bank_counters[bank]
        total = counters["transactions_count"]
        categorized_pct = (counters["categorized_count"] / total) * 100.0 if total > 0 else 0.0
        uncategorized_pct = (counters["uncategorized_count"] / total) * 100.0 if total > 0 else 0.0
        category_metrics_by_bank.append(
            {
                "bank": bank,
                "transactions_count": total,
                "categorized_count": counters["categorized_count"],
                "uncategorized_count": counters["uncategorized_count"],
                "categorized_pct": round(categorized_pct, 4),
                "uncategorized_pct": round(uncategorized_pct, 4),
            }
        )

    summary_payload: SummaryPayload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "files_scanned": len(source_files),
        "files_failed": files_failed,
        "transactions_parsed": len(transactions),
        "new_rows": upsert.new_rows,
        "total_rows": upsert.total_rows,
        "parquet_path": str(upsert.parquet_path),
        "dashboard_path": str(dashboard_path),
        "completeness_report_path": str(settings.completeness_json_path),
        "completeness_status": completeness_status,
        "file_coverage_ratio": completeness_coverage_ratio,
        "missing_source_file_count": missing_source_file_count,
        "statement_reconciliation_checkable_file_count": reconciliation_checkable_count,
        "statement_reconciliation_fail_count": reconciliation_fail_count,
        "statement_reconciliation_uncheckable_file_count": reconciliation_uncheckable_count,
        "statement_reconciliation_pass_ratio": reconciliation_pass_ratio,
        "statement_reconciliation_median_abs_difference": reconciliation_median_abs_difference,
        "statement_reconciliation_hsbc_median_abs_difference": hsbc_abs_difference,
        "parser_low_confidence_file_count": parser_low_confidence_file_count,
        "parser_selection_diagnostics": parser_selection_diagnostics,
        "hsbc_csv_files_scanned": hsbc_csv_files_scanned,
        "hsbc_csv_statement_replaced_count": hsbc_merge_metrics[
            "hsbc_csv_statement_replaced_count"
        ],
        "hsbc_pdf_fallback_statement_count": hsbc_merge_metrics[
            "hsbc_pdf_fallback_statement_count"
        ],
        "hsbc_csv_only_statement_count": hsbc_merge_metrics["hsbc_csv_only_statement_count"],
        "hsbc_pdf_balance_validated_count": hsbc_merge_metrics["hsbc_pdf_balance_validated_count"],
        "hsbc_pdf_balance_validation_fail_count": hsbc_merge_metrics[
            "hsbc_pdf_balance_validation_fail_count"
        ],
        "hsbc_selection_policy": "pdf_only",
        "hsbc_adaptive_source_switch_count": hsbc_merge_metrics[
            "hsbc_adaptive_source_switch_count"
        ],
        "hsbc_selected_csv_month_count": hsbc_merge_metrics["hsbc_selected_csv_month_count"],
        "hsbc_selected_pdf_month_count": hsbc_merge_metrics["hsbc_selected_pdf_month_count"],
        "hsbc_period_remap_applied_month_count": hsbc_merge_metrics[
            "hsbc_period_remap_applied_month_count"
        ],
        "hsbc_period_remap_reassigned_tx_count": hsbc_merge_metrics[
            "hsbc_period_remap_reassigned_tx_count"
        ],
        "hsbc_period_remap_unassigned_csv_tx_count": hsbc_merge_metrics[
            "hsbc_period_remap_unassigned_csv_tx_count"
        ],
        "hsbc_period_parse_variant_match_count": hsbc_period_parse_variant_match_count,
        "hsbc_boundary_table_start_count": hsbc_boundary_metrics["table_start_count"],
        "hsbc_boundary_table_end_count": hsbc_boundary_metrics["table_end_count"],
        "hsbc_boundary_rows_seen_in_table": hsbc_boundary_metrics["rows_seen_in_table"],
        "hsbc_boundary_rows_rejected_outside_table": hsbc_boundary_metrics[
            "rows_rejected_outside_table"
        ],
        "hsbc_boundary_rows_rejected_after_table": hsbc_boundary_metrics[
            "rows_rejected_after_table"
        ],
        "hsbc_boundary_transition_anomaly_count": hsbc_boundary_metrics["transition_anomaly_count"],
        "hsbc_boundary_diagnostics": hsbc_boundary_diagnostics,
        "hsbc_sign_from_running_balance_count": hsbc_sign_metrics[
            "sign_from_running_balance_count"
        ],
        "hsbc_sign_from_column_position_count": hsbc_sign_metrics[
            "sign_from_column_position_count"
        ],
        "hsbc_sign_from_token_marker_count": hsbc_sign_metrics["sign_from_token_marker_count"],
        "hsbc_sign_from_description_marker_count": hsbc_sign_metrics[
            "sign_from_description_marker_count"
        ],
        "hsbc_sign_from_fallback_hint_count": hsbc_sign_metrics["sign_from_fallback_hint_count"],
        "hsbc_sign_default_debit_count": hsbc_sign_metrics["sign_default_debit_count"],
        "hsbc_sign_conflict_running_vs_marker_count": hsbc_sign_metrics[
            "sign_conflict_running_vs_marker_count"
        ],
        "hsbc_sign_unresolved_ambiguous_count": hsbc_sign_metrics[
            "sign_unresolved_ambiguous_count"
        ],
        "hsbc_sign_diagnostics": hsbc_sign_diagnostics,
        "hsbc_selection_diagnostics": hsbc_selection_diagnostics,
        "ingest_parser_duration_seconds_by_parser": ingest_parser_duration_seconds_by_parser,
        "ingest_duration_seconds_by_bank": ingest_duration_seconds_by_bank,
        "ingest_text_cache_enabled": ingest_text_cache_enabled,
        "ingest_text_cache_hits": ingest_text_cache_hits,
        "ingest_text_cache_misses": ingest_text_cache_misses,
        "ingest_text_cache_write_count": ingest_text_cache_write_count,
        "categorized_count": classification_diagnostics.categorized_count,
        "uncategorized_count": classification_diagnostics.uncategorized_count,
        "uncategorized_ratio": classification_diagnostics.uncategorized_ratio,
        "category_source_counts": classification_diagnostics.category_source_counts,
        "category_metrics_by_bank": category_metrics_by_bank,
        "top_uncategorized_descriptions": (
            classification_diagnostics.top_uncategorized_descriptions
        ),
        "top_rules_by_hits": classification_diagnostics.top_rules_by_hits,
        "category_rules_path": str(settings.category_rules_path),
        "category_overrides_path": str(settings.category_overrides_path),
        "project_rules_path": str(settings.project_rules_path),
        "budget_targets_path": str(settings.budget_targets_path),
        "project_overrides_path": str(settings.project_overrides_path),
        "transaction_overrides_path": str(settings.transaction_overrides_path),
        "fx_cache_path": str(settings.fx_cache_path),
        "warnings": warnings,
    }
    write_json(settings.summary_json_path, summary_payload)

    result = WorkflowResult(
        dashboard_path=dashboard_path,
        parquet_path=upsert.parquet_path,
        csv_path=settings.export_csv_path,
        json_path=settings.export_json_path,
        summary_path=settings.summary_json_path,
        completeness_path=settings.completeness_json_path,
        files_scanned=len(source_files),
        files_failed=files_failed,
        transactions_parsed=len(transactions),
        new_rows=upsert.new_rows,
        total_rows=upsert.total_rows,
        completeness_status=completeness_status,
        completeness_coverage_ratio=completeness_coverage_ratio,
        missing_source_file_count=missing_source_file_count,
        reconciliation_checkable_file_count=reconciliation_checkable_count,
        reconciliation_fail_count=reconciliation_fail_count,
        reconciliation_uncheckable_file_count=reconciliation_uncheckable_count,
        reconciliation_pass_ratio=reconciliation_pass_ratio,
        warnings=tuple(warnings),
    )

    return result, summary_payload

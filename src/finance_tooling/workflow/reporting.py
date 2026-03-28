"""Persistence and reporting stage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pandas as pd
from pandas import DataFrame

from finance_tooling.backup import BackupRunResult
from finance_tooling.classify import ClassificationDiagnostics, normalize_description
from finance_tooling.completeness import build_completeness_report_from_dataframe
from finance_tooling.config import Settings, state_root_path
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.models import Transaction, WorkflowResult
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.store import (
    UpsertResult,
    upsert_transactions,
)
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


def _write_legacy_identity_collision_candidates(
    dataframe: DataFrame,
    output_path: Path,
) -> tuple[int, int]:
    if dataframe.empty:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        DataFrame().to_csv(output_path, index=False)
        return 0, 0

    working = dataframe.reindex(
        columns=[
            "booking_date",
            "description",
            "source_record_index",
            "amount_native",
            "currency",
            "bank",
            "account_label",
            "source_file",
            "parser",
        ]
    ).copy()
    descriptions = working["description"].astype("string").fillna("")
    working["legacy_transaction_id"] = (
        working["booking_date"].astype("string").fillna("")
        + "|"
        + descriptions.map(lambda value: normalize_description(str(value)))
        + "|"
        + working["amount_native"].astype("string").fillna("")
        + "|"
        + working["currency"].astype("string").str.upper().fillna("")
        + "|"
        + working["bank"].astype("string").fillna("")
        + "|"
        + working["account_label"].astype("string").fillna("")
        + "|"
        + working["source_file"].astype("string").fillna("")
    ).map(lambda payload: hashlib.sha256(payload.encode("utf-8")).hexdigest())

    collision_sizes = (
        working.groupby("legacy_transaction_id")["legacy_transaction_id"].transform("size")
    )
    collision_rows = working.loc[collision_sizes > 1].copy()
    if collision_rows.empty:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        DataFrame().to_csv(output_path, index=False)
        return 0, 0

    collision_rows["collision_group_size"] = collision_sizes.loc[collision_rows.index]
    collision_rows["group_row_number"] = (
        collision_rows.groupby("legacy_transaction_id").cumcount() + 1
    )
    rows = collision_rows.loc[
        :,
        [
            "legacy_transaction_id",
            "collision_group_size",
            "group_row_number",
            "booking_date",
            "description",
            "source_record_index",
            "amount_native",
            "currency",
            "bank",
            "account_label",
            "source_file",
            "parser",
        ],
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output_path, index=False)
    return rows["legacy_transaction_id"].nunique(), len(rows)


def _build_classification_diagnostics_from_dataframe(
    dataframe: DataFrame,
) -> ClassificationDiagnostics:
    if dataframe.empty:
        return ClassificationDiagnostics(
            categorized_count=0,
            uncategorized_count=0,
            uncategorized_ratio=0.0,
            category_source_counts={},
            top_uncategorized_descriptions=[],
            top_rules_by_hits=[],
        )

    category_series = (
        dataframe.get("category", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
    )
    category_source_series = (
        dataframe.get("category_source", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
    )
    effective_category_source_series = category_source_series.mask(
        category_source_series.eq("")
        & category_series.str.strip().ne("")
        & category_series.str.strip().str.casefold().ne("uncategorized"),
        "rule",
    )
    category_source_counts = {
        str(index): int(value)
        for index, value in effective_category_source_series.replace("", "unknown")
        .value_counts()
        .items()
    }
    uncategorized_mask = category_series.str.strip().str.casefold().eq("uncategorized") | (
        effective_category_source_series.str.casefold().eq("uncategorized")
    )
    uncategorized_count = int(uncategorized_mask.sum())
    categorized_count = int(len(dataframe) - uncategorized_count)
    uncategorized_ratio = (uncategorized_count / len(dataframe)) if len(dataframe) else 0.0

    uncategorized_descriptions: dict[str, int] = {}
    if uncategorized_count > 0 and "description" in dataframe.columns:
        normalized_descriptions = (
            dataframe.loc[uncategorized_mask, "description"]
            .astype("string")
            .fillna("")
            .map(lambda value: normalize_description(str(value)) or "unknown")
            .value_counts()
        )
        uncategorized_descriptions = {
            str(index): int(value) for index, value in normalized_descriptions.items()
        }
    top_uncategorized = [
        {"description": description, "count": count}
        for description, count in sorted(
            uncategorized_descriptions.items(),
            key=lambda item: (-item[1], item[0]),
        )[:10]
    ]

    top_rules: list[dict[str, object]] = []
    if "category_rule_id" in dataframe.columns:
        rule_hits = (
            dataframe["category_rule_id"]
            .dropna()
            .astype("string")
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
        )
        top_rules = [
            {"rule_id": str(rule_id), "count": int(count)}
            for rule_id, count in sorted(
                ((str(index), int(value)) for index, value in rule_hits.items()),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ]

    return ClassificationDiagnostics(
        categorized_count=categorized_count,
        uncategorized_count=uncategorized_count,
        uncategorized_ratio=uncategorized_ratio,
        category_source_counts=category_source_counts,
        top_uncategorized_descriptions=top_uncategorized,
        top_rules_by_hits=top_rules,
    )


def _build_category_metrics_from_dataframe(
    dataframe: DataFrame,
) -> tuple[list[dict[str, object]], float, float, int]:
    if dataframe.empty:
        return [], 0.0, 0.0, 0

    bank_series = (
        dataframe.get("bank", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
    )
    bank_series = bank_series.replace("", "UNKNOWN")
    category_series = (
        dataframe.get("category", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
    )
    category_source_series = (
        dataframe.get("category_source", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
    )
    reviewed_series = (
        dataframe.get("reviewed", pd.Series(False, index=dataframe.index))
        .fillna(False)
        .astype(bool)
    )
    amount_series = pd.to_numeric(
        dataframe.get("amount_eur", pd.Series(0.0, index=dataframe.index)),
        errors="coerce",
    ).fillna(0.0)
    absolute_amount_series = amount_series.abs()
    uncategorized_mask = category_series.str.casefold().eq("uncategorized") | (
        category_source_series.str.casefold().eq("uncategorized")
    )

    metrics_frame = pd.DataFrame(
        {
            "bank": bank_series,
            "reviewed": reviewed_series,
            "uncategorized": uncategorized_mask,
            "absolute_amount_eur": absolute_amount_series,
        },
        index=dataframe.index,
    )
    metrics_frame["categorized"] = ~metrics_frame["uncategorized"]
    metrics_frame["categorized_amount_eur_abs"] = metrics_frame["absolute_amount_eur"].where(
        metrics_frame["categorized"], 0.0
    )
    metrics_frame["uncategorized_amount_eur_abs"] = metrics_frame["absolute_amount_eur"].where(
        metrics_frame["uncategorized"], 0.0
    )

    grouped = metrics_frame.groupby("bank", sort=True).agg(
        transactions_count=("bank", "size"),
        categorized_count=("categorized", "sum"),
        uncategorized_count=("uncategorized", "sum"),
        reviewed_count=("reviewed", "sum"),
        categorized_amount_eur_abs=("categorized_amount_eur_abs", "sum"),
        uncategorized_amount_eur_abs=("uncategorized_amount_eur_abs", "sum"),
    )

    category_metrics_by_bank: list[dict[str, object]] = []
    for bank, row in grouped.iterrows():
        transactions_count = int(row["transactions_count"])
        categorized_count = int(row["categorized_count"])
        uncategorized_count = int(row["uncategorized_count"])
        reviewed_count = int(row["reviewed_count"])
        categorized_amount_eur_abs = float(row["categorized_amount_eur_abs"])
        uncategorized_amount_eur_abs = float(row["uncategorized_amount_eur_abs"])
        total_bank_amount = categorized_amount_eur_abs + uncategorized_amount_eur_abs
        category_metrics_by_bank.append(
            {
                "bank": str(bank),
                "transactions_count": transactions_count,
                "categorized_count": categorized_count,
                "uncategorized_count": uncategorized_count,
                "categorized_amount_eur_abs": round(categorized_amount_eur_abs, 4),
                "uncategorized_amount_eur_abs": round(uncategorized_amount_eur_abs, 4),
                "reviewed_count": reviewed_count,
                "categorized_pct": round(
                    (categorized_count / transactions_count) * 100.0 if transactions_count else 0.0,
                    4,
                ),
                "uncategorized_pct": round(
                    (uncategorized_count / transactions_count) * 100.0
                    if transactions_count
                    else 0.0,
                    4,
                ),
                "categorized_amount_eur_abs_ratio": round(
                    (categorized_amount_eur_abs / total_bank_amount) * 100.0
                    if total_bank_amount
                    else 0.0,
                    4,
                ),
                "uncategorized_amount_eur_abs_ratio": round(
                    (uncategorized_amount_eur_abs / total_bank_amount) * 100.0
                    if total_bank_amount
                    else 0.0,
                    4,
                ),
                "reviewed_pct": round(
                    (reviewed_count / transactions_count) * 100.0 if transactions_count else 0.0,
                    4,
                ),
            }
        )

    return (
        category_metrics_by_bank,
        float(metrics_frame["categorized_amount_eur_abs"].sum()),
        float(metrics_frame["uncategorized_amount_eur_abs"].sum()),
        int(metrics_frame["reviewed"].sum()),
    )


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
    manual_category_carry_forward_applied_count: int,
    manual_category_carry_forward_ambiguous_skipped_count: int,
    manual_category_carry_forward_unmatched_count: int,
    warnings: list[str],
    run_mode: str = "incremental",
    files_selected_for_processing: int = 0,
    files_skipped_already_committed: int = 0,
    files_skipped_modified_existing: int = 0,
    files_missing_since_last_commit: int = 0,
    dataset_stale: bool = False,
    stale_reasons: list[str] | None = None,
    backup_run: BackupRunResult | None = None,
    upsert_transactions_fn: Callable[[Path, list[Transaction]], UpsertResult] = upsert_transactions,
    render_dashboard_html_fn: Callable[..., Path] = render_dashboard_html,
) -> tuple[WorkflowResult, SummaryPayload]:
    """Persist artifacts and return final workflow result plus summary payload."""
    upsert = upsert_transactions_fn(settings.master_parquet_path, transactions)
    dataframe: DataFrame = upsert.dataframe
    classification_diagnostics: ClassificationDiagnostics = (
        _build_classification_diagnostics_from_dataframe(dataframe)
    )
    completeness_report = build_completeness_report_from_dataframe(
        source_files,
        dataframe,
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

    settings.export_csv_path.parent.mkdir(parents=True, exist_ok=True)
    settings.export_json_path.parent.mkdir(parents=True, exist_ok=True)
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
    collision_candidates_path = (
        settings.summary_json_path.parent / "legacy_identity_collision_candidates.csv"
    )
    legacy_identity_collision_group_count, legacy_identity_collision_row_count = (
        _write_legacy_identity_collision_candidates(dataframe, collision_candidates_path)
    )

    (
        category_metrics_by_bank,
        categorized_amount_eur_abs,
        uncategorized_amount_eur_abs,
        reviewed_count,
    ) = _build_category_metrics_from_dataframe(dataframe)
    total_amount_eur_abs = categorized_amount_eur_abs + uncategorized_amount_eur_abs
    reviewed_ratio = (reviewed_count / len(dataframe)) if len(dataframe) else 0.0
    categorized_amount_eur_abs_ratio = (
        (categorized_amount_eur_abs / total_amount_eur_abs) if total_amount_eur_abs > 0 else 0.0
    )
    uncategorized_amount_eur_abs_ratio = (
        (uncategorized_amount_eur_abs / total_amount_eur_abs) if total_amount_eur_abs > 0 else 0.0
    )

    summary_payload: SummaryPayload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "files_scanned": len(source_files),
        "files_failed": files_failed,
        "transactions_parsed": len(dataframe),
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
        "categorized_amount_eur_abs": round(categorized_amount_eur_abs, 4),
        "uncategorized_amount_eur_abs": round(uncategorized_amount_eur_abs, 4),
        "total_amount_eur_abs": round(total_amount_eur_abs, 4),
        "categorized_amount_eur_abs_ratio": round(categorized_amount_eur_abs_ratio, 4),
        "uncategorized_amount_eur_abs_ratio": round(uncategorized_amount_eur_abs_ratio, 4),
        "reviewed_count": reviewed_count,
        "reviewed_ratio": reviewed_ratio,
        "manual_category_carry_forward_applied_count": (
            manual_category_carry_forward_applied_count
        ),
        "manual_category_carry_forward_ambiguous_skipped_count": (
            manual_category_carry_forward_ambiguous_skipped_count
        ),
        "manual_category_carry_forward_unmatched_count": (
            manual_category_carry_forward_unmatched_count
        ),
        "legacy_identity_collision_group_count": legacy_identity_collision_group_count,
        "legacy_identity_collision_row_count": legacy_identity_collision_row_count,
        "legacy_identity_collision_candidates_path": str(collision_candidates_path),
        "category_source_counts": classification_diagnostics.category_source_counts,
        "category_metrics_by_bank": category_metrics_by_bank,
        "top_uncategorized_descriptions": (
            classification_diagnostics.top_uncategorized_descriptions
        ),
        "top_rules_by_hits": classification_diagnostics.top_rules_by_hits,
        "category_rules_path": str(settings.category_rules_path),
        "project_rules_path": str(settings.project_rules_path),
        "budget_targets_path": str(settings.budget_targets_path),
        "project_overrides_path": str(settings.project_overrides_path),
        "transaction_overrides_path": str(settings.transaction_overrides_path),
        "review_state_path": str(settings.review_state_path),
        "fx_cache_path": str(settings.fx_cache_path),
        "source_inventory_path": str(state_root_path(settings) / "workflow_source_inventory.json"),
        "backup_run_id": backup_run.run_id if backup_run is not None else None,
        "backup_processed_dir": (
            str(backup_run.processed_backup_dir)
            if backup_run is not None and backup_run.processed_backup_dir is not None
            else None
        ),
        "backup_config_dir": (
            str(backup_run.config_backup_dir)
            if backup_run is not None and backup_run.config_backup_dir is not None
            else None
        ),
        "backup_manifest_paths": (
            [str(path) for path in backup_run.manifest_paths] if backup_run is not None else []
        ),
        "backup_copied_file_count": len(backup_run.copied_files) if backup_run is not None else 0,
        "backup_missing_file_count": (
            len(backup_run.skipped_missing_files) if backup_run is not None else 0
        ),
        "backup_pruned_run_ids": list(backup_run.pruned_run_ids) if backup_run is not None else [],
        "run_mode": run_mode,
        "files_selected_for_processing": files_selected_for_processing,
        "files_skipped_already_committed": files_skipped_already_committed,
        "files_skipped_modified_existing": files_skipped_modified_existing,
        "files_missing_since_last_commit": files_missing_since_last_commit,
        "dataset_stale": dataset_stale,
        "stale_reasons": stale_reasons or [],
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
        transactions_parsed=len(dataframe),
        new_rows=upsert.new_rows,
        total_rows=upsert.total_rows,
        completeness_status=completeness_status,
        completeness_coverage_ratio=completeness_coverage_ratio,
        missing_source_file_count=missing_source_file_count,
        reconciliation_checkable_file_count=reconciliation_checkable_count,
        reconciliation_fail_count=reconciliation_fail_count,
        reconciliation_uncheckable_file_count=reconciliation_uncheckable_count,
        reconciliation_pass_ratio=reconciliation_pass_ratio,
        categorized_count=classification_diagnostics.categorized_count,
        uncategorized_count=classification_diagnostics.uncategorized_count,
        categorized_amount_eur_abs=round(categorized_amount_eur_abs, 4),
        uncategorized_amount_eur_abs=round(uncategorized_amount_eur_abs, 4),
        categorized_amount_eur_abs_ratio=round(categorized_amount_eur_abs_ratio, 4),
        uncategorized_amount_eur_abs_ratio=round(uncategorized_amount_eur_abs_ratio, 4),
        warnings=tuple(warnings),
        backup_run=backup_run,
        run_mode=run_mode,
        files_selected_for_processing=files_selected_for_processing,
        files_skipped_already_committed=files_skipped_already_committed,
        files_skipped_modified_existing=files_skipped_modified_existing,
        files_missing_since_last_commit=files_missing_since_last_commit,
        dataset_stale=dataset_stale,
        stale_reasons=tuple(stale_reasons or []),
    )

    return result, summary_payload

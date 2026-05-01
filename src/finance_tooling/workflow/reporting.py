"""Persistence and reporting stage."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pandas as pd
from pandas import DataFrame

from finance_tooling.categorization.account_inference import AccountInferenceConfig
from finance_tooling.categorization.category_normalization import (
    normalize_categories_for_dataframe,
    write_categorization_consolidation_delta,
)
from finance_tooling.categorization.classify import (
    ClassificationDiagnostics,
    ClassificationRules,
    TopRuleHitSummary,
    UncategorizedDescriptionSummary,
    normalize_description,
    resolve_reporting_categories_for_dataframe,
)
from finance_tooling.categorization.transaction_overrides import TransactionOverrideStore
from finance_tooling.core.backup import BackupRunResult
from finance_tooling.core.config import HOUSEHOLD_HEALTHCHECK_FILENAME, Settings
from finance_tooling.core.fx import FX_RATE_SEMANTICS_VERSION
from finance_tooling.core.models import Transaction, WorkflowResult
from finance_tooling.core.store import (
    UpsertResult,
    upsert_transactions,
    write_canonical_dataframe,
)
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.reporting.cashflow import (
    build_cashflow_yoy_summary,
    resolve_cashflow_types_for_dataframe,
    resolve_decision_roles_for_dataframe,
    resolve_economic_roles_for_dataframe,
)
from finance_tooling.reporting.completeness import build_completeness_report_from_dataframe
from finance_tooling.reporting.dashboard import render_dashboard_html
from finance_tooling.reporting.household_healthcheck import render_household_healthcheck_html
from finance_tooling.workflow.enrichment import recompute_dataframe_fx
from finance_tooling.workflow.incremental_state import compute_config_fingerprint
from finance_tooling.workflow.types import (
    CategoryMetricByBankRow,
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


def _remove_if_exists(path: Path) -> None:
    """Best-effort removal for optional artifacts disabled in the current run."""
    try:
        path.unlink()
    except FileNotFoundError:
        return


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
    top_uncategorized: list[UncategorizedDescriptionSummary] = [
        {"description": description, "count": count}
        for description, count in sorted(
            uncategorized_descriptions.items(),
            key=lambda item: (-item[1], item[0]),
        )[:10]
    ]

    top_rules: list[TopRuleHitSummary] = []
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
) -> tuple[list[CategoryMetricByBankRow], float, float, float, int]:
    if dataframe.empty:
        return [], 0.0, 0.0, 0.0, 0

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
    subcategory_series = (
        dataframe.get("subcategory", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
    )
    economic_role_series = (
        dataframe.get("economic_role", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    economic_role_series = economic_role_series.mask(
        economic_role_series.eq(""),
        pd.Series("expense", index=dataframe.index, dtype="string"),
    )
    cashflow_type_series = (
        dataframe.get("cashflow_type", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    economic_role_series = economic_role_series.mask(
        economic_role_series.eq("expense") & cashflow_type_series.eq("out"),
        "variable_expense",
    )
    economic_role_series = economic_role_series.mask(
        category_series.str.casefold().eq("income")
        | subcategory_series.str.casefold().isin({"salary", "interest"}),
        "income",
    )
    economic_role_series = economic_role_series.mask(
        category_series.str.casefold().eq("transfers"),
        "transfer",
    )
    economic_role_series = economic_role_series.mask(
        category_series.str.casefold().isin(
            {"non personal transactions", "pass-through", "excluded"}
        ),
        "exclude",
    )
    income_mask = economic_role_series.eq("income") & amount_series.gt(0)
    absolute_amount_series = amount_series.abs()
    uncategorized_mask = category_series.str.casefold().eq("uncategorized") | (
        category_source_series.str.casefold().eq("uncategorized")
    )

    metrics_frame = pd.DataFrame(
        {
            "bank": bank_series,
            "reviewed": reviewed_series,
            "uncategorized": uncategorized_mask,
            "income_amount_eur": amount_series.where(income_mask, 0.0),
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
        income_amount_eur=("income_amount_eur", "sum"),
        categorized_amount_eur_abs=("categorized_amount_eur_abs", "sum"),
        uncategorized_amount_eur_abs=("uncategorized_amount_eur_abs", "sum"),
    )

    category_metrics_by_bank: list[CategoryMetricByBankRow] = []
    for bank, row in grouped.iterrows():
        transactions_count = int(row["transactions_count"])
        categorized_count = int(row["categorized_count"])
        uncategorized_count = int(row["uncategorized_count"])
        reviewed_count = int(row["reviewed_count"])
        income_amount_eur = float(row["income_amount_eur"])
        categorized_amount_eur_abs = float(row["categorized_amount_eur_abs"])
        uncategorized_amount_eur_abs = float(row["uncategorized_amount_eur_abs"])
        category_metrics_by_bank.append(
            {
                "bank": str(bank),
                "transactions_count": transactions_count,
                "categorized_count": categorized_count,
                "uncategorized_count": uncategorized_count,
                "income_amount_eur": round(income_amount_eur, 4),
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
                    (categorized_amount_eur_abs / income_amount_eur) * 100.0
                    if income_amount_eur
                    else 0.0,
                    4,
                ),
                "uncategorized_amount_eur_abs_ratio": round(
                    (uncategorized_amount_eur_abs / income_amount_eur) * 100.0
                    if income_amount_eur
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
        float(metrics_frame["income_amount_eur"].sum()),
        float(metrics_frame["categorized_amount_eur_abs"].sum()),
        float(metrics_frame["uncategorized_amount_eur_abs"].sum()),
        int(metrics_frame["reviewed"].sum()),
    )


def _build_exclude_metrics_from_dataframe(
    dataframe: DataFrame,
) -> tuple[int, float, list[str]]:
    if dataframe.empty:
        return 0, 0.0, []

    cashflow_type_series = (
        dataframe.get("cashflow_type", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    exclude_mask = cashflow_type_series.eq("exclude")
    exclude_count = int(exclude_mask.sum())
    if exclude_count == 0:
        return 0, 0.0, []

    amount_series = pd.to_numeric(
        dataframe.get("amount_eur", pd.Series(0.0, index=dataframe.index)),
        errors="coerce",
    ).fillna(0.0)
    category_series = (
        dataframe.get("category", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
    )
    exclude_categories = sorted(
        {
            str(category).strip() or "Uncategorized"
            for category in category_series.loc[exclude_mask].tolist()
        }
    )
    return exclude_count, float(amount_series.loc[exclude_mask].abs().sum()), exclude_categories


def _build_account_inference_metrics_from_dataframe(
    dataframe: DataFrame,
) -> tuple[int, int, dict[str, int]]:
    if dataframe.empty:
        return 0, 0, {}

    from_type = (
        dataframe.get("from_account_type", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    to_type = (
        dataframe.get("to_account_type", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    source = (
        dataframe.get(
            "account_inference_source", pd.Series("", index=dataframe.index, dtype="object")
        )
        .astype("string")
        .fillna("")
        .str.strip()
        .replace("", "unknown")
    )
    unknown_from = from_type.eq("unknown") | from_type.eq("")
    unknown_to = to_type.eq("unknown") | to_type.eq("")
    unknown_transaction = unknown_from | unknown_to
    source_counts = {str(index): int(value) for index, value in source.value_counts().items()}
    return (
        int(unknown_transaction.sum()),
        int(unknown_from.sum() + unknown_to.sum()),
        source_counts,
    )


def _build_economic_role_metrics_from_dataframe(dataframe: DataFrame) -> dict[str, int]:
    if dataframe.empty:
        return {
            "income": 0,
            "fixed_expense": 0,
            "variable_expense": 0,
            "expense": 0,
            "transfer": 0,
            "exclude": 0,
        }

    role_series = (
        dataframe.get("economic_role", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    return {
        role: int(role_series.eq(role).sum())
        for role in (
            "income",
            "fixed_expense",
            "variable_expense",
            "expense",
            "transfer",
            "exclude",
        )
    }


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
    effective_ingest_workers: int,
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
    classification_rules: ClassificationRules,
    transaction_override_store: TransactionOverrideStore,
    account_inference_config: AccountInferenceConfig,
    upsert_transactions_fn: Callable[[Path, list[Transaction]], UpsertResult] = upsert_transactions,
    render_dashboard_html_fn: Callable[..., Path] = render_dashboard_html,
    render_household_healthcheck_html_fn: Callable[..., Path] = render_household_healthcheck_html,
) -> tuple[WorkflowResult, SummaryPayload]:
    """Persist artifacts and return final workflow result plus summary payload."""
    upsert = upsert_transactions_fn(settings.master_parquet_path, transactions)
    dataframe, fx_warnings = recompute_dataframe_fx(upsert.dataframe, settings)
    warnings = [*warnings, *fx_warnings]
    dataframe = resolve_reporting_categories_for_dataframe(
        dataframe,
        rules=classification_rules,
    )
    normalization = normalize_categories_for_dataframe(
        dataframe,
        rules=classification_rules,
    )
    dataframe = normalization.dataframe
    if normalization.changed_row_count > 0:
        warnings.append(
            "Applied category normalization to "
            f"{normalization.changed_row_count} canonical rows "
            f"({normalization.changed_category_count} category changes, "
            f"{normalization.changed_subcategory_count} subcategory changes)."
        )
    cashflow_resolution = resolve_cashflow_types_for_dataframe(
        dataframe,
        classification_rules=classification_rules,
        transaction_override_store=transaction_override_store,
    )
    economic_role_resolution = resolve_economic_roles_for_dataframe(
        cashflow_resolution.dataframe,
        account_inference_config=account_inference_config,
        classification_rules=classification_rules,
    )
    decision_role_resolution = resolve_decision_roles_for_dataframe(
        economic_role_resolution.dataframe,
        classification_rules=classification_rules,
    )
    dataframe = decision_role_resolution.dataframe
    write_canonical_dataframe(settings.master_parquet_path, dataframe)
    write_categorization_consolidation_delta(
        settings=settings,
        current_dataframe=dataframe,
    )
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

    write_json(settings.completeness_json_path, completeness_report)

    settings.export_csv_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(settings.export_csv_path, index=False)
    if settings.export_json_enabled:
        settings.export_json_path.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_json(settings.export_json_path, orient="records", indent=2)
    else:
        _remove_if_exists(settings.export_json_path)

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
    household_healthcheck_path = render_household_healthcheck_html_fn(
        dataframe,
        settings.output_path.parent / HOUSEHOLD_HEALTHCHECK_FILENAME,
        base_currency=settings.base_currency,
    )
    _remove_if_exists(settings.output_path.parent / "legacy_identity_collision_candidates.csv")

    (
        category_metrics_by_bank,
        total_income_eur,
        categorized_amount_eur_abs,
        uncategorized_amount_eur_abs,
        reviewed_count,
    ) = _build_category_metrics_from_dataframe(dataframe)
    exclude_count, exclude_amount_eur_abs, exclude_categories = (
        _build_exclude_metrics_from_dataframe(dataframe)
    )
    (
        account_boundary_unknown_count,
        account_boundary_unknown_side_count,
        account_inference_source_counts,
    ) = _build_account_inference_metrics_from_dataframe(dataframe)
    economic_role_counts = _build_economic_role_metrics_from_dataframe(dataframe)
    total_amount_eur_abs = categorized_amount_eur_abs + uncategorized_amount_eur_abs
    reviewed_ratio = (reviewed_count / len(dataframe)) if len(dataframe) else 0.0
    categorized_amount_eur_abs_ratio = (
        (categorized_amount_eur_abs / total_income_eur) if total_income_eur > 0 else 0.0
    )
    uncategorized_amount_eur_abs_ratio = (
        (uncategorized_amount_eur_abs / total_income_eur) if total_income_eur > 0 else 0.0
    )

    cashflow_yoy = build_cashflow_yoy_summary(dataframe)

    summary_payload: SummaryPayload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "files_scanned": len(source_files),
        "files_failed": files_failed,
        "transactions_parsed": len(dataframe),
        "new_rows": upsert.new_rows,
        "total_rows": upsert.total_rows,
        "parquet_path": str(upsert.parquet_path),
        "dashboard_path": str(dashboard_path),
        "household_healthcheck_path": str(household_healthcheck_path),
        "completeness_report_path": str(settings.completeness_json_path),
        "categorized_count": classification_diagnostics.categorized_count,
        "uncategorized_count": classification_diagnostics.uncategorized_count,
        "uncategorized_ratio": classification_diagnostics.uncategorized_ratio,
        "categorized_amount_eur_abs": round(categorized_amount_eur_abs, 4),
        "uncategorized_amount_eur_abs": round(uncategorized_amount_eur_abs, 4),
        "total_amount_eur_abs": round(total_amount_eur_abs, 4),
        "total_income_eur": round(total_income_eur, 4),
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
        "category_source_counts": classification_diagnostics.category_source_counts,
        "category_metrics_by_bank": category_metrics_by_bank,
        "top_uncategorized_descriptions": (
            classification_diagnostics.top_uncategorized_descriptions
        ),
        "top_rules_by_hits": classification_diagnostics.top_rules_by_hits,
        "category_rules_path": str(settings.category_rules_path),
        "project_rules_path": str(settings.project_rules_path),
        "budget_targets_path": str(settings.budget_targets_path),
        "account_rules_path": str(settings.account_rules_path),
        "project_overrides_path": str(settings.project_overrides_path),
        "transaction_overrides_path": str(settings.transaction_overrides_path),
        "review_state_path": str(settings.review_state_path),
        "transform_config_fingerprint": compute_config_fingerprint(settings),
        "fx_rate_semantics_version": FX_RATE_SEMANTICS_VERSION,
        "cashflow_type_unknown_count": cashflow_resolution.unknown_count,
        "cashflow_type_unknown_categories": cashflow_resolution.unknown_categories,
        "exclude_count": exclude_count,
        "exclude_amount_eur_abs": round(exclude_amount_eur_abs, 4),
        "exclude_categories": exclude_categories,
        "economic_role_counts": economic_role_counts,
        "account_transfer_override_count": cashflow_resolution.account_transfer_override_count,
        "account_transfer_conflict_count": cashflow_resolution.account_transfer_conflict_count,
        "account_boundary_unknown_count": account_boundary_unknown_count,
        "account_boundary_unknown_side_count": account_boundary_unknown_side_count,
        "account_inference_source_counts": account_inference_source_counts,
        "cashflow_yoy": cashflow_yoy,
        "backup_run_id": backup_run.run_id if backup_run is not None else None,
        "backup_root": (
            str(backup_run.backup_root) if backup_run and backup_run.backup_root else None
        ),
        "backup_snapshot_dir": (
            str(backup_run.snapshot_dir) if backup_run and backup_run.snapshot_dir else None
        ),
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
        household_healthcheck_path=household_healthcheck_path,
    )

    return result, summary_payload

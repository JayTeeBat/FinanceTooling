"""Shared helpers for CLI command modules."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from finance_tooling.core.backup import BackupRunResult
from finance_tooling.core.config import (
    PIPELINE_OUTPUTS_DIRNAME,
    TRANSFORM_TRANSACTIONS_CSV_FILENAME,
    Settings,
    load_settings_from_env,
    resolve_transform_artifact_path,
)
from finance_tooling.core.models import WorkflowResult
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.workflow.incremental_state import FullRefreshPreflight
from finance_tooling.workflow.ingest_stage import IngestExecutionResult
from finance_tooling.workflow.planning_stage import PlanningExecutionResult

DEFAULT_REVIEW_WORKBOOK_FILENAME = "transactions_review.xlsx"
LEGACY_REVIEW_CSV_FILENAME = "transactions_review.csv"


def try_load_settings_for_defaults() -> Settings | None:
    """Return settings when env-backed defaults are available."""
    try:
        return load_settings_from_env()
    except ValueError:
        return None


def processed_dir_from_settings(settings: Settings) -> Path:
    """Return the processed directory derived from settings."""
    processed_path = getattr(settings, "processed_path", None)
    if processed_path is not None:
        return Path(processed_path)
    summary_json_path = getattr(settings, "summary_json_path", None)
    if summary_json_path is not None:
        parent = Path(summary_json_path).parent
        return parent.parent if parent.name == PIPELINE_OUTPUTS_DIRNAME else parent
    raise AttributeError("settings must define processed_path or summary_json_path")


def infer_data_adjacent_config_dir(review_path: Path) -> Path:
    """Infer the data-adjacent config directory from a review file path."""
    return review_path.expanduser().resolve().parent.parent / "config"


def resolve_review_export_paths(
    normalized_path: Path | None,
    output_path: Path | None,
) -> tuple[Path, Path, Path | None, bool]:
    """Resolve canonical CSV input and the standard review workbook path."""
    if normalized_path is not None and output_path is not None:
        settings = try_load_settings_for_defaults()
        review_state_path = (
            getattr(settings, "review_state_path", None) if settings is not None else None
        )
        dark_safe = (
            getattr(settings, "review_export_dark_safe", True) if settings is not None else True
        )
        return normalized_path, output_path, review_state_path, dark_safe

    settings = try_load_settings_for_defaults()
    if settings is None:
        missing_flags: list[str] = []
        if normalized_path is None:
            missing_flags.append("--normalized-path")
        if output_path is None:
            missing_flags.append("--output-path")
        joined = ", ".join(missing_flags)
        raise ValueError(
            f"Missing {joined}; provide explicit flags or configure .env "
            "with FINANCE_STATEMENTS_PATH and FINANCE_PROCESSED_PATH."
        )

    processed_dir = processed_dir_from_settings(settings)
    default_normalized_path = getattr(
        settings,
        "export_csv_path",
        processed_dir / PIPELINE_OUTPUTS_DIRNAME / TRANSFORM_TRANSACTIONS_CSV_FILENAME,
    )
    default_normalized_path = resolve_transform_artifact_path(settings, default_normalized_path)
    return (
        normalized_path or default_normalized_path,
        output_path or (processed_dir / DEFAULT_REVIEW_WORKBOOK_FILENAME),
        getattr(settings, "review_state_path", None),
        getattr(settings, "review_export_dark_safe", True),
    )


def resolve_review_import_paths(
    review_path: Path | None,
    transaction_overrides_path: Path | None,
) -> tuple[Path, Path, Path | None]:
    """Resolve review-import paths using the standard workbook and compatibility fallbacks."""
    settings = try_load_settings_for_defaults()
    settings_transaction_overrides = (
        getattr(settings, "transaction_overrides_path", None) if settings is not None else None
    )

    review_config_dir: Path | None = None
    if review_path is not None:
        review_config_dir = infer_data_adjacent_config_dir(review_path)

    resolved_transaction_overrides = transaction_overrides_path or settings_transaction_overrides
    if resolved_transaction_overrides is None and review_config_dir is not None:
        resolved_transaction_overrides = review_config_dir / "transaction_overrides.yaml"

    if review_path is not None:
        if resolved_transaction_overrides is None:
            raise ValueError(
                "Missing --transaction-overrides-path; provide explicit "
                "paths or configure .env with FINANCE_STATEMENTS_PATH and "
                "FINANCE_PROCESSED_PATH."
            )
        review_state_path = (
            getattr(settings, "review_state_path", None) if settings is not None else None
        )
        return review_path, resolved_transaction_overrides, review_state_path

    if settings is None:
        raise ValueError(
            "Missing --review-path; provide explicit path or configure .env "
            "with FINANCE_STATEMENTS_PATH and FINANCE_PROCESSED_PATH."
        )
    if resolved_transaction_overrides is None:
        raise ValueError(
            "Unable to resolve transaction override path; provide "
            "--transaction-overrides-path explicitly."
        )

    processed_dir = processed_dir_from_settings(settings)
    default_review_xlsx = processed_dir / DEFAULT_REVIEW_WORKBOOK_FILENAME
    default_review_csv = processed_dir / LEGACY_REVIEW_CSV_FILENAME
    if default_review_xlsx.exists():
        resolved_review_path = default_review_xlsx
    elif default_review_csv.exists():
        resolved_review_path = default_review_csv
    else:
        resolved_review_path = default_review_xlsx
    return (
        resolved_review_path,
        resolved_transaction_overrides,
        getattr(settings, "review_state_path", None),
    )


def print_backup_run(result: BackupRunResult) -> None:
    """Print backup metadata without filesystem paths."""
    print(f"Backup run: {result.run_id} ({result.stage} via {result.command})")
    print(f"Backup copied files: {len(result.copied_files)}")
    print(f"Backup missing files skipped: {len(result.skipped_missing_files)}")
    if result.pruned_run_ids:
        print(f"Backup pruned runs: {', '.join(result.pruned_run_ids)}")


def print_selection_summary(
    *,
    run_mode: str,
    files_selected_for_processing: int,
    files_skipped_already_committed: int,
    files_skipped_modified_existing: int,
    files_missing_since_last_commit: int,
    dataset_stale: bool,
    stale_reasons: tuple[str, ...] | list[str],
) -> None:
    """Print a compact selection and stale-state summary."""
    print(
        "Selection: "
        f"mode={run_mode}, "
        f"selected={files_selected_for_processing}, "
        f"already_committed={files_skipped_already_committed}, "
        f"modified={files_skipped_modified_existing}, "
        f"missing={files_missing_since_last_commit}"
    )
    if dataset_stale:
        print(f"Drift: stale ({', '.join(stale_reasons)})")
    else:
        print("Drift: clean")


def _format_reason_counts(reasons: list[str]) -> str:
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return ", ".join(f"{reason} x{count}" for reason, count in sorted(counts.items()))


def _print_reconciliation_summary(
    validations: tuple[StatementValidation, ...], *, verbose: bool
) -> None:
    """Print concise reconciliation results for newly ingested statements."""
    statement_validations = [
        validation for validation in validations if validation.statement_type == "statement"
    ]
    if not statement_validations:
        print("Reconciliation: no new statement validations")
        return

    pass_count = sum(1 for validation in statement_validations if validation.status == "pass")
    fail_validations = [
        validation for validation in statement_validations if validation.status == "fail"
    ]
    fail_count = len(fail_validations)
    uncheckable_count = sum(
        1 for validation in statement_validations if validation.status == "uncheckable"
    )

    print(f"Reconciliation: {pass_count} pass, {fail_count} fail, {uncheckable_count} uncheckable")
    if not fail_validations:
        return

    reasons = [validation.reason or "unknown" for validation in fail_validations]
    differences = [
        abs(validation.difference)
        for validation in fail_validations
        if validation.difference is not None
    ]
    detail = f"Failure reasons: {_format_reason_counts(reasons)}"
    if differences:
        total_gap = sum(differences, start=Decimal("0"))
        detail += f"; abs EUR gap {total_gap:.2f}"
    print(detail)
    if verbose:
        for validation in fail_validations:
            if validation.difference is None:
                print(f"- fail: {validation.reason or 'unknown'}")
            else:
                print(
                    f"- fail: {validation.reason or 'unknown'} "
                    f"(abs EUR gap {abs(validation.difference):.2f})"
                )


def print_incremental_run_metadata(
    *,
    run_mode: str,
    files_selected_for_processing: int,
    files_skipped_already_committed: int,
    files_skipped_modified_existing: int,
    files_missing_since_last_commit: int,
    dataset_stale: bool,
    stale_reasons: tuple[str, ...] | list[str],
) -> None:
    """Print detailed run-mode and stale-state metadata for pipeline stages."""
    print(f"Run mode: {run_mode}")
    print(f"Files selected for processing: {files_selected_for_processing}")
    print(f"Files skipped already committed: {files_skipped_already_committed}")
    print(f"Files skipped modified existing: {files_skipped_modified_existing}")
    print(f"Files missing since last commit: {files_missing_since_last_commit}")
    print(f"Dataset stale: {dataset_stale}")
    if stale_reasons:
        print(f"Stale reasons: {', '.join(stale_reasons)}")


def print_full_refresh_preflight(preflight: FullRefreshPreflight, *, verbose: bool = False) -> None:
    """Print the destructive-impact summary for a guarded full refresh."""
    print("FULL REFRESH WARNING")
    print(f"Full refresh risk: {preflight.full_refresh_risk}")
    print(
        "Impact: "
        f"{preflight.raw_file_count} raw files, "
        f"{preflight.committed_source_count} committed documents, "
        f"{preflight.estimated_reprocessed_row_count} rows to rebuild, "
        f"{preflight.estimated_pruned_row_count} rows to prune"
    )
    if preflight.stale_reasons:
        print(f"Risk reasons: {', '.join(preflight.stale_reasons)}")
    if verbose:
        print("This can remove canonical data for source files no longer present in raw inputs.")
        print("This can reclassify historical transactions under current config.")
        print("Use --dry-run first to inspect impact before executing.")
        print("Automatic backups will still be created before any mutation.")
        print(f"Raw files discovered: {preflight.raw_file_count}")
        print(f"Unique source documents: {preflight.unique_document_count}")
        print(f"Modified committed files: {preflight.modified_committed_count}")
        print(f"Missing committed files: {preflight.missing_committed_count}")
        print(f"Config drift since last full refresh: {preflight.config_drift}")
    print(
        "To proceed, rerun with: "
        f"--full-refresh --confirm-full-refresh {preflight.confirmation_token}"
    )


def print_workflow_result(result: WorkflowResult, *, verbose: bool = False) -> int:
    """Print workflow result summary and return process exit code."""
    total_categorization_count = result.categorized_count + result.uncategorized_count
    categorized_count_ratio = (
        result.categorized_count / total_categorization_count if total_categorization_count else 0.0
    )
    uncategorized_count_ratio = (
        result.uncategorized_count / total_categorization_count
        if total_categorization_count
        else 0.0
    )

    print(f"Transactions: {result.total_rows} total")
    print(
        "Uncategorized exposure: "
        f"{result.uncategorized_count} transactions "
        f"({uncategorized_count_ratio * 100.0:.2f}%), "
        f"EUR {result.uncategorized_amount_eur_abs:.2f} "
        f"({result.uncategorized_amount_eur_abs_ratio * 100.0:.2f}% of Income)"
    )
    if (
        result.uncategorized_count_delta is None
        or result.uncategorized_amount_eur_abs_delta is None
    ):
        print("Uncategorized delta: n/a")
    else:
        print(
            "Uncategorized delta: "
            f"{result.uncategorized_count_delta:+d} transactions, "
            f"EUR {result.uncategorized_amount_eur_abs_delta:+.2f}"
        )
    if verbose:
        print_selection_summary(
            run_mode=result.run_mode,
            files_selected_for_processing=result.files_selected_for_processing,
            files_skipped_already_committed=result.files_skipped_already_committed,
            files_skipped_modified_existing=result.files_skipped_modified_existing,
            files_missing_since_last_commit=result.files_missing_since_last_commit,
            dataset_stale=result.dataset_stale,
            stale_reasons=result.stale_reasons,
        )
        print(f"Scanned files: {result.files_scanned}")
        print_incremental_run_metadata(
            run_mode=result.run_mode,
            files_selected_for_processing=result.files_selected_for_processing,
            files_skipped_already_committed=result.files_skipped_already_committed,
            files_skipped_modified_existing=result.files_skipped_modified_existing,
            files_missing_since_last_commit=result.files_missing_since_last_commit,
            dataset_stale=result.dataset_stale,
            stale_reasons=result.stale_reasons,
        )
        print(f"Failed files: {result.files_failed}")
        print(
            "Completeness: "
            f"{result.completeness_status} "
            f"(coverage={result.completeness_coverage_ratio:.3f}, "
            f"missing_files={result.missing_source_file_count})"
        )
        pass_ratio = (
            f"{result.reconciliation_pass_ratio:.3f}"
            if result.reconciliation_pass_ratio is not None
            else "n/a"
        )
        print(
            "Reconciliation: "
            f"{result.reconciliation_fail_count} failed / "
            f"{result.reconciliation_checkable_file_count} checkable, "
            f"{result.reconciliation_uncheckable_file_count} info "
            f"(pass_ratio={pass_ratio})"
        )
        print(
            "Categorization: "
            f"{result.uncategorized_count} uncategorized / "
            f"{result.categorized_count} categorized "
            f"(abs EUR uncategorized={result.uncategorized_amount_eur_abs:.2f}, "
            f"categorized={result.categorized_amount_eur_abs:.2f})"
        )
        print(
            "Categorization by transaction count: "
            f"{uncategorized_count_ratio * 100.0:.2f}% uncategorized / "
            f"{categorized_count_ratio * 100.0:.2f}% categorized"
        )
        print(
            "Categorization by EUR amount vs Income: "
            f"{result.uncategorized_amount_eur_abs_ratio * 100.0:.2f}% uncategorized / "
            f"{result.categorized_amount_eur_abs_ratio * 100.0:.2f}% categorized"
        )
        if (
            result.categorized_count_delta is not None
            and result.uncategorized_count_delta is not None
        ):
            print(
                "Count delta since last run: "
                f"uncategorized {result.uncategorized_count_delta:+d}, "
                f"categorized {result.categorized_count_delta:+d}"
            )
        if (
            result.categorized_amount_eur_abs_delta is not None
            and result.uncategorized_amount_eur_abs_delta is not None
        ):
            print(
                "EUR delta since last run: "
                f"uncategorized {result.uncategorized_amount_eur_abs_delta:+.2f}, "
                f"categorized {result.categorized_amount_eur_abs_delta:+.2f}"
            )
        if result.backup_run is not None:
            print_backup_run(result.backup_run)

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    if result.transactions_parsed == 0 and result.total_rows == 0:
        return 2
    return 0


def print_planning_result(result: PlanningExecutionResult, *, verbose: bool = False) -> int:
    """Print planning stage summary and return process exit code."""
    print(f"Planning ledger: {result.ledger_rows} rows")
    print(f"Budget status: {result.budget_status_rows} rows")
    if verbose:
        print(f"Input transactions: {result.input_transactions_path}")
        print(f"Ledger parquet: {result.ledger_path}")
        print(f"Ledger CSV: {result.ledger_csv_path}")
        print(f"KPI summary: {result.kpi_summary_path}")
        print(f"Budget status CSV: {result.budget_status_path}")
        print(f"Planning dashboard: {result.dashboard_path}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    return 0


def print_ingest_result(result: IngestExecutionResult, *, verbose: bool = False) -> int:
    """Print ingest stage summary and return process exit code."""
    print(f"Run mode: {result.run_mode}")
    print(
        "Statements: "
        f"{result.files_skipped_already_committed} preexisting, "
        f"{result.files_selected_for_processing} new"
    )
    if result.newly_covered_months:
        print(f"New coverage months: {', '.join(result.newly_covered_months)}")
    else:
        print("New coverage months: none")
    print(f"New transactions: {result.transactions_parsed}")
    _print_reconciliation_summary(result.validations, verbose=verbose)
    if result.dataset_stale:
        print(f"Drift: {', '.join(result.stale_reasons)}")
    elif verbose:
        print("Drift: clean")
    if verbose:
        print_selection_summary(
            run_mode=result.run_mode,
            files_selected_for_processing=result.files_selected_for_processing,
            files_skipped_already_committed=result.files_skipped_already_committed,
            files_skipped_modified_existing=result.files_skipped_modified_existing,
            files_missing_since_last_commit=result.files_missing_since_last_commit,
            dataset_stale=result.dataset_stale,
            stale_reasons=result.stale_reasons,
        )
        print(
            "Sources: "
            f"{result.raw_files_discovered} discovered, "
            f"{result.duplicate_raw_file_count} ignored duplicates, "
            f"{result.files_failed} failed"
        )
        print(f"Scanned files: {result.files_scanned}")
        print_incremental_run_metadata(
            run_mode=result.run_mode,
            files_selected_for_processing=result.files_selected_for_processing,
            files_skipped_already_committed=result.files_skipped_already_committed,
            files_skipped_modified_existing=result.files_skipped_modified_existing,
            files_missing_since_last_commit=result.files_missing_since_last_commit,
            dataset_stale=result.dataset_stale,
            stale_reasons=result.stale_reasons,
        )
        print(f"HSBC CSV files scanned: {result.hsbc_csv_files_scanned}")
        print(f"Parser low-confidence files: {result.parser_low_confidence_file_count}")
        if result.ingest_summary_path is not None:
            print("Ingest summary: written")
        if result.backup_run is not None:
            print_backup_run(result.backup_run)

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    if result.files_scanned == 0 and result.transactions_parsed == 0:
        return 2
    return 0

"""Shared helpers for CLI command modules."""

from __future__ import annotations

from pathlib import Path

from finance_tooling.config import Settings, load_settings_from_env
from finance_tooling.models import WorkflowResult
from finance_tooling.workflow.ingest_stage import IngestExecutionResult


def try_load_settings_for_defaults() -> Settings | None:
    """Return settings when env-backed defaults are available."""
    try:
        return load_settings_from_env()
    except ValueError:
        return None


def processed_dir_from_settings(settings: Settings) -> Path:
    """Return the processed directory derived from settings."""
    return settings.summary_json_path.parent


def infer_data_adjacent_config_dir(review_path: Path) -> Path:
    """Infer the data-adjacent config directory from a review file path."""
    return review_path.expanduser().resolve().parent.parent / "config"


def resolve_review_export_paths(
    normalized_path: Path | None,
    output_path: Path | None,
) -> tuple[Path, Path, Path | None, bool]:
    """Resolve normalized and review output paths using settings defaults when possible."""
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
    return (
        normalized_path or (processed_dir / "transactions_normalized.csv"),
        output_path or (processed_dir / "transactions_review.xlsx"),
        getattr(settings, "review_state_path", None),
        getattr(settings, "review_export_dark_safe", True),
    )


def resolve_review_import_paths(
    review_path: Path | None,
    transaction_overrides_path: Path | None,
) -> tuple[Path, Path, Path | None]:
    """Resolve review-import paths using settings or review-file-adjacent defaults."""
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
    default_review_xlsx = processed_dir / "transactions_review.xlsx"
    default_review_csv = processed_dir / "transactions_review.csv"
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


def print_workflow_result(result: WorkflowResult) -> int:
    """Print workflow result summary and return process exit code."""
    print(f"Scanned files: {result.files_scanned}")
    print(f"Failed files: {result.files_failed}")
    print(f"Parsed transactions: {result.transactions_parsed}")
    print(f"Inserted rows: {result.new_rows}")
    print(f"Total rows in parquet: {result.total_rows}")
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
        f"{result.categorized_count} categorized / "
        f"{result.uncategorized_count} uncategorized "
        f"(abs EUR categorized={result.categorized_amount_eur_abs:.2f}, "
        f"uncategorized={result.uncategorized_amount_eur_abs:.2f})"
    )
    print(
        "Categorization coverage by absolute EUR amount: "
        f"{result.categorized_amount_eur_abs_ratio * 100.0:.2f}% categorized / "
        f"{result.uncategorized_amount_eur_abs_ratio * 100.0:.2f}% uncategorized"
    )
    if (
        result.categorized_count_delta is None
        or result.uncategorized_count_delta is None
        or result.categorized_amount_eur_abs_delta is None
        or result.uncategorized_amount_eur_abs_delta is None
    ):
        print("Delta since last run: n/a")
    else:
        print(
            "Delta since last run: "
            f"categorized {result.categorized_count_delta:+d}, "
            f"uncategorized {result.uncategorized_count_delta:+d}"
        )
        print(
            "Delta abs EUR: "
            f"categorized {result.categorized_amount_eur_abs_delta:+.2f}, "
            f"uncategorized {result.uncategorized_amount_eur_abs_delta:+.2f}"
        )
    print(f"Dashboard: {result.dashboard_path}")
    print(f"Parquet: {result.parquet_path}")
    print(f"CSV export: {result.csv_path}")
    print(f"JSON export: {result.json_path}")
    print(f"Summary: {result.summary_path}")
    print(f"Completeness report: {result.completeness_path}")

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    if result.transactions_parsed == 0 and result.total_rows == 0:
        return 2
    return 0


def print_ingest_result(result: IngestExecutionResult) -> int:
    """Print ingest stage summary and return process exit code."""
    print(f"Scanned files: {result.files_scanned}")
    print(f"Raw files discovered: {result.raw_files_discovered}")
    print(f"Ignored duplicate raw files: {result.duplicate_raw_file_count}")
    print(f"Failed files: {result.files_failed}")
    print(f"Staged transactions: {result.transactions_parsed}")
    print(f"Staged parquet: {result.staged_path}")
    print(f"Ingest summary: {result.ingest_summary_path}")
    print(f"Source inventory: {result.source_inventory_path}")
    print(f"HSBC CSV files scanned: {result.hsbc_csv_files_scanned}")
    print(f"Parser low-confidence files: {result.parser_low_confidence_file_count}")

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    if result.files_scanned == 0 and result.transactions_parsed == 0:
        return 2
    return 0

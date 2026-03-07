"""Shared helpers for CLI command modules."""

from __future__ import annotations

from finance_tooling.models import WorkflowResult
from finance_tooling.workflow.ingest_stage import IngestExecutionResult


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
    print(f"Failed files: {result.files_failed}")
    print(f"Staged transactions: {result.transactions_parsed}")
    print(f"Staged parquet: {result.staged_path}")
    print(f"Ingest summary: {result.ingest_summary_path}")
    print(f"HSBC CSV files scanned: {result.hsbc_csv_files_scanned}")
    print(f"Parser low-confidence files: {result.parser_low_confidence_file_count}")

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    if result.files_scanned == 0 and result.transactions_parsed == 0:
        return 2
    return 0

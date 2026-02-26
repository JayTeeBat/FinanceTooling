"""CLI entrypoint for finance_tooling."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.categorization_review import (
    export_fallback_review_rows,
    import_review_into_overrides,
)
from finance_tooling.classify import load_override_store
from finance_tooling.config import load_settings_from_env
from finance_tooling.pipeline import run_workflow


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m finance_tooling",
        description="Finance tooling workflow and categorization review utilities.",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run the statement processing workflow.")
    run_parser.set_defaults(command="run")

    review_export = subparsers.add_parser(
        "review-export",
        help="Export fallback categorization rows for manual review.",
    )
    review_export.add_argument(
        "--normalized-path",
        type=Path,
        required=True,
        help="Path to normalized transactions table (.csv/.json/.parquet).",
    )
    review_export.add_argument(
        "--output-path",
        type=Path,
        required=True,
        help="Destination review file (.csv or .json).",
    )

    review_import = subparsers.add_parser(
        "review-import",
        help="Import reviewed categories and upsert overrides.",
    )
    review_import.add_argument(
        "--review-path",
        type=Path,
        required=True,
        help="Reviewed categorization file (.csv/.json/.parquet).",
    )
    review_import.add_argument(
        "--overrides-path",
        type=Path,
        default=Path("config/category_overrides.yaml"),
        help="Override config destination (.yaml/.yml/.json).",
    )
    review_import.add_argument(
        "--include-account-label-scope",
        action="store_true",
        help="Use normalized fingerprint + bank + account_label as upsert key.",
    )

    return parser


def _run_workflow_command() -> int:
    try:
        settings = load_settings_from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    result = run_workflow(settings)
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


def main(argv: list[str] | None = None) -> int:
    """Run workflow or categorization review subcommands."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"

    if command == "run":
        return _run_workflow_command()

    if command == "review-export":
        exported = export_fallback_review_rows(args.normalized_path, args.output_path)
        print(f"Exported {exported} fallback review rows to {args.output_path}")
        return 0

    if command == "review-import":
        overrides, warnings = load_override_store(args.overrides_path)
        if warnings:
            for warning in warnings:
                print(f"Warning: {warning}")
        result = import_review_into_overrides(
            review_path=args.review_path,
            overrides_path=args.overrides_path,
            existing_store=overrides,
            include_account_label_scope=args.include_account_label_scope,
        )
        print(f"Imported rows: {result.rows_read}")
        print(f"Overrides upserted: {result.overrides_upserted}")
        print(f"Updated: {result.overrides_updated}")
        print(f"Inserted: {result.overrides_inserted}")
        print(f"Skipped rows: {result.rows_skipped}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

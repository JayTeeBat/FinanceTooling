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
from finance_tooling.metrics_log import (
    build_bank_snapshots,
    build_snapshot,
    upsert_bank_snapshots,
    upsert_snapshot,
)
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

    metrics_log = subparsers.add_parser(
        "metrics-log-update",
        help="Append or update commit-level percentage metrics from run_summary.json.",
    )
    metrics_log.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="Path to run_summary.json (defaults to settings summary path when env is configured).",
    )
    metrics_log.add_argument(
        "--log-path",
        type=Path,
        default=Path("docs/metrics_commit_log.csv"),
        help="Destination overall metrics CSV path.",
    )
    metrics_log.add_argument(
        "--log-path-by-bank",
        type=Path,
        default=Path("docs/metrics_commit_log_by_bank.csv"),
        help="Destination per-bank metrics CSV path.",
    )
    metrics_log.add_argument(
        "--commit",
        type=str,
        default=None,
        help="Optional commit hash override (defaults to current git HEAD short hash).",
    )
    metrics_log.add_argument(
        "--branch",
        type=str,
        default=None,
        help="Optional branch override (defaults to current git branch).",
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

    if command == "metrics-log-update":
        summary_path = args.summary_path
        if summary_path is None:
            try:
                settings = load_settings_from_env()
                summary_path = settings.summary_json_path
            except ValueError:
                print(
                    "Configuration error: provide --summary-path "
                    "or configure env so settings can be loaded."
                )
                return 1
        if not summary_path.exists():
            print(f"Summary file not found: {summary_path}")
            return 1

        snapshot = build_snapshot(summary_path, commit=args.commit, branch=args.branch)
        total_rows, replaced = upsert_snapshot(args.log_path, snapshot)
        bank_snapshots = build_bank_snapshots(
            summary_path,
            commit=snapshot.commit,
            branch=snapshot.branch,
        )
        bank_rows, bank_replaced = upsert_bank_snapshots(args.log_path_by_bank, bank_snapshots)
        action = "updated" if replaced else "appended"
        bank_action = "updated" if bank_replaced else "appended"
        reconciliation_pct = (
            f"{snapshot.reconciliation_pass_pct:.2f}%"
            if snapshot.reconciliation_pass_pct is not None
            else "n/a"
        )
        print(f"Metrics log {action} for commit {snapshot.commit}: {args.log_path}")
        print(f"- parsing_success_pct: {snapshot.parsing_success_pct:.2f}%")
        print(f"- categorized_pct: {snapshot.categorized_pct:.2f}%")
        print(f"- uncategorized_pct: {snapshot.uncategorized_pct:.2f}%")
        print(f"- reconciliation_pass_pct: {reconciliation_pct}")
        print(f"- rows in log: {total_rows}")
        print(
            f"Per-bank metrics log {bank_action} for commit "
            f"{snapshot.commit}: {args.log_path_by_bank}"
        )
        print(f"- bank rows for commit: {bank_rows}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

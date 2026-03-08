"""CLI command for review-import."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.classify import load_override_store
from finance_tooling.commands.common import print_workflow_result, resolve_review_import_paths
from finance_tooling.config import load_settings_from_env
from finance_tooling.review_import import import_review_into_overrides
from finance_tooling.transaction_overrides import load_transaction_override_store
from finance_tooling.workflow.transform_stage import run_transform


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register review-import-specific CLI arguments."""
    parser.add_argument(
        "--review-path",
        type=Path,
        default=None,
        help="Reviewed categorization file (.xlsx/.csv/.json/.parquet).",
    )
    parser.add_argument(
        "--overrides-path",
        type=Path,
        default=None,
        help="Override config destination (.yaml/.yml/.json).",
    )
    parser.add_argument(
        "--transaction-overrides-path",
        type=Path,
        default=None,
        help="Transaction override destination (.yaml/.yml/.json).",
    )
    parser.add_argument(
        "--include-account-label-scope",
        action="store_true",
        help="Use normalized fingerprint + bank + account_label as upsert key.",
    )
    parser.add_argument(
        "--allow-load-warnings",
        action="store_true",
        help="Proceed even when existing override file fails to parse cleanly.",
    )
    parser.add_argument(
        "--allow-non-fallback-import",
        action="store_true",
        help="Import rows whose category_source is not fallback.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview import/upsert counts without writing override files.",
    )
    parser.add_argument(
        "--backup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create a timestamped backup before writing overrides (default: enabled).",
    )
    parser.add_argument(
        "--backup-path",
        type=Path,
        default=None,
        help="Optional explicit backup destination path.",
    )
    parser.add_argument(
        "--run-transform",
        action="store_true",
        help="Run transform after a successful non-dry-run import.",
    )
    parser.set_defaults(command="review-import", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the review-import command from parsed CLI arguments."""
    try:
        if args.dry_run and args.run_transform:
            raise ValueError("--run-transform cannot be used together with --dry-run.")
        review_path, overrides_path, transaction_overrides_path, review_state_path = (
            resolve_review_import_paths(
                args.review_path,
                args.overrides_path,
                args.transaction_overrides_path,
            )
        )
        overrides, warnings = load_override_store(overrides_path)
        transaction_overrides, transaction_warnings = load_transaction_override_store(
            transaction_overrides_path
        )
        has_warnings = bool(warnings or transaction_warnings)
        if has_warnings and not args.allow_load_warnings:
            for warning in warnings:
                print(f"Warning: {warning}")
            for warning in transaction_warnings:
                print(f"Warning: {warning}")
            print(
                "Review import error: override load warnings detected; "
                "fix the override file or rerun with --allow-load-warnings."
            )
            return 1
        if has_warnings:
            for warning in warnings:
                print(f"Warning: {warning}")
            for warning in transaction_warnings:
                print(f"Warning: {warning}")
        result = import_review_into_overrides(
            review_path=review_path,
            overrides_path=overrides_path,
            existing_store=overrides,
            transaction_overrides_path=transaction_overrides_path,
            existing_transaction_store=transaction_overrides,
            include_account_label_scope=args.include_account_label_scope,
            allow_non_fallback_import=bool(args.allow_non_fallback_import),
            dry_run=bool(args.dry_run),
            backup=bool(args.backup),
            backup_path=args.backup_path,
            review_state_path=review_state_path,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Review import error: {exc}")
        return 1
    print(f"Imported rows: {result.rows_read}")
    print(f"Overrides upserted: {result.overrides_upserted}")
    print(f"Updated: {result.overrides_updated}")
    print(f"Inserted: {result.overrides_inserted}")
    print(f"Transaction overrides upserted: {result.transaction_overrides_upserted}")
    print(f"Transaction updated: {result.transaction_overrides_updated}")
    print(f"Transaction inserted: {result.transaction_overrides_inserted}")
    print(f"Project tags applied: {result.project_tags_applied}")
    print(f"Review state upserted: {result.review_state_upserted}")
    print(f"Review state updated: {result.review_state_updated}")
    print(f"Review state inserted: {result.review_state_inserted}")
    print(f"Skipped rows: {result.rows_skipped}")
    print(f"Skipped non-fallback rows: {result.rows_skipped_non_fallback}")
    print(f"Skipped invalid rows: {result.rows_skipped_invalid}")
    print(f"Skipped invalid category rows: {result.rows_skipped_invalid_category}")
    print(f"Skipped invalid project rows: {result.rows_skipped_invalid_project_tags}")
    print(f"Skipped invalid review-state rows: {result.rows_skipped_invalid_review_state}")
    if args.dry_run:
        print("Dry run: no override file was written.")
    else:
        if result.backup_path is not None:
            print(f"Category backup: {result.backup_path}")
        if result.transaction_backup_path is not None:
            print(f"Transaction backup: {result.transaction_backup_path}")
        if args.run_transform:
            try:
                settings = load_settings_from_env()
                workflow_result = run_transform(settings)
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                print(f"Transform error after review import: {exc}")
                return 1
            return print_workflow_result(workflow_result)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for review-import."""
    parser = argparse.ArgumentParser(
        prog="review-import",
        description="Import reviewed categories and upsert overrides.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

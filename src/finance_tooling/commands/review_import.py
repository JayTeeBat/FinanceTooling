"""CLI command for review-import."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.commands.common import print_workflow_result, resolve_review_import_paths
from finance_tooling.config import load_settings_from_env
from finance_tooling.review_import import ReviewImportResult, import_review_into_overrides
from finance_tooling.transaction_overrides import load_transaction_override_store
from finance_tooling.workflow.transform_stage import run_transform


def print_review_import_result(result: ReviewImportResult, *, dry_run: bool, verbose: bool) -> None:
    """Print concise or verbose review-import results."""
    print(
        "Review import: "
        f"read {result.rows_read} rows, "
        f"upserted {result.transaction_overrides_upserted} overrides, "
        f"skipped {result.rows_skipped} rows."
    )
    if result.project_tags_applied:
        print(f"Project tags applied: {result.project_tags_applied}")
    if result.review_state_upserted:
        print(f"Review state updated: {result.review_state_upserted}")
    if result.rows_skipped_invalid:
        print(f"Invalid rows skipped: {result.rows_skipped_invalid}")
    if verbose:
        print(f"Transaction overrides upserted: {result.transaction_overrides_upserted}")
        print(f"Transaction updated: {result.transaction_overrides_updated}")
        print(f"Transaction inserted: {result.transaction_overrides_inserted}")
        print(f"Project tags applied: {result.project_tags_applied}")
        print(f"Review state upserted: {result.review_state_upserted}")
        print(f"Review state updated: {result.review_state_updated}")
        print(f"Review state inserted: {result.review_state_inserted}")
        print(f"Skipped rows: {result.rows_skipped}")
        print(f"Skipped invalid rows: {result.rows_skipped_invalid}")
        print(f"Skipped invalid category rows: {result.rows_skipped_invalid_category}")
        print(f"Skipped invalid project rows: {result.rows_skipped_invalid_project_tags}")
        print(f"Skipped invalid review-state rows: {result.rows_skipped_invalid_review_state}")
    if dry_run:
        print("Dry run: no override file was written.")


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register review-import-specific CLI arguments."""
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed import counters and follow-up workflow details.",
    )
    parser.add_argument(
        "--review-path",
        type=Path,
        default=None,
        help="Reviewed categorization file (.xlsx/.csv/.json/.parquet).",
    )
    parser.add_argument(
        "--transaction-overrides-path",
        type=Path,
        default=None,
        help="Transaction override destination (.yaml/.yml/.json).",
    )
    parser.add_argument(
        "--allow-load-warnings",
        action="store_true",
        help="Proceed even when existing override file fails to parse cleanly.",
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
        help=(
            "Create a pre-run snapshot backup before writing overrides "
            "(default: enabled, stored under the data backup/ folder)."
        ),
    )
    parser.add_argument(
        "--run-transform",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run transform after a successful import (default: enabled).",
    )
    parser.set_defaults(command="review-import", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the review-import command from parsed CLI arguments."""
    try:
        settings = load_settings_from_env()
        review_path, transaction_overrides_path, review_state_path = resolve_review_import_paths(
            args.review_path,
            args.transaction_overrides_path,
        )
        transaction_overrides, transaction_warnings = load_transaction_override_store(
            transaction_overrides_path
        )
        has_warnings = bool(transaction_warnings)
        if has_warnings and not args.allow_load_warnings:
            for warning in transaction_warnings:
                print(f"Warning: {warning}")
            print(
                "Review import error: override load warnings detected; "
                "fix the override file or rerun with --allow-load-warnings."
            )
            return 1
        if has_warnings:
            for warning in transaction_warnings:
                print(f"Warning: {warning}")
        result = import_review_into_overrides(
            review_path=review_path,
            transaction_overrides_path=transaction_overrides_path,
            existing_transaction_store=transaction_overrides,
            dry_run=bool(args.dry_run),
            backup=bool(args.backup),
            review_state_path=review_state_path,
            category_rules_path=getattr(settings, "category_rules_path", None),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Review import error: {exc}")
        return 1
    print_review_import_result(result, dry_run=bool(args.dry_run), verbose=bool(args.verbose))
    if not args.dry_run:
        if result.backup_run is not None:
            print("Backup snapshot: created")
        if args.run_transform:
            try:
                workflow_result = run_transform(
                    settings,
                    backup_command="review-import",
                    backup_run=result.backup_run,
                )
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                print(f"Transform error after review import: {exc}")
                return 1
            return print_workflow_result(workflow_result, verbose=bool(args.verbose))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for review-import."""
    parser = argparse.ArgumentParser(
        prog="review-import",
        description="Import reviewed categories and upsert transaction overrides.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

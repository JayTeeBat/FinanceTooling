"""CLI command for migrating transaction-id keyed manual state."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.commands.common import (
    processed_dir_from_settings,
    try_load_settings_for_defaults,
)
from finance_tooling.maintenance.migrate_transaction_ids import migrate_transaction_ids


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register migrate-transaction-ids-specific CLI arguments."""
    parser.add_argument(
        "--staged-path",
        type=Path,
        default=None,
        help="Fresh staged transaction parquet generated after rerunning ingest.",
    )
    parser.add_argument(
        "--transaction-overrides-path",
        type=Path,
        default=None,
        help="Transaction overrides file to migrate.",
    )
    parser.add_argument(
        "--review-state-path",
        type=Path,
        default=None,
        help="Review-state parquet to migrate.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="Migration report destination (.json).",
    )
    parser.add_argument(
        "--unmigrated-overrides-path",
        type=Path,
        default=None,
        help="Sidecar YAML/JSON file for skipped transaction overrides.",
    )
    parser.add_argument(
        "--unmigrated-review-state-path",
        type=Path,
        default=None,
        help="Sidecar CSV file for skipped review-state rows.",
    )
    parser.add_argument(
        "--backup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create backups of changed manual-state files before writing (default: enabled).",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Optional explicit backup directory.",
    )
    parser.set_defaults(command="migrate-transaction-ids", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the migration command from parsed CLI arguments."""
    settings = try_load_settings_for_defaults()
    if settings is None:
        print(
            "Migration error: configure .env with FINANCE_STATEMENTS_PATH and "
            "FINANCE_PROCESSED_PATH or provide all explicit paths."
        )
        return 1

    processed_dir = processed_dir_from_settings(settings)
    staged_path = args.staged_path or settings.staged_transactions_path
    transaction_overrides_path = (
        args.transaction_overrides_path or settings.transaction_overrides_path
    )
    review_state_path = args.review_state_path or settings.review_state_path
    report_path = args.report_path or (processed_dir / "transaction_id_migration_report.json")
    unmigrated_overrides_path = args.unmigrated_overrides_path or (
        processed_dir / "transaction_overrides_unmigrated.yaml"
    )
    unmigrated_review_state_path = args.unmigrated_review_state_path or (
        processed_dir / "review_state_unmigrated.csv"
    )

    try:
        result = migrate_transaction_ids(
            staged_path=staged_path,
            transaction_overrides_path=transaction_overrides_path,
            review_state_path=review_state_path,
            report_path=report_path,
            unmigrated_overrides_path=unmigrated_overrides_path,
            unmigrated_review_state_path=unmigrated_review_state_path,
            backup=bool(args.backup),
            backup_dir=args.backup_dir,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Migration error: {exc}")
        return 1

    print(f"Migrated overrides: {result.migrated_override_count}")
    print(f"Skipped override rows (ambiguous): {result.skipped_override_ambiguous_count}")
    print(f"Skipped override rows (unmatched): {result.skipped_override_unmatched_count}")
    print(f"Migrated review-state rows: {result.migrated_review_state_count}")
    print(f"Skipped review-state rows (ambiguous): {result.skipped_review_state_ambiguous_count}")
    print(f"Skipped review-state rows (unmatched): {result.skipped_review_state_unmatched_count}")
    print(f"Report: {result.report_path}")
    print(f"Unmigrated overrides: {result.unmigrated_overrides_path}")
    print(f"Unmigrated review state: {result.unmigrated_review_state_path}")
    if result.backup_dir is not None:
        print(f"Backup dir: {result.backup_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for transaction-id migration."""
    parser = argparse.ArgumentParser(
        prog="migrate-transaction-ids",
        description="Migrate transaction-id keyed manual state after transaction identity changes.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

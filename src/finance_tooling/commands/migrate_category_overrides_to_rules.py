"""CLI command for migrating legacy category overrides into rules."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.commands.common import (
    processed_dir_from_settings,
    try_load_settings_for_defaults,
)
from finance_tooling.migrate_category_overrides import migrate_category_overrides_to_rules


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register migrate-category-overrides-to-rules-specific CLI arguments."""
    parser.add_argument(
        "--overrides-path",
        type=Path,
        default=None,
        help="Legacy category overrides file (.yaml/.yml/.json).",
    )
    parser.add_argument(
        "--rules-path",
        type=Path,
        default=None,
        help="Category rules file to update.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="Migration report destination (.json).",
    )
    parser.add_argument(
        "--backup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create a backup of the rules file before writing (default: enabled).",
    )
    parser.add_argument(
        "--backup-path",
        type=Path,
        default=None,
        help="Optional explicit backup destination path.",
    )
    parser.set_defaults(command="migrate-category-overrides-to-rules", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the migration command from parsed CLI arguments."""
    settings = try_load_settings_for_defaults()
    processed_dir = processed_dir_from_settings(settings) if settings is not None else None
    config_dir = settings.input_path.parent / "config" if settings is not None else None

    overrides_path = args.overrides_path or (
        (config_dir / "category_overrides.yaml") if config_dir is not None else None
    )
    rules_path = args.rules_path or (
        (config_dir / "category_rules.yaml") if config_dir is not None else None
    )
    report_path = args.report_path or (
        (processed_dir / "category_override_migration_report.json")
        if processed_dir is not None
        else None
    )

    if overrides_path is None or rules_path is None or report_path is None:
        print(
            "Migration error: provide --overrides-path, --rules-path, and --report-path "
            "or configure .env with FINANCE_STATEMENTS_PATH and FINANCE_PROCESSED_PATH."
        )
        return 1

    try:
        result = migrate_category_overrides_to_rules(
            overrides_path=overrides_path,
            rules_path=rules_path,
            report_path=report_path,
            backup=bool(args.backup),
            backup_path=args.backup_path,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Migration error: {exc}")
        return 1

    print(f"Migrated rules: {result.migrated_count}")
    print(f"Skipped entries: {result.skipped_count}")
    print(f"Conflicts: {result.conflict_count}")
    print(f"Rules file: {result.rules_path}")
    print(f"Report: {result.report_path}")
    if result.backup_path is not None:
        print(f"Backup: {result.backup_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for override migration."""
    parser = argparse.ArgumentParser(
        prog="migrate-category-overrides-to-rules",
        description="Migrate legacy category overrides into exact-match category rules.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

"""CLI entrypoint for finance_tooling."""

from __future__ import annotations

import argparse

from finance_tooling.commands import (
    ingest as ingest_command,
)
from finance_tooling.commands import (
    metrics_log_update as metrics_log_update_command,
)
from finance_tooling.commands import (
    migrate_category_overrides_to_rules as migrate_category_overrides_command,
)
from finance_tooling.commands import (
    review_export as review_export_command,
)
from finance_tooling.commands import (
    review_import as review_import_command,
)
from finance_tooling.commands import (
    transform as transform_command,
)
from finance_tooling.commands import (
    update as update_command,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m finance_tooling",
        description="Finance tooling workflow and categorization review utilities.",
    )
    subparsers = parser.add_subparsers(dest="command")

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Run ingest stage and write staged transactions.",
    )
    ingest_command.configure_parser(ingest_parser)

    transform_parser = subparsers.add_parser(
        "transform",
        help="Run transform stage from staged transactions.",
    )
    transform_command.configure_parser(transform_parser)

    update_parser = subparsers.add_parser(
        "update",
        help="Run ingest then transform (or a single stage with flags).",
    )
    update_command.configure_parser(update_parser)

    review_export_parser = subparsers.add_parser(
        "review-export",
        help="Export uncategorized transaction rows for manual review.",
    )
    review_export_command.configure_parser(review_export_parser)

    review_import_parser = subparsers.add_parser(
        "review-import",
        help="Import reviewed categories and upsert overrides.",
    )
    review_import_command.configure_parser(review_import_parser)

    migrate_category_overrides_parser = subparsers.add_parser(
        "migrate-category-overrides-to-rules",
        help="Migrate legacy category overrides into exact-match rules.",
    )
    migrate_category_overrides_command.configure_parser(migrate_category_overrides_parser)

    metrics_log_parser = subparsers.add_parser(
        "metrics-log-update",
        help="Append or update commit-level percentage metrics from run_summary.json.",
    )
    metrics_log_update_command.configure_parser(metrics_log_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run workflow or categorization review subcommands."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

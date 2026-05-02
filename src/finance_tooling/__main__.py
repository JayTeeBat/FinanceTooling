"""CLI entrypoint for finance_tooling."""

from __future__ import annotations

import argparse

from finance_tooling.commands import (
    ingest as ingest_command,
)
from finance_tooling.commands import (
    planning as planning_command,
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
from finance_tooling.commands import (
    workflow_status as workflow_status_command,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m finance_tooling",
        description=(
            "Finance tooling workflow for importing statements, reviewing categories, "
            "and inspecting pipeline health."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Advanced: parse raw statements and write staged state only.",
    )
    ingest_command.configure_parser(ingest_parser)

    transform_parser = subparsers.add_parser(
        "transform",
        help="Advanced: rebuild canonical outputs from staged transactions.",
    )
    transform_command.configure_parser(transform_parser)

    planning_parser = subparsers.add_parser(
        "planning",
        help="Recommended: build planning ledger, budget status, KPIs, and dashboard.",
    )
    planning_command.configure_parser(planning_parser)

    update_parser = subparsers.add_parser(
        "update",
        help="Recommended: run the end-to-end workflow and refresh canonical outputs.",
    )
    update_command.configure_parser(update_parser)

    review_export_parser = subparsers.add_parser(
        "review-export",
        help="Recommended: export review rows into the standard workbook.",
    )
    review_export_command.configure_parser(review_export_parser)

    review_import_parser = subparsers.add_parser(
        "review-import",
        help="Recommended: import reviewed workbook changes into overrides.",
    )
    review_import_command.configure_parser(review_import_parser)

    workflow_status_parser = subparsers.add_parser(
        "workflow-status",
        help="Recommended: inspect pipeline health and write a state snapshot.",
    )
    workflow_status_command.configure_parser(workflow_status_parser)

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

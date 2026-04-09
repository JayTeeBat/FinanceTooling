"""CLI command for combined workflow update orchestration."""

from __future__ import annotations

import argparse

from finance_tooling.commands.common import (
    print_full_refresh_preflight,
    print_ingest_result,
    print_workflow_result,
)
from finance_tooling.core.config import load_settings_from_env
from finance_tooling.workflow.incremental_state import build_full_refresh_preflight
from finance_tooling.workflow.ingest_stage import IngestExecutionResult
from finance_tooling.workflow.update_stage import run_update


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register update-specific CLI arguments."""
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed counters, backup details, and diagnostic paths.",
    )
    parser.add_argument(
        "--ingest-only",
        action="store_true",
        help="Run ingest stage only.",
    )
    parser.add_argument(
        "--transform-only",
        action="store_true",
        help="Run transform stage only from staged transactions.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Reparse and rebuild the full representative source corpus.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the full-refresh impact summary without mutating anything.",
    )
    parser.add_argument(
        "--confirm-full-refresh",
        default=None,
        help="Confirmation token required to execute a full refresh.",
    )
    parser.add_argument(
        "--emit-ingest-summary",
        action="store_true",
        help="Write state/ingest_summary.json when the ingest stage runs.",
    )
    parser.set_defaults(command="update", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the update command from parsed CLI arguments."""
    try:
        settings = load_settings_from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    if args.dry_run and not args.full_refresh:
        print("Update error: --dry-run is only supported together with --full-refresh.")
        return 1
    if args.confirm_full_refresh is not None and not args.full_refresh:
        print("Update error: --confirm-full-refresh requires --full-refresh.")
        return 1
    if args.full_refresh and args.transform_only:
        print("Update error: --transform-only cannot be combined with --full-refresh.")
        return 1

    if args.full_refresh:
        preflight = build_full_refresh_preflight(settings=settings, command="update")
        if args.dry_run:
            print_full_refresh_preflight(preflight, verbose=bool(args.verbose))
            return 0
        if args.confirm_full_refresh != preflight.confirmation_token:
            print_full_refresh_preflight(preflight, verbose=bool(args.verbose))
            return 1

    try:
        if args.full_refresh:
            result = run_update(
                settings,
                ingest_only=bool(args.ingest_only),
                transform_only=bool(args.transform_only),
                full_refresh=True,
                emit_ingest_summary=bool(args.emit_ingest_summary),
            )
        else:
            result = run_update(
                settings,
                ingest_only=bool(args.ingest_only),
                transform_only=bool(args.transform_only),
                emit_ingest_summary=bool(args.emit_ingest_summary),
            )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Update error: {exc}")
        return 1

    if isinstance(result, IngestExecutionResult):
        return print_ingest_result(result, verbose=bool(args.verbose))
    return print_workflow_result(result, verbose=bool(args.verbose))


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for update."""
    parser = argparse.ArgumentParser(
        prog="update",
        description="Recommended: run the end-to-end workflow and refresh canonical outputs.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

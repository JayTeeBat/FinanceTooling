"""CLI command for the ingest stage."""

from __future__ import annotations

import argparse

from finance_tooling.commands.common import print_full_refresh_preflight, print_ingest_result
from finance_tooling.core.config import load_settings_from_env
from finance_tooling.workflow.incremental_state import build_full_refresh_preflight
from finance_tooling.workflow.ingest_stage import run_ingest


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register ingest-specific CLI arguments."""
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed counters, backup details, and diagnostic paths.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Reparse the full representative source corpus instead of only new files.",
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
        help="Write state/ingest_summary.json as an optional diagnostics artifact.",
    )
    parser.set_defaults(command="ingest", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the ingest command from parsed CLI arguments."""
    try:
        settings = load_settings_from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    if args.dry_run and not args.full_refresh:
        print("Ingest error: --dry-run is only supported together with --full-refresh.")
        return 1

    if args.confirm_full_refresh is not None and not args.full_refresh:
        print("Ingest error: --confirm-full-refresh requires --full-refresh.")
        return 1

    if args.full_refresh:
        preflight = build_full_refresh_preflight(settings=settings, command="ingest")
        if args.dry_run:
            print_full_refresh_preflight(preflight, verbose=bool(args.verbose))
            return 0
        if args.confirm_full_refresh != preflight.confirmation_token:
            print_full_refresh_preflight(preflight, verbose=bool(args.verbose))
            return 1

    try:
        if args.full_refresh:
            result = run_ingest(
                settings,
                run_mode="full_refresh",
                emit_ingest_summary=bool(args.emit_ingest_summary),
            )
        else:
            result = run_ingest(settings, emit_ingest_summary=bool(args.emit_ingest_summary))
    except (RuntimeError, ValueError) as exc:
        print(f"Ingest error: {exc}")
        return 1
    return print_ingest_result(result, verbose=bool(args.verbose))


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for ingest."""
    parser = argparse.ArgumentParser(
        prog="ingest",
        description="Advanced: run only the ingest stage and write staged state artifacts.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

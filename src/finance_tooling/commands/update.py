"""CLI command for combined workflow update orchestration."""

from __future__ import annotations

import argparse

from finance_tooling.commands.common import print_ingest_result, print_workflow_result
from finance_tooling.config import load_settings_from_env
from finance_tooling.workflow.ingest_stage import IngestExecutionResult
from finance_tooling.workflow.update_stage import run_update


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register update-specific CLI arguments."""
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
    parser.set_defaults(command="update", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the update command from parsed CLI arguments."""
    try:
        settings = load_settings_from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    try:
        result = run_update(
            settings,
            ingest_only=bool(args.ingest_only),
            transform_only=bool(args.transform_only),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Update error: {exc}")
        return 1

    if isinstance(result, IngestExecutionResult):
        return print_ingest_result(result)
    return print_workflow_result(result)


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for update."""
    parser = argparse.ArgumentParser(
        prog="update",
        description="Run ingest then transform, or a single stage with flags.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

"""CLI command for the ingest stage."""

from __future__ import annotations

import argparse

from finance_tooling.commands.common import print_ingest_result
from finance_tooling.config import load_settings_from_env
from finance_tooling.workflow.ingest_stage import run_ingest


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register ingest-specific CLI arguments."""
    parser.set_defaults(command="ingest", handler=handle)


def handle(_args: argparse.Namespace) -> int:
    """Execute the ingest command from parsed CLI arguments."""
    try:
        settings = load_settings_from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    try:
        result = run_ingest(settings)
    except (RuntimeError, ValueError) as exc:
        print(f"Ingest error: {exc}")
        return 1
    return print_ingest_result(result)


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for ingest."""
    parser = argparse.ArgumentParser(prog="ingest", description="Run ingest stage only.")
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

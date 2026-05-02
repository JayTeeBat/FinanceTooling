"""CLI command for the planning stage."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.commands.common import print_planning_result
from finance_tooling.core.config import load_settings_from_env
from finance_tooling.workflow.planning_stage import run_planning


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register planning-specific CLI arguments."""
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed planning artifact paths and warnings.",
    )
    parser.add_argument(
        "--input-transactions-path",
        type=Path,
        default=None,
        help="Path to canonical transform transactions parquet or CSV.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for planning artifacts.",
    )
    parser.add_argument(
        "--budget-targets-path",
        type=Path,
        default=None,
        help="Path to budget targets YAML/JSON.",
    )
    parser.set_defaults(command="planning", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the planning command from parsed CLI arguments."""
    try:
        settings = load_settings_from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    try:
        result = run_planning(
            settings,
            input_transactions_path=args.input_transactions_path,
            output_dir=args.output_dir,
            budget_targets_path=args.budget_targets_path,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Planning error: {exc}")
        return 1
    return print_planning_result(result, verbose=bool(args.verbose))


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for planning."""
    parser = argparse.ArgumentParser(
        prog="planning",
        description="Recommended: build planning ledger, budget status, KPIs, and dashboard.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

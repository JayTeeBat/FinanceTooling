"""CLI command for the transform stage."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.commands.common import print_workflow_result
from finance_tooling.config import load_settings_from_env
from finance_tooling.workflow.transform_stage import run_transform


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register transform-specific CLI arguments."""
    parser.add_argument(
        "--input-staged-path",
        type=Path,
        default=None,
        help="Path to staged transactions parquet (defaults to configured staged path).",
    )
    parser.set_defaults(command="transform", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the transform command from parsed CLI arguments."""
    try:
        settings = load_settings_from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    try:
        result = run_transform(settings, staged_path=args.input_staged_path)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Transform error: {exc}")
        return 1
    return print_workflow_result(result)


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for transform."""
    parser = argparse.ArgumentParser(
        prog="transform",
        description="Advanced: run only the transform stage and rebuild canonical outputs.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

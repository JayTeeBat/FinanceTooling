"""CLI command for rendering the planning hypothesis playground page."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.planning.dashboard import render_planning_hypothesis_html

DEFAULT_INPUTS_PATH = Path("planning/household_finance_360/09_planning_inputs.yaml")
DEFAULT_OUTPUT_PATH = Path("planning/household_finance_360/15_hypothesis_playground.html")


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register plan-hypothesis-page-specific CLI arguments."""
    parser.add_argument(
        "--inputs-path",
        type=Path,
        default=DEFAULT_INPUTS_PATH,
        help="Path to planning assumptions YAML.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Destination HTML path for the hypothesis playground.",
    )
    parser.set_defaults(command="plan-hypothesis-page", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the plan-hypothesis-page command from parsed CLI arguments."""
    if not args.inputs_path.exists():
        print(f"Planning inputs not found: {args.inputs_path}")
        return 1
    destination = render_planning_hypothesis_html(args.inputs_path, args.output_path)
    print(f"Hypothesis playground written: {destination}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for plan-hypothesis-page."""
    parser = argparse.ArgumentParser(
        prog="plan-hypothesis-page",
        description="Render a self-contained HTML planning hypothesis playground.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

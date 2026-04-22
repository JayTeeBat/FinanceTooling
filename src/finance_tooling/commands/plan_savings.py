"""CLI command for household savings sizing from planning inputs."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from finance_tooling.planning.engine import (
    build_planning_summary,
    load_planning_inputs,
    write_planning_summary,
)

DEFAULT_INPUTS_PATH = Path("planning/household_finance_360/09_planning_inputs.yaml")
DEFAULT_OUTPUT_PATH = Path("planning/household_finance_360/12_sizing_output.json")


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register plan-savings-specific CLI arguments."""
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
        help="Path to write JSON sizing output.",
    )
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=None,
        help="Optional ISO date override for calculations (YYYY-MM-DD).",
    )
    parser.set_defaults(command="plan-savings", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the plan-savings command from parsed CLI arguments."""
    if not args.inputs_path.exists():
        print(f"Planning inputs not found: {args.inputs_path}")
        return 1

    try:
        effective_date = date.fromisoformat(args.as_of_date) if args.as_of_date else None
    except ValueError:
        print(f"Invalid --as-of-date value: {args.as_of_date}")
        return 1

    try:
        inputs = load_planning_inputs(args.inputs_path)
        summary = build_planning_summary(inputs, as_of_date=effective_date)
    except ValueError as exc:
        print(f"Planning input error: {exc}")
        return 1

    write_planning_summary(args.output_path, summary)
    print(f"Planning sizing output written: {args.output_path}")
    print(f"As of date: {summary.as_of_date}")
    print(f"Inflation assumption: {summary.inflation_pct:.2f}%")
    print(f"Emergency fund target: {summary.emergency_fund_target_eur:.2f} EUR")
    print(
        "Retirement annual gap: "
        f"{summary.retirement_annual_gap_eur:.2f} EUR "
        f"(today: {summary.retirement_annual_gap_today_eur:.2f} EUR)"
    )
    print(
        "Retirement target capital: "
        f"{summary.retirement_target_capital_eur:.2f} EUR "
        f"(today: {summary.retirement_target_capital_today_eur:.2f} EUR)"
    )
    print("Required monthly savings by goal:")
    for result in summary.goal_results:
        print(
            f"- {result.goal_name}: {result.required_monthly_saving_eur:.2f} EUR/month "
            f"(target {result.inflation_adjusted_target_amount_eur:.2f} EUR, "
            f"today-value {result.base_target_amount_eur:.2f} EUR, "
            f"return {result.expected_return_pct:.2f}%, "
            f"{result.years_to_goal:.1f} years)"
        )
    print(
        f"Total required monthly savings: {summary.total_required_monthly_saving_eur:.2f} EUR/month"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for plan-savings."""
    parser = argparse.ArgumentParser(
        prog="plan-savings",
        description="Calculate monthly savings requirements from planning assumptions.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

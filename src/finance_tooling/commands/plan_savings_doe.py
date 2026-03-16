"""CLI command for savings-planning design-of-experiments runs."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from finance_tooling.planning import (
    build_planning_doe_rows,
    load_planning_inputs,
    write_planning_doe_rows,
)

DEFAULT_BASE_INPUTS_PATH = Path("planning/household_finance_360/09_planning_inputs.yaml")
DEFAULT_DOE_INPUTS_PATH = Path("planning/household_finance_360/13_doe_ranges.yaml")
DEFAULT_OUTPUT_PATH = Path("planning/household_finance_360/14_doe_results.csv")


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register plan-savings-doe-specific CLI arguments."""
    parser.add_argument(
        "--base-inputs-path",
        type=Path,
        default=DEFAULT_BASE_INPUTS_PATH,
        help="Path to baseline planning assumptions YAML.",
    )
    parser.add_argument(
        "--doe-inputs-path",
        type=Path,
        default=DEFAULT_DOE_INPUTS_PATH,
        help="Path to DOE ranges YAML.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to write DOE CSV output.",
    )
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=None,
        help="Optional ISO date override for calculations (YYYY-MM-DD).",
    )
    parser.set_defaults(command="plan-savings-doe", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the plan-savings-doe command from parsed CLI arguments."""
    for path, label in (
        (args.base_inputs_path, "Baseline planning inputs"),
        (args.doe_inputs_path, "DOE inputs"),
    ):
        if not path.exists():
            print(f"{label} not found: {path}")
            return 1

    try:
        effective_date = date.fromisoformat(args.as_of_date) if args.as_of_date else None
    except ValueError:
        print(f"Invalid --as-of-date value: {args.as_of_date}")
        return 1

    try:
        base_inputs = load_planning_inputs(args.base_inputs_path)
        doe_inputs = load_planning_inputs(args.doe_inputs_path)
        rows = build_planning_doe_rows(base_inputs, doe_inputs, as_of_date=effective_date)
    except ValueError as exc:
        print(f"Planning DOE input error: {exc}")
        return 1

    if not rows:
        print("No DOE rows were generated.")
        return 1

    write_planning_doe_rows(args.output_path, rows)
    print(f"Planning DOE output written: {args.output_path}")
    print(f"Scenario count: {len(rows)}")
    print("Lowest monthly savings cases:")
    for row in rows[:5]:
        print(
            f"- {row.scenario_name}: {row.total_required_monthly_saving_eur:.2f} EUR/month "
            f"(retirement {row.required_monthly_retirement_saving_eur:.2f}, "
            f"education {row.required_monthly_education_saving_eur:.2f}, "
            f"house {row.required_monthly_house_saving_eur:.2f})"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for plan-savings-doe."""
    parser = argparse.ArgumentParser(
        prog="plan-savings-doe",
        description="Run a savings-planning scenario grid and write ranked CSV results.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

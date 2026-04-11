"""CLI command for static review-helper generation."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.commands.common import (
    resolve_review_helper_paths,
    try_load_settings_for_defaults,
)
from finance_tooling.reporting.review_helper import render_review_helper_html
from finance_tooling.review.export import build_review_dataframe


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register review-helper-specific CLI arguments."""
    parser.add_argument(
        "--normalized-path",
        type=Path,
        default=None,
        help="Path to normalized transactions table (.csv/.json/.parquet).",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="Destination helper file (.html).",
    )
    parser.add_argument(
        "--include-categorized",
        action="store_true",
        help="Include already-categorized rows in addition to uncategorized rows.",
    )
    parser.add_argument(
        "--month",
        type=str,
        default=None,
        help="Optional month shortcut (YYYY-MM) for start/end booking_date bounds.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Optional inclusive lower booking_date bound (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Optional inclusive upper booking_date bound (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--contains",
        type=str,
        default=None,
        help="Optional case-insensitive substring filter across review text fields.",
    )
    parser.add_argument(
        "--bank",
        type=str,
        default=None,
        help="Optional exact bank filter.",
    )
    parser.add_argument(
        "--account-label",
        type=str,
        default=None,
        help="Optional exact account label filter.",
    )
    parser.add_argument(
        "--only-unreviewed",
        action="store_true",
        help="Include only rows that are not reviewed in persisted review state.",
    )
    parser.set_defaults(command="review-helper", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the review-helper command from parsed CLI arguments."""
    try:
        normalized_path, output_path, review_state_path = resolve_review_helper_paths(
            args.normalized_path,
            args.output_path,
        )
        settings = try_load_settings_for_defaults()
        review_rows, review_rules = build_review_dataframe(
            normalized_path,
            include_categorized=bool(args.include_categorized),
            month=args.month,
            start_date=args.start_date,
            end_date=args.end_date,
            contains=args.contains,
            bank=args.bank,
            account_label=args.account_label,
            only_unreviewed=bool(args.only_unreviewed),
            review_state_path=review_state_path,
            category_rules_path=(
                getattr(settings, "category_rules_path", None) if settings is not None else None
            ),
        )
        destination = render_review_helper_html(
            review_rows,
            output_path,
            rules=review_rules,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Review helper error: {exc}")
        return 1
    print(f"Review helper: {len(review_rows)} rows")
    print(f"Review helper output: {destination.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for review-helper."""
    parser = argparse.ArgumentParser(
        prog="review-helper",
        description="Generate a static HTML helper for review triage and draft export.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

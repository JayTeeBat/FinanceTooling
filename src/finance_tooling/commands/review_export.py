"""CLI command for review-export."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.commands import common
from finance_tooling.reporting.review_helper import render_review_helper_html
from finance_tooling.review.common import write_table
from finance_tooling.review.export import build_review_dataframe


def _default_helper_output_path(review_output_path: Path) -> Path:
    """Derive the default helper path alongside the processed review workbook."""
    return review_output_path.parent / common.DEFAULT_REVIEW_HELPER_FILENAME


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register review-export-specific CLI arguments."""
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
        help="Destination review file (.xlsx, .csv, or .json).",
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
        "--min-amount",
        type=str,
        default=None,
        help="Optional inclusive lower bound on signed amount_native.",
    )
    parser.add_argument(
        "--max-amount",
        type=str,
        default=None,
        help="Optional inclusive upper bound on signed amount_native.",
    )
    parser.add_argument(
        "--min-abs-amount",
        type=str,
        default=None,
        help="Optional inclusive lower bound on abs(amount_native).",
    )
    parser.add_argument(
        "--max-abs-amount",
        type=str,
        default=None,
        help="Optional inclusive upper bound on abs(amount_native).",
    )
    parser.add_argument(
        "--only-unreviewed",
        action="store_true",
        help="Export only rows that are not marked reviewed in persisted review state.",
    )
    parser.add_argument(
        "--preserve-review-state",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Preserve editable review fields from the existing review workbook when re-exporting.",
    )
    parser.add_argument(
        "--dark-safe",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Render `.xlsx` output with explicit light text on dark fills "
            "for dark-mode readability out of the box."
        ),
    )
    parser.add_argument(
        "--helper",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also generate the static HTML review helper alongside the workbook export.",
    )
    parser.set_defaults(command="review-export", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the review-export command from parsed CLI arguments."""
    try:
        normalized_path, output_path, review_state_path, default_dark_safe = (
            common.resolve_review_export_paths(
                args.normalized_path,
                args.output_path,
            )
        )
        settings = common.try_load_settings_for_defaults()
        review_rows, review_rules = build_review_dataframe(
            normalized_path,
            output_path,
            include_categorized=bool(args.include_categorized),
            month=args.month,
            start_date=args.start_date,
            end_date=args.end_date,
            contains=args.contains,
            bank=args.bank,
            account_label=args.account_label,
            min_amount=args.min_amount,
            max_amount=args.max_amount,
            min_abs_amount=args.min_abs_amount,
            max_abs_amount=args.max_abs_amount,
            only_unreviewed=bool(args.only_unreviewed),
            preserve_review_state=bool(args.preserve_review_state),
            review_state_path=review_state_path,
            category_rules_path=(
                getattr(settings, "category_rules_path", None) if settings is not None else None
            ),
        )
        write_table(
            output_path,
            review_rows,
            dark_safe=(default_dark_safe if args.dark_safe is None else bool(args.dark_safe)),
            review_rules=review_rules,
        )
        helper_path: Path | None = None
        if bool(args.helper):
            helper_path = _default_helper_output_path(output_path)
            render_review_helper_html(
                review_rows,
                helper_path,
                rules=review_rules,
            )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Review export error: {exc}")
        return 1
    print(f"Review export: {len(review_rows)} rows")
    if helper_path is not None:
        print(f"Review helper: {helper_path.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for review-export."""
    parser = argparse.ArgumentParser(
        prog="review-export",
        description="Export uncategorized transaction rows for manual review.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

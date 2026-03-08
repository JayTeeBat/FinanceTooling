"""CLI command for review-export."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.commands.common import resolve_review_export_paths
from finance_tooling.review_export import export_review_rows


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
    parser.set_defaults(command="review-export", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the review-export command from parsed CLI arguments."""
    try:
        normalized_path, output_path, review_state_path, default_dark_safe = (
            resolve_review_export_paths(
                args.normalized_path,
                args.output_path,
            )
        )
        exported = export_review_rows(
            normalized_path,
            output_path,
            include_categorized=bool(args.include_categorized),
            start_date=args.start_date,
            end_date=args.end_date,
            contains=args.contains,
            bank=args.bank,
            account_label=args.account_label,
            only_unreviewed=bool(args.only_unreviewed),
            preserve_review_state=bool(args.preserve_review_state),
            review_state_path=review_state_path,
            dark_safe=(default_dark_safe if args.dark_safe is None else bool(args.dark_safe)),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Review export error: {exc}")
        return 1
    print(f"Exported {exported} review rows to {output_path}")
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

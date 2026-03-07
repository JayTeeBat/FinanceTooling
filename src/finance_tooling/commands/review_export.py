"""CLI command for review-export."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.commands.common import resolve_review_export_paths
from finance_tooling.review_export import export_fallback_review_rows


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
        help="Destination review file (.csv or .json).",
    )
    parser.add_argument(
        "--include-categorized",
        action="store_true",
        help="Include already-categorized rows in addition to fallback rows.",
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
    parser.set_defaults(command="review-export", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the review-export command from parsed CLI arguments."""
    try:
        normalized_path, output_path = resolve_review_export_paths(
            args.normalized_path,
            args.output_path,
        )
        exported = export_fallback_review_rows(
            normalized_path,
            output_path,
            include_categorized=bool(args.include_categorized),
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Review export error: {exc}")
        return 1
    print(f"Exported {exported} fallback review rows to {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for review-export."""
    parser = argparse.ArgumentParser(
        prog="review-export",
        description="Export fallback categorization rows for manual review.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

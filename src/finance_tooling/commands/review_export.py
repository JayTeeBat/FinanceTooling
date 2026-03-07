"""CLI command for review-export."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.config import Settings, load_settings_from_env
from finance_tooling.review_export import export_fallback_review_rows


def _try_load_settings_for_review_defaults() -> Settings | None:
    try:
        return load_settings_from_env()
    except ValueError:
        return None


def _resolve_review_export_paths(
    normalized_path: Path | None,
    output_path: Path | None,
) -> tuple[Path, Path]:
    if normalized_path is not None and output_path is not None:
        return normalized_path, output_path

    settings = _try_load_settings_for_review_defaults()
    if settings is None:
        missing_flags: list[str] = []
        if normalized_path is None:
            missing_flags.append("--normalized-path")
        if output_path is None:
            missing_flags.append("--output-path")
        joined = ", ".join(missing_flags)
        raise ValueError(
            f"Missing {joined}; provide explicit flags or configure .env "
            "with FINANCE_STATEMENTS_PATH and FINANCE_PROCESSED_PATH."
        )

    processed_dir = settings.summary_json_path.parent
    return (
        normalized_path or (processed_dir / "transactions_normalized.csv"),
        output_path or (processed_dir / "fallback_category_review.csv"),
    )


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
        normalized_path, output_path = _resolve_review_export_paths(
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

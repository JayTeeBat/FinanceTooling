"""Manual categorization review export helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from finance_tooling.review_common import (
    EXISTING_PROJECT_TAGS_COLUMN,
    OVERRIDE_LEVEL_COLUMN,
    PROJECT_TAGS_COLUMN,
    REQUIRED_REVIEW_COLUMNS,
    parse_filter_date,
    read_table,
    write_table,
)


def export_fallback_review_rows(
    normalized_path: Path,
    review_output_path: Path,
    *,
    include_categorized: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """Export fallback-classified rows for manual review."""
    dataframe = read_table(normalized_path)
    missing_columns = [
        column for column in REQUIRED_REVIEW_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Input table missing required columns: {joined}")

    start_date_value = parse_filter_date(start_date, label="start_date")
    end_date_value = parse_filter_date(end_date, label="end_date")
    if (
        start_date_value is not None
        and end_date_value is not None
        and start_date_value > end_date_value
    ):
        raise ValueError("start_date must be <= end_date")

    filtered_rows = dataframe
    if not include_categorized:
        filtered_rows = filtered_rows.loc[
            filtered_rows["category_source"].astype(str).str.strip().str.lower() == "fallback"
        ]

    if start_date_value is not None or end_date_value is not None:
        if "booking_date" not in filtered_rows.columns:
            raise ValueError("Input table missing required columns: booking_date")
        booking_dates = pd.to_datetime(filtered_rows["booking_date"], errors="coerce")
        if start_date_value is not None:
            filtered_rows = filtered_rows.loc[booking_dates >= pd.Timestamp(start_date_value)]
            booking_dates = booking_dates.loc[filtered_rows.index]
        if end_date_value is not None:
            filtered_rows = filtered_rows.loc[booking_dates <= pd.Timestamp(end_date_value)]

    review_rows = filtered_rows.copy()
    if PROJECT_TAGS_COLUMN in review_rows.columns:
        review_rows[EXISTING_PROJECT_TAGS_COLUMN] = review_rows[PROJECT_TAGS_COLUMN]
    else:
        review_rows[EXISTING_PROJECT_TAGS_COLUMN] = None
    review_rows[PROJECT_TAGS_COLUMN] = None
    review_rows[OVERRIDE_LEVEL_COLUMN] = None
    if "project_source" in review_rows.columns:
        columns = review_rows.columns.tolist()
        columns.remove(OVERRIDE_LEVEL_COLUMN)
        project_source_index = columns.index("project_source")
        columns.insert(project_source_index + 1, OVERRIDE_LEVEL_COLUMN)
        review_rows = review_rows.loc[:, columns]
    write_table(review_output_path, review_rows)
    return len(review_rows)

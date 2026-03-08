"""Manual transaction review export helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from finance_tooling.classify import normalize_description
from finance_tooling.review_common import (
    EXISTING_PROJECT_TAGS_COLUMN,
    FINGERPRINT_COLUMN,
    PROJECT_TAGS_COLUMN,
    REQUIRED_REVIEW_COLUMNS,
    REVIEW_COMMENT_COLUMN,
    REVIEWED_COLUMN,
    normalize_optional_upper,
    normalize_reviewed_value,
    parse_filter_date,
    read_table,
    write_table,
)
from finance_tooling.review_state import load_review_state

_PRESERVED_REVIEW_COLUMNS = (
    "category",
    "subcategory",
    PROJECT_TAGS_COLUMN,
    REVIEWED_COLUMN,
    REVIEW_COMMENT_COLUMN,
)
_CONTEXT_EXPORT_COLUMNS = (
    "transaction_id",
    "booking_date",
    "description",
    "amount_native",
    "currency",
    "bank",
)
_EDITABLE_EXPORT_COLUMNS = (
    "category",
    "subcategory",
    PROJECT_TAGS_COLUMN,
    REVIEWED_COLUMN,
    REVIEW_COMMENT_COLUMN,
)
_PROVENANCE_EXPORT_COLUMNS = (
    FINGERPRINT_COLUMN,
    "account_label",
    "project_source",
    EXISTING_PROJECT_TAGS_COLUMN,
    "source_file",
)


def _apply_existing_review_values(
    review_rows: pd.DataFrame,
    existing_rows: pd.DataFrame,
) -> pd.DataFrame:
    if "transaction_id" not in review_rows.columns or "transaction_id" not in existing_rows.columns:
        return review_rows

    merged = review_rows.copy()
    existing_indexed = (
        existing_rows.dropna(subset=["transaction_id"])
        .drop_duplicates(subset=["transaction_id"], keep="last")
        .set_index("transaction_id")
    )
    review_transaction_ids = merged["transaction_id"].astype(str)
    for column in _PRESERVED_REVIEW_COLUMNS:
        if column not in existing_indexed.columns:
            continue
        merged[column] = review_transaction_ids.map(existing_indexed[column]).where(
            review_transaction_ids.isin(existing_indexed.index.astype(str)),
            merged[column],
        )
    return merged


def _apply_review_state(review_rows: pd.DataFrame, review_state_path: Path | None) -> pd.DataFrame:
    if review_state_path is None or "transaction_id" not in review_rows.columns:
        return review_rows
    state = load_review_state(review_state_path)
    if state.empty:
        return review_rows
    merged = review_rows.copy()
    indexed = state.drop_duplicates(subset=["transaction_id"], keep="last").set_index(
        "transaction_id"
    )
    transaction_ids = merged["transaction_id"].astype(str)
    if REVIEWED_COLUMN in indexed.columns:
        merged[REVIEWED_COLUMN] = transaction_ids.map(indexed[REVIEWED_COLUMN]).where(
            transaction_ids.isin(indexed.index.astype(str)),
            merged[REVIEWED_COLUMN].map(normalize_reviewed_value),
        )
    if REVIEW_COMMENT_COLUMN in indexed.columns:
        merged[REVIEW_COMMENT_COLUMN] = transaction_ids.map(indexed[REVIEW_COMMENT_COLUMN]).where(
            transaction_ids.isin(indexed.index.astype(str)),
            merged[REVIEW_COMMENT_COLUMN],
        )
    return merged


def _apply_contains_filter(dataframe: pd.DataFrame, text: str | None) -> pd.DataFrame:
    if text is None:
        return dataframe
    needle = text.strip().casefold()
    if not needle:
        return dataframe

    haystacks = []
    for column in ("description", FINGERPRINT_COLUMN, "bank", "account_label"):
        if column not in dataframe.columns:
            continue
        haystacks.append(dataframe[column].fillna("").astype(str).str.casefold())
    if not haystacks:
        return dataframe
    mask = haystacks[0].str.contains(needle, regex=False)
    for series in haystacks[1:]:
        mask = mask | series.str.contains(needle, regex=False)
    return dataframe.loc[mask]


def _apply_exact_filter(dataframe: pd.DataFrame, column: str, value: str | None) -> pd.DataFrame:
    if value is None or column not in dataframe.columns:
        return dataframe
    normalized = normalize_optional_upper(value)
    if normalized is None:
        return dataframe
    values = dataframe[column].map(normalize_optional_upper)
    return dataframe.loc[values == normalized]


def _order_review_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    ordered: list[str] = []
    for column in (
        *_CONTEXT_EXPORT_COLUMNS,
        *_EDITABLE_EXPORT_COLUMNS,
        *_PROVENANCE_EXPORT_COLUMNS,
    ):
        if column in dataframe.columns and column not in ordered:
            ordered.append(column)
    for column in dataframe.columns:
        if column not in ordered:
            ordered.append(column)
    return dataframe.loc[:, ordered]


def export_review_rows(
    normalized_path: Path,
    review_output_path: Path,
    *,
    include_categorized: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
    contains: str | None = None,
    bank: str | None = None,
    account_label: str | None = None,
    only_unreviewed: bool = False,
    preserve_review_state: bool = True,
    review_state_path: Path | None = None,
    dark_safe: bool = True,
) -> int:
    """Export uncategorized rows for manual review."""
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

    filtered_rows = dataframe.copy()
    filtered_rows[FINGERPRINT_COLUMN] = filtered_rows["description"].map(
        lambda value: normalize_description(str(value))
    )

    if not include_categorized and "category_source" in filtered_rows.columns:
        filtered_rows = filtered_rows.loc[
            filtered_rows["category_source"].astype(str).str.strip().str.lower() == "uncategorized"
        ]

    if start_date_value is not None or end_date_value is not None:
        booking_dates = pd.to_datetime(filtered_rows["booking_date"], errors="coerce")
        if start_date_value is not None:
            filtered_rows = filtered_rows.loc[booking_dates >= pd.Timestamp(start_date_value)]
            booking_dates = booking_dates.loc[filtered_rows.index]
        if end_date_value is not None:
            filtered_rows = filtered_rows.loc[booking_dates <= pd.Timestamp(end_date_value)]

    filtered_rows = _apply_contains_filter(filtered_rows, contains)
    filtered_rows = _apply_exact_filter(filtered_rows, "bank", bank)
    filtered_rows = _apply_exact_filter(filtered_rows, "account_label", account_label)

    review_rows = filtered_rows.copy()
    if PROJECT_TAGS_COLUMN in review_rows.columns:
        review_rows[EXISTING_PROJECT_TAGS_COLUMN] = review_rows[PROJECT_TAGS_COLUMN]
    else:
        review_rows[EXISTING_PROJECT_TAGS_COLUMN] = None
    review_rows[PROJECT_TAGS_COLUMN] = None
    review_rows[REVIEWED_COLUMN] = False
    review_rows[REVIEW_COMMENT_COLUMN] = None
    for removable in ("category_source", "category_rule_id"):
        if removable in review_rows.columns:
            review_rows = review_rows.drop(columns=[removable])

    if preserve_review_state and review_output_path.exists():
        review_rows = _apply_existing_review_values(review_rows, read_table(review_output_path))
    review_rows = _apply_review_state(review_rows, review_state_path)

    if only_unreviewed:
        review_rows = review_rows.loc[~review_rows[REVIEWED_COLUMN].map(normalize_reviewed_value)]

    review_rows = _order_review_columns(review_rows)
    write_table(review_output_path, review_rows, dark_safe=dark_safe)
    return len(review_rows)

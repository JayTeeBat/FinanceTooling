"""Shared helpers for review export/import workflows."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

REQUIRED_REVIEW_COLUMNS: tuple[str, ...] = (
    "description",
    "bank",
    "account_label",
    "category",
    "subcategory",
    "category_source",
)
OVERRIDE_LEVEL_COLUMN = "override_level"
PROJECT_TAGS_COLUMN = "project_tags"
EXISTING_PROJECT_TAGS_COLUMN = "existing_project_tags"
VALID_OVERRIDE_LEVELS = {"skip", "category_override", "transaction_override"}


def read_table(path: Path) -> pd.DataFrame:
    """Read CSV/JSON/parquet review or normalized tables."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported table format for {path}; expected .csv, .json, or .parquet")


def write_table(path: Path, dataframe: pd.DataFrame) -> None:
    """Write CSV/JSON review export tables."""
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        dataframe.to_csv(path, index=False)
        return
    if suffix == ".json":
        path.write_text(
            json.dumps(dataframe.to_dict(orient="records"), indent=2, default=str),
            encoding="utf-8",
        )
        return
    raise ValueError(f"Unsupported review output format for {path}; expected .csv or .json")


def normalize_optional_text(value: object) -> str | None:
    """Normalize optional text-like values from review tables."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def normalize_optional_upper(value: object) -> str | None:
    """Normalize optional text and uppercase it."""
    text = normalize_optional_text(value)
    return text.upper() if text is not None else None


def normalize_optional_decimal(value: object) -> Decimal | None:
    """Normalize optional decimal values from review tables."""
    text = normalize_optional_text(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def normalize_optional_booking_date(value: object) -> str | None:
    """Normalize optional date-like values to ISO format."""
    text = normalize_optional_text(value)
    if text is None:
        return None
    timestamp = pd.to_datetime(text, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp.date().isoformat()


def normalize_project_tags(value: object) -> tuple[str, ...]:
    """Normalize review project tag input into a unique ordered tuple."""
    if value is None:
        return ()
    raw_values: list[str] = []
    if isinstance(value, list | tuple):
        raw_values.extend(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return ()
        raw_values.extend(part.strip() for part in text.split("|"))

    tags: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        if not raw:
            continue
        marker = raw.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        tags.append(raw)
    return tuple(tags)


def is_fallback_category_source(value: object) -> bool:
    """Return True when the source column points to fallback categorization."""
    normalized = normalize_optional_text(value)
    if normalized is None:
        return False
    return normalized.lower() == "fallback"


def parse_filter_date(value: str | None, *, label: str) -> date | None:
    """Parse optional inclusive date bounds for review export."""
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid {label}: {value}")
    return parsed.date()

"""Manual categorization review export/import helpers."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import yaml

from finance_tooling.classify import OverrideEntry, OverrideStore, normalize_description
from finance_tooling.transaction_overrides import (
    TransactionOverrideEntry,
    TransactionOverrideStore,
    load_transaction_override_store,
    merge_transaction_override_entries,
    transaction_override_entry_key,
    upsert_transaction_override_entries,
    write_transaction_override_store,
)

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


@dataclass(frozen=True)
class ReviewImportResult:
    """Result metadata for review import/upsert."""

    rows_read: int = 0
    overrides_upserted: int = 0
    overrides_updated: int = 0
    overrides_inserted: int = 0
    transaction_overrides_upserted: int = 0
    transaction_overrides_updated: int = 0
    transaction_overrides_inserted: int = 0
    project_tags_applied: int = 0
    rows_skipped: int = 0
    rows_skipped_non_fallback: int = 0
    rows_skipped_invalid: int = 0
    rows_skipped_invalid_category: int = 0
    rows_skipped_invalid_project_tags: int = 0
    backup_path: Path | None = None
    transaction_backup_path: Path | None = None


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported table format for {path}; expected .csv, .json, or .parquet")


def _write_table(path: Path, dataframe: pd.DataFrame) -> None:
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


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _normalize_optional_upper(value: object) -> str | None:
    text = _normalize_optional_text(value)
    return text.upper() if text is not None else None


def _normalize_optional_decimal(value: object) -> Decimal | None:
    text = _normalize_optional_text(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _normalize_optional_booking_date(value: object) -> str | None:
    text = _normalize_optional_text(value)
    if text is None:
        return None
    timestamp = pd.to_datetime(text, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp.date().isoformat()


def _normalize_project_tags(value: object) -> tuple[str, ...]:
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


def _is_fallback_category_source(value: object) -> bool:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return False
    return normalized.lower() == "fallback"


def _parse_filter_date(value: str | None, *, label: str) -> date | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid {label}: {value}")
    return parsed.date()


def export_fallback_review_rows(
    normalized_path: Path,
    review_output_path: Path,
    *,
    include_categorized: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """Export fallback-classified rows for manual review."""
    dataframe = _read_table(normalized_path)
    missing_columns = [
        column for column in REQUIRED_REVIEW_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Input table missing required columns: {joined}")

    start_date_value = _parse_filter_date(start_date, label="start_date")
    end_date_value = _parse_filter_date(end_date, label="end_date")
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
    _write_table(review_output_path, review_rows)
    return len(review_rows)


def _parse_category_override_row(
    row: dict[str, object],
    *,
    include_account_label_scope: bool,
) -> OverrideEntry | None:
    description = _normalize_optional_text(row.get("description"))
    category = _normalize_optional_text(row.get("category"))
    if description is None or category is None:
        return None

    fingerprint = normalize_description(description)
    if not fingerprint:
        return None

    bank = _normalize_optional_upper(row.get("bank"))
    account_label = (
        _normalize_optional_upper(row.get("account_label")) if include_account_label_scope else None
    )
    subcategory = _normalize_optional_text(row.get("subcategory"))
    return OverrideEntry(
        fingerprint=fingerprint,
        category=category,
        subcategory=subcategory,
        bank=bank,
        account_label=account_label,
        hit_count=0,
    )


def _parse_category_transaction_override_row(
    row: dict[str, object],
) -> TransactionOverrideEntry | None:
    category = _normalize_optional_text(row.get("category"))
    if category is None:
        return None

    subcategory = _normalize_optional_text(row.get("subcategory"))
    transaction_id = _normalize_optional_text(row.get("transaction_id"))

    fingerprint: str | None = None
    booking_date: str | None = None
    amount_native: Decimal | None = None
    currency: str | None = None
    bank: str | None = None
    account_label: str | None = None

    if transaction_id is None:
        description = _normalize_optional_text(row.get("description"))
        fingerprint = normalize_description(description or "")
        if not fingerprint:
            return None
        booking_date = _normalize_optional_booking_date(row.get("booking_date"))
        amount_native = _normalize_optional_decimal(row.get("amount_native"))
        currency = _normalize_optional_upper(row.get("currency"))
        bank = _normalize_optional_upper(row.get("bank"))
        account_label = _normalize_optional_upper(row.get("account_label"))
        if booking_date is None or amount_native is None or currency is None or bank is None:
            return None

    return TransactionOverrideEntry(
        override_id=None,
        transaction_id=transaction_id,
        fingerprint=fingerprint,
        booking_date=(
            datetime.fromisoformat(f"{booking_date}T00:00:00+00:00").date()
            if booking_date
            else None
        ),
        amount_native=amount_native,
        currency=currency,
        bank=bank,
        account_label=account_label,
        category=category,
        set_category=True,
        subcategory=subcategory,
        set_subcategory=True,
        project=None,
        set_project=False,
        project_tags=(),
        set_project_tags=False,
    )


def _parse_project_transaction_override_row(
    row: dict[str, object],
    tags: tuple[str, ...],
) -> TransactionOverrideEntry | None:
    transaction_id = _normalize_optional_text(row.get("transaction_id"))
    if transaction_id is None:
        return None
    return TransactionOverrideEntry(
        override_id=None,
        transaction_id=transaction_id,
        fingerprint=None,
        booking_date=None,
        amount_native=None,
        currency=None,
        bank=None,
        account_label=None,
        category=None,
        set_category=False,
        subcategory=None,
        set_subcategory=False,
        project=None,
        set_project=False,
        project_tags=tags,
        set_project_tags=True,
    )


def _resolve_override_level(
    row: dict[str, object],
    *,
    has_override_level_column: bool,
) -> str | None:
    if not has_override_level_column:
        return "category_override"
    raw = _normalize_optional_text(row.get(OVERRIDE_LEVEL_COLUMN))
    if raw is None:
        return "transaction_override"
    normalized = raw.strip().lower()
    if normalized in VALID_OVERRIDE_LEVELS:
        return normalized
    return None


def _has_category_override_request(
    row: dict[str, object],
    *,
    has_override_level_column: bool,
) -> bool:
    category = _normalize_optional_text(row.get("category"))
    subcategory = _normalize_optional_text(row.get("subcategory"))
    if category is None:
        return False
    if not has_override_level_column:
        return True
    return category.lower() != "uncategorized" or subcategory is not None


def _entry_matches(
    existing: OverrideEntry,
    incoming: OverrideEntry,
    *,
    include_account_label_scope: bool,
) -> bool:
    if existing.fingerprint != incoming.fingerprint:
        return False
    if (existing.bank or None) != (incoming.bank or None):
        return False
    if include_account_label_scope:
        return (existing.account_label or None) == (incoming.account_label or None)
    return existing.account_label is None


def _upsert_override_entries(
    existing_store: OverrideStore,
    incoming_entries: list[OverrideEntry],
    *,
    include_account_label_scope: bool,
) -> tuple[OverrideStore, int, int]:
    merged = list(existing_store.entries)
    updated = 0
    inserted = 0
    for incoming in incoming_entries:
        match_index = next(
            (
                index
                for index, entry in enumerate(merged)
                if _entry_matches(
                    entry,
                    incoming,
                    include_account_label_scope=include_account_label_scope,
                )
            ),
            None,
        )
        if match_index is None:
            merged.append(incoming)
            inserted += 1
            continue
        merged[match_index] = OverrideEntry(
            fingerprint=merged[match_index].fingerprint,
            category=incoming.category,
            subcategory=incoming.subcategory,
            bank=incoming.bank,
            account_label=incoming.account_label,
            hit_count=merged[match_index].hit_count,
        )
        updated += 1

    merged.sort(
        key=lambda entry: (
            entry.fingerprint,
            entry.bank or "",
            entry.account_label or "",
            entry.category,
            entry.subcategory or "",
        )
    )
    return OverrideStore(entries=tuple(merged)), updated, inserted


def _write_override_store(path: Path, store: OverrideStore) -> None:
    payload = {
        "version": 1,
        "overrides": [
            {
                "fingerprint": entry.fingerprint,
                "category": entry.category,
                "subcategory": entry.subcategory,
                "bank": entry.bank,
                "account_label": entry.account_label,
                "hit_count": entry.hit_count,
            }
            for entry in store.entries
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        return
    if suffix == ".json":
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return
    raise ValueError(f"Unsupported override format for {path}; expected .yaml, .yml, or .json")


def _default_backup_path(path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{path.name}.{timestamp}.bak")


def _backup_override_store(path: Path, backup_path: Path | None) -> Path | None:
    if not path.exists():
        return None
    destination = backup_path or _default_backup_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination


def import_review_into_overrides(
    *,
    review_path: Path,
    overrides_path: Path,
    existing_store: OverrideStore,
    transaction_overrides_path: Path | None = None,
    existing_transaction_store: TransactionOverrideStore | None = None,
    include_account_label_scope: bool,
    allow_non_fallback_import: bool = False,
    dry_run: bool = False,
    backup: bool = True,
    backup_path: Path | None = None,
    transaction_backup_path: Path | None = None,
) -> ReviewImportResult:
    """Import reviewed rows and upsert into override config."""
    dataframe = _read_table(review_path)
    missing_columns = [
        column for column in REQUIRED_REVIEW_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Review table missing required columns: {joined}")

    has_override_level_column = OVERRIDE_LEVEL_COLUMN in dataframe.columns
    has_project_tags_column = PROJECT_TAGS_COLUMN in dataframe.columns

    raw_rows = dataframe.to_dict(orient="records")
    parsed_category_entries: dict[tuple[str, str | None, str | None], OverrideEntry] = {}
    parsed_transaction_entries: dict[tuple[str, ...], TransactionOverrideEntry] = {}
    skipped_non_fallback_rows: set[int] = set()
    invalid_rows: set[int] = set()
    invalid_category_rows: set[int] = set()
    invalid_project_rows: set[int] = set()
    project_tags_applied = 0

    for index, row in enumerate(raw_rows):
        row_is_fallback = _is_fallback_category_source(row.get("category_source"))
        tags = (
            _normalize_project_tags(row.get(PROJECT_TAGS_COLUMN)) if has_project_tags_column else ()
        )
        category_requested = _has_category_override_request(
            row,
            has_override_level_column=has_override_level_column,
        )
        if not allow_non_fallback_import and not row_is_fallback and (category_requested or tags):
            skipped_non_fallback_rows.add(index)
            continue

        if category_requested:
            level = _resolve_override_level(
                row,
                has_override_level_column=has_override_level_column,
            )
            if level is None:
                invalid_rows.add(index)
                invalid_category_rows.add(index)
            elif level == "skip":
                pass
            elif level == "category_override":
                parsed_category = _parse_category_override_row(
                    row,
                    include_account_label_scope=include_account_label_scope,
                )
                if parsed_category is None:
                    invalid_rows.add(index)
                    invalid_category_rows.add(index)
                else:
                    dedupe_key = (
                        parsed_category.fingerprint,
                        parsed_category.bank,
                        parsed_category.account_label,
                    )
                    parsed_category_entries[dedupe_key] = parsed_category
            elif level == "transaction_override":
                parsed_transaction = _parse_category_transaction_override_row(row)
                if parsed_transaction is None:
                    invalid_rows.add(index)
                    invalid_category_rows.add(index)
                else:
                    dedupe_key = transaction_override_entry_key(parsed_transaction)
                    existing = parsed_transaction_entries.get(dedupe_key)
                    if existing is None:
                        parsed_transaction_entries[dedupe_key] = parsed_transaction
                    else:
                        parsed_transaction_entries[dedupe_key] = merge_transaction_override_entries(
                            existing,
                            parsed_transaction,
                        )

        if tags:
            parsed_project = _parse_project_transaction_override_row(row, tags)
            if parsed_project is None:
                invalid_rows.add(index)
                invalid_project_rows.add(index)
            else:
                dedupe_key = transaction_override_entry_key(parsed_project)
                existing = parsed_transaction_entries.get(dedupe_key)
                if existing is None:
                    parsed_transaction_entries[dedupe_key] = parsed_project
                else:
                    parsed_transaction_entries[dedupe_key] = merge_transaction_override_entries(
                        existing,
                        parsed_project,
                    )
                project_tags_applied += 1

    merged_store, updated, inserted = _upsert_override_entries(
        existing_store,
        list(parsed_category_entries.values()),
        include_account_label_scope=include_account_label_scope,
    )
    resolved_transaction_path = transaction_overrides_path or Path(
        "config/transaction_overrides.yaml"
    )
    tx_updated = 0
    tx_inserted = 0
    merged_transaction_store: TransactionOverrideStore | None = None
    if parsed_transaction_entries:
        transaction_store = existing_transaction_store
        if transaction_store is None:
            transaction_store, warnings = load_transaction_override_store(resolved_transaction_path)
            if warnings:
                joined = "; ".join(warnings)
                raise ValueError(f"Transaction override load warnings detected: {joined}")
        merged_transaction_store, tx_updated, tx_inserted = upsert_transaction_override_entries(
            transaction_store,
            list(parsed_transaction_entries.values()),
        )

    created_backup_path: Path | None = None
    created_transaction_backup_path: Path | None = None
    if not dry_run:
        if backup and (updated > 0 or inserted > 0):
            created_backup_path = _backup_override_store(overrides_path, backup_path)
        if updated > 0 or inserted > 0:
            _write_override_store(overrides_path, merged_store)
        if merged_transaction_store is not None and backup and (tx_updated > 0 or tx_inserted > 0):
            created_transaction_backup_path = _backup_override_store(
                resolved_transaction_path,
                transaction_backup_path,
            )
        if merged_transaction_store is not None and (tx_updated > 0 or tx_inserted > 0):
            write_transaction_override_store(
                resolved_transaction_path,
                merged_transaction_store,
            )

    skipped_rows = skipped_non_fallback_rows | invalid_rows
    return ReviewImportResult(
        rows_read=len(raw_rows),
        overrides_upserted=updated + inserted,
        overrides_updated=updated,
        overrides_inserted=inserted,
        transaction_overrides_upserted=tx_updated + tx_inserted,
        transaction_overrides_updated=tx_updated,
        transaction_overrides_inserted=tx_inserted,
        project_tags_applied=project_tags_applied,
        rows_skipped=len(skipped_rows),
        rows_skipped_non_fallback=len(skipped_non_fallback_rows),
        rows_skipped_invalid=len(invalid_rows),
        rows_skipped_invalid_category=len(invalid_category_rows),
        rows_skipped_invalid_project_tags=len(invalid_project_rows),
        backup_path=created_backup_path,
        transaction_backup_path=created_transaction_backup_path,
    )

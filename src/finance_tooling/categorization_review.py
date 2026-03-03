"""Manual categorization review export/import helpers."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from finance_tooling.classify import OverrideEntry, OverrideStore, normalize_description

REQUIRED_REVIEW_COLUMNS: tuple[str, ...] = (
    "description",
    "bank",
    "account_label",
    "category",
    "subcategory",
    "category_source",
)


@dataclass(frozen=True)
class ReviewImportResult:
    """Result metadata for review import/upsert."""

    rows_read: int
    overrides_upserted: int
    overrides_updated: int
    overrides_inserted: int
    rows_skipped: int
    rows_skipped_non_fallback: int
    rows_skipped_invalid: int
    backup_path: Path | None


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


def _is_fallback_category_source(value: object) -> bool:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return False
    return normalized.lower() == "fallback"


def export_fallback_review_rows(normalized_path: Path, review_output_path: Path) -> int:
    """Export fallback-classified rows for manual review."""
    dataframe = _read_table(normalized_path)
    missing_columns = [
        column for column in REQUIRED_REVIEW_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Input table missing required columns: {joined}")

    fallback_rows = dataframe.loc[
        dataframe["category_source"].astype(str).str.strip().str.lower() == "fallback"
    ].copy()
    _write_table(review_output_path, fallback_rows)
    return len(fallback_rows)


def _parse_review_row(
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
        merged[match_index] = replace(
            merged[match_index],
            category=incoming.category,
            subcategory=incoming.subcategory,
            bank=incoming.bank,
            account_label=incoming.account_label,
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
    include_account_label_scope: bool,
    allow_non_fallback_import: bool = False,
    dry_run: bool = False,
    backup: bool = True,
    backup_path: Path | None = None,
) -> ReviewImportResult:
    """Import reviewed rows and upsert into override config."""
    dataframe = _read_table(review_path)
    missing_columns = [
        column for column in REQUIRED_REVIEW_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Review table missing required columns: {joined}")

    raw_rows = dataframe[list(REQUIRED_REVIEW_COLUMNS)].to_dict(orient="records")
    parsed_entries: dict[tuple[str, str | None, str | None], OverrideEntry] = {}
    skipped_non_fallback = 0
    skipped_invalid = 0
    for row in raw_rows:
        if not allow_non_fallback_import and not _is_fallback_category_source(
            row.get("category_source")
        ):
            skipped_non_fallback += 1
            continue
        parsed = _parse_review_row(
            row,
            include_account_label_scope=include_account_label_scope,
        )
        if parsed is None:
            skipped_invalid += 1
            continue
        dedupe_key = (parsed.fingerprint, parsed.bank, parsed.account_label)
        parsed_entries[dedupe_key] = parsed

    merged_store, updated, inserted = _upsert_override_entries(
        existing_store,
        list(parsed_entries.values()),
        include_account_label_scope=include_account_label_scope,
    )
    created_backup_path: Path | None = None
    if not dry_run:
        if backup:
            created_backup_path = _backup_override_store(overrides_path, backup_path)
        _write_override_store(overrides_path, merged_store)

    skipped = skipped_non_fallback + skipped_invalid
    return ReviewImportResult(
        rows_read=len(raw_rows),
        overrides_upserted=updated + inserted,
        overrides_updated=updated,
        overrides_inserted=inserted,
        rows_skipped=skipped,
        rows_skipped_non_fallback=skipped_non_fallback,
        rows_skipped_invalid=skipped_invalid,
        backup_path=created_backup_path,
    )

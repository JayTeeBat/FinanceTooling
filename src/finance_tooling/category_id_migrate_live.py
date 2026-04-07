"""One-off live migration to durable category IDs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from finance_tooling.category_id_migration_audit import _resolve_row_category_ids
from finance_tooling.classify import (
    ClassificationRules,
    load_classification_rules,
    resolve_taxonomy_labels,
)
from finance_tooling.config import Settings, load_settings_from_env
from finance_tooling.store import write_canonical_dataframe
from finance_tooling.transaction_overrides import (
    TransactionOverrideStore,
    load_transaction_override_store,
    write_transaction_override_store,
)


def migrate_canonical_dataframe(
    dataframe: pd.DataFrame,
    *,
    rules: ClassificationRules,
) -> tuple[pd.DataFrame, int]:
    """Backfill durable and reporting category IDs into canonical rows."""
    migrated = dataframe.copy()
    if "category_id" not in migrated.columns:
        migrated["category_id"] = None
    if "reporting_category_id" not in migrated.columns:
        migrated["reporting_category_id"] = None

    updated_rows = 0
    for index in migrated.index:
        category = migrated.at[index, "category"] if "category" in migrated.columns else None
        subcategory = (
            migrated.at[index, "subcategory"] if "subcategory" in migrated.columns else None
        )
        current_category_id = migrated.at[index, "category_id"]
        resolved_category_id, reporting_category_id, resolution_source = _resolve_row_category_ids(
            current_category_id=str(current_category_id) if pd.notna(current_category_id) else None,
            category=str(category) if pd.notna(category) else None,
            subcategory=str(subcategory) if pd.notna(subcategory) else None,
            rules=rules,
        )
        if resolution_source == "unresolved_labels":
            migrated.at[index, "category_id"] = None
            migrated.at[index, "reporting_category_id"] = None
            continue

        resolved_category, resolved_subcategory = resolve_taxonomy_labels(
            reporting_category_id or resolved_category_id,
            rules=rules,
        )
        migrated.at[index, "category_id"] = resolved_category_id
        migrated.at[index, "reporting_category_id"] = reporting_category_id
        migrated.at[index, "category"] = resolved_category
        migrated.at[index, "subcategory"] = resolved_subcategory
        updated_rows += 1

    return migrated, updated_rows


def migrate_override_store(
    store: TransactionOverrideStore,
    *,
    rules: ClassificationRules,
) -> tuple[TransactionOverrideStore, int]:
    """Rewrite category-bearing override entries to durable category IDs."""
    migrated_entries = []
    updated_entries = 0
    for entry in store.entries:
        if not (entry.set_category_id or entry.set_category or entry.set_subcategory):
            migrated_entries.append(entry)
            continue

        resolved_category_id, _reporting_category_id, resolution_source = _resolve_row_category_ids(
            current_category_id=entry.category_id if entry.set_category_id else None,
            category=entry.category if entry.set_category else None,
            subcategory=entry.subcategory if entry.set_subcategory else None,
            rules=rules,
        )
        if resolution_source == "unresolved_labels" or resolved_category_id is None:
            raise ValueError(
                "Unresolved transaction override during category-id migration: "
                f"{entry.transaction_id or entry.override_id or entry.fingerprint or '<unknown>'}"
            )

        migrated_entries.append(
            replace(
                entry,
                category_id=resolved_category_id,
                set_category_id=True,
                category=None,
                set_category=False,
                subcategory=None,
                set_subcategory=False,
            )
        )
        updated_entries += 1

    return TransactionOverrideStore(
        entries=tuple(migrated_entries),
        entry_indexes_by_transaction_id=store.entry_indexes_by_transaction_id,
        entry_indexes_by_fingerprint=store.entry_indexes_by_fingerprint,
        fallback_entry_indexes=store.fallback_entry_indexes,
    ), updated_entries


def run_live_category_id_migration(settings: Settings) -> tuple[Path, Path, int, int]:
    """Rewrite the live canonical parquet and override store to durable IDs."""
    canonical = pd.read_parquet(settings.master_parquet_path)
    rules, rule_warnings = load_classification_rules(settings.category_rules_path)
    if rule_warnings:
        raise ValueError("; ".join(rule_warnings))
    overrides, override_warnings = load_transaction_override_store(
        settings.transaction_overrides_path
    )
    if override_warnings:
        raise ValueError("; ".join(override_warnings))

    migrated_canonical, updated_rows = migrate_canonical_dataframe(canonical, rules=rules)
    migrated_overrides, updated_entries = migrate_override_store(overrides, rules=rules)

    write_canonical_dataframe(settings.master_parquet_path, migrated_canonical)
    write_transaction_override_store(settings.transaction_overrides_path, migrated_overrides)
    return (
        settings.master_parquet_path,
        settings.transaction_overrides_path,
        updated_rows,
        updated_entries,
    )


def main() -> int:
    """Run the live category-id migration from current environment settings."""
    settings = load_settings_from_env()
    canonical_path, override_path, updated_rows, updated_entries = run_live_category_id_migration(
        settings
    )
    print(f"Migrated canonical parquet: {canonical_path} ({updated_rows} rows)")
    print(f"Migrated override store: {override_path} ({updated_entries} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

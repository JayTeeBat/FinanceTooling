"""Manual transaction review import helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from finance_tooling.categorization.classify import (
    load_classification_rules,
    resolve_category_id_from_labels,
)
from finance_tooling.categorization.transaction_overrides import (
    TransactionOverrideEntry,
    TransactionOverrideStore,
    load_transaction_override_store,
    merge_transaction_override_entries,
    transaction_override_entry_key,
    upsert_transaction_override_entries,
    write_transaction_override_store,
)
from finance_tooling.core.backup import BackupRunResult, create_stage_backup_run
from finance_tooling.core.config import load_settings_from_env
from finance_tooling.review.common import (
    ORIGINAL_CATEGORY_COLUMN,
    ORIGINAL_SUBCATEGORY_COLUMN,
    PROJECT_TAGS_COLUMN,
    REQUIRED_REVIEW_COLUMNS,
    REVIEW_COMMENT_COLUMN,
    REVIEWED_COLUMN,
    normalize_optional_text,
    normalize_project_tags,
    normalize_reviewed_value,
    read_table,
)
from finance_tooling.review.state import build_review_state_updates, upsert_review_state


@dataclass(frozen=True)
class ReviewImportResult:
    """Result metadata for review import/upsert."""

    rows_read: int = 0
    transaction_overrides_upserted: int = 0
    transaction_overrides_updated: int = 0
    transaction_overrides_inserted: int = 0
    project_tags_applied: int = 0
    review_state_upserted: int = 0
    review_state_updated: int = 0
    review_state_inserted: int = 0
    rows_skipped: int = 0
    rows_skipped_invalid: int = 0
    rows_skipped_invalid_category: int = 0
    rows_skipped_invalid_project_tags: int = 0
    rows_skipped_invalid_review_state: int = 0
    transaction_backup_path: Path | None = None
    backup_run: BackupRunResult | None = None


def _resolve_review_import_backup_run(
    *,
    review_path: Path,
    transaction_overrides_path: Path,
    review_state_path: Path | None,
    category_rules_path: Path | None,
) -> BackupRunResult:
    processed_dir = (
        review_state_path.parent.parent
        if review_state_path is not None
        else review_path.parent / "processed"
    )
    config_dir = transaction_overrides_path.parent
    config_targets = [
        category_rules_path or (config_dir / "category_rules.yaml"),
        config_dir / "project_rules.yaml",
        config_dir / "budget_targets.yaml",
        config_dir / "account_rules.yaml",
        config_dir / "project_overrides.yaml",
        transaction_overrides_path,
    ]
    return create_stage_backup_run(
        stage="review-import",
        command="review-import",
        processed_dir=processed_dir,
        config_targets=tuple(config_targets),
    )


def _resolve_category_rules_path(
    *,
    transaction_overrides_path: Path | None,
    category_rules_path: Path | None,
) -> Path | None:
    if category_rules_path is not None:
        return category_rules_path
    if transaction_overrides_path is not None:
        sibling_rules_path = transaction_overrides_path.parent / "category_rules.yaml"
        if sibling_rules_path.exists():
            return sibling_rules_path
    try:
        return load_settings_from_env().category_rules_path
    except Exception:
        return None


def _parse_category_transaction_override_row(
    row: dict[str, object],
    *,
    category_rules_path: Path | None,
) -> TransactionOverrideEntry | None:
    category = normalize_optional_text(row.get("category"))
    if category is None or category.lower() == "uncategorized":
        return None

    original_category = normalize_optional_text(row.get(ORIGINAL_CATEGORY_COLUMN))
    original_subcategory = normalize_optional_text(row.get(ORIGINAL_SUBCATEGORY_COLUMN))

    transaction_id = normalize_optional_text(row.get("transaction_id"))
    if transaction_id is None:
        return None

    subcategory = normalize_optional_text(row.get("subcategory"))
    original_category_id = normalize_optional_text(row.get("original_category_id"))
    if category == original_category and subcategory == original_subcategory:
        return None

    resolved_category_id = None
    if category_rules_path is not None:
        classification_rules, _warnings = load_classification_rules(category_rules_path)
        resolved_category_id = resolve_category_id_from_labels(
            category,
            subcategory,
            rules=classification_rules,
            prefer_active=True,
        )

    return TransactionOverrideEntry(
        override_id=None,
        transaction_id=transaction_id,
        fingerprint=None,
        booking_date=None,
        amount_native=None,
        currency=None,
        bank=None,
        account_label=None,
        category_id=resolved_category_id or original_category_id,
        set_category_id=resolved_category_id is not None,
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
    transaction_id = normalize_optional_text(row.get("transaction_id"))
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
        category_id=None,
        set_category_id=False,
        category=None,
        set_category=False,
        subcategory=None,
        set_subcategory=False,
        project=None,
        set_project=False,
        project_tags=tags,
        set_project_tags=True,
    )


def import_review_into_overrides(
    *,
    review_path: Path,
    transaction_overrides_path: Path | None = None,
    existing_transaction_store: TransactionOverrideStore | None = None,
    review_state_path: Path | None = None,
    category_rules_path: Path | None = None,
    dry_run: bool = False,
    backup: bool = True,
    backup_run: BackupRunResult | None = None,
) -> ReviewImportResult:
    """Import reviewed rows and upsert into transaction override config."""
    dataframe = read_table(review_path)
    missing_columns = [
        column for column in REQUIRED_REVIEW_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        joined = ", ".join(missing_columns)
        raise ValueError(f"Review table missing required columns: {joined}")

    resolved_transaction_path = transaction_overrides_path or Path(
        "config/transaction_overrides.yaml"
    )
    resolved_category_rules_path = _resolve_category_rules_path(
        transaction_overrides_path=(
            resolved_transaction_path if transaction_overrides_path is not None else None
        ),
        category_rules_path=category_rules_path,
    )

    raw_rows = dataframe.to_dict(orient="records")
    parsed_transaction_entries: dict[tuple[str, ...], TransactionOverrideEntry] = {}
    invalid_rows: set[int] = set()
    invalid_category_rows: set[int] = set()
    invalid_project_rows: set[int] = set()
    invalid_review_state_rows: set[int] = set()
    project_tags_applied = 0

    for index, row in enumerate(raw_rows):
        tags = normalize_project_tags(row.get(PROJECT_TAGS_COLUMN))
        category = normalize_optional_text(row.get("category"))
        subcategory = normalize_optional_text(row.get("subcategory"))

        if subcategory is not None and category is None:
            invalid_rows.add(index)
            invalid_category_rows.add(index)
        elif category is not None:
            parsed_transaction = _parse_category_transaction_override_row(
                row,
                category_rules_path=resolved_category_rules_path,
            )
            if parsed_transaction is None:
                original_category = normalize_optional_text(row.get(ORIGINAL_CATEGORY_COLUMN))
                original_subcategory = normalize_optional_text(row.get(ORIGINAL_SUBCATEGORY_COLUMN))
                if category != original_category or subcategory != original_subcategory:
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

        transaction_id = normalize_optional_text(row.get("transaction_id"))
        if transaction_id is None and (REVIEWED_COLUMN in row or REVIEW_COMMENT_COLUMN in row):
            reviewed = normalize_reviewed_value(row.get(REVIEWED_COLUMN))
            comment = normalize_optional_text(row.get(REVIEW_COMMENT_COLUMN))
            if reviewed or comment is not None:
                invalid_review_state_rows.add(index)

    created_backup_run = backup_run
    if not dry_run and backup and created_backup_run is None:
        created_backup_run = _resolve_review_import_backup_run(
            review_path=review_path,
            transaction_overrides_path=resolved_transaction_path,
            review_state_path=review_state_path,
            category_rules_path=category_rules_path,
        )
    tx_updated = 0
    tx_inserted = 0
    review_state_upserted = 0
    review_state_updated = 0
    review_state_inserted = 0
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

    review_state_updates = build_review_state_updates(
        raw_rows,
        reviewed_column=REVIEWED_COLUMN,
        review_comment_column=REVIEW_COMMENT_COLUMN,
    )
    if not dry_run and review_state_path is not None and not review_state_updates.empty:
        review_state_result = upsert_review_state(review_state_path, review_state_updates)
        review_state_upserted = review_state_result.rows_upserted
        review_state_updated = review_state_result.rows_updated
        review_state_inserted = review_state_result.rows_inserted
    elif dry_run and review_state_path is not None:
        review_state_upserted = len(review_state_updates)

    if not dry_run:
        if merged_transaction_store is not None and (tx_updated > 0 or tx_inserted > 0):
            write_transaction_override_store(
                resolved_transaction_path,
                merged_transaction_store,
            )

    skipped_rows = invalid_rows | invalid_review_state_rows
    return ReviewImportResult(
        rows_read=len(raw_rows),
        transaction_overrides_upserted=tx_updated + tx_inserted,
        transaction_overrides_updated=tx_updated,
        transaction_overrides_inserted=tx_inserted,
        project_tags_applied=project_tags_applied,
        review_state_upserted=review_state_upserted,
        review_state_updated=review_state_updated,
        review_state_inserted=review_state_inserted,
        rows_skipped=len(skipped_rows),
        rows_skipped_invalid=len(invalid_rows),
        rows_skipped_invalid_category=len(invalid_category_rows),
        rows_skipped_invalid_project_tags=len(invalid_project_rows),
        rows_skipped_invalid_review_state=len(invalid_review_state_rows),
        transaction_backup_path=(
            created_backup_run.snapshot_dir if created_backup_run is not None else None
        ),
        backup_run=created_backup_run,
    )

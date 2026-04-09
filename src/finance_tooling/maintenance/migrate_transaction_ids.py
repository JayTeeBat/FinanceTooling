"""One-off migration helpers for transaction identity changes."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.categorization.classify import normalize_description
from finance_tooling.categorization.transaction_overrides import (
    TransactionOverrideEntry,
    TransactionOverrideStore,
    load_transaction_override_store,
    upsert_transaction_override_entries,
    write_transaction_override_store,
)
from finance_tooling.core.models import Transaction
from finance_tooling.core.store import (
    compute_legacy_transaction_id,
    compute_path_based_transaction_id,
    compute_transaction_id,
)
from finance_tooling.review.state import REVIEW_STATE_COLUMNS, load_review_state
from finance_tooling.workflow.staging import read_staged_transactions


@dataclass(frozen=True)
class TransactionIdMigrationResult:
    """Result metadata for transaction id migration."""

    report_path: Path
    transaction_overrides_path: Path
    review_state_path: Path
    unmigrated_overrides_path: Path
    unmigrated_review_state_path: Path
    backup_dir: Path | None
    migrated_override_count: int
    skipped_override_ambiguous_count: int
    skipped_override_unmatched_count: int
    migrated_review_state_count: int
    skipped_review_state_ambiguous_count: int
    skipped_review_state_unmatched_count: int


def _backup_file(path: Path, backup_dir: Path | None) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    destination_dir = backup_dir or path.parent / f"transaction_id_migration_backup_{timestamp}"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / path.name
    shutil.copy2(path, destination)
    return destination_dir


def _transaction_selector_matches(
    entry: TransactionOverrideEntry,
    transaction: Transaction,
) -> bool:
    fingerprint = normalize_description(transaction.description)
    if entry.fingerprint is not None and entry.fingerprint != fingerprint:
        return False
    if entry.booking_date is not None and entry.booking_date != transaction.booking_date:
        return False
    if entry.amount_native is not None and entry.amount_native != transaction.amount_native:
        return False
    if entry.currency is not None and entry.currency != transaction.currency.strip().upper():
        return False
    if entry.bank is not None and entry.bank != transaction.bank.strip().upper():
        return False
    normalized_account = (transaction.account_label or "").strip().upper() or None
    if entry.account_label is not None and entry.account_label != normalized_account:
        return False
    return any(
        (
            entry.fingerprint is not None,
            entry.booking_date is not None,
            entry.amount_native is not None,
            entry.currency is not None,
            entry.bank is not None,
            entry.account_label is not None,
        )
    )


def _write_review_state(path: Path, dataframe: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.parquet")
    dataframe.to_parquet(temp_path, index=False)
    temp_path.replace(path)


def migrate_transaction_ids(
    *,
    staged_path: Path,
    transaction_overrides_path: Path,
    review_state_path: Path,
    report_path: Path,
    unmigrated_overrides_path: Path,
    unmigrated_review_state_path: Path,
    backup: bool = True,
    backup_dir: Path | None = None,
) -> TransactionIdMigrationResult:
    """Migrate transaction-id keyed manual state to the current id formula."""
    staged_transactions = read_staged_transactions(staged_path)
    legacy_to_new: dict[str, list[str]] = {}
    for transaction in staged_transactions:
        legacy_id = compute_legacy_transaction_id(transaction)
        old_current_id = compute_path_based_transaction_id(transaction)
        new_id = compute_transaction_id(transaction)
        legacy_to_new.setdefault(legacy_id, []).append(new_id)
        legacy_to_new.setdefault(old_current_id, []).append(new_id)

    transaction_store, transaction_warnings = load_transaction_override_store(
        transaction_overrides_path
    )
    if transaction_warnings:
        joined = "; ".join(transaction_warnings)
        raise ValueError(f"Transaction override load warnings detected: {joined}")

    backup_root: Path | None = None
    if backup:
        backup_root = _backup_file(transaction_overrides_path, backup_dir)
        review_backup_root = _backup_file(review_state_path, backup_root)
        if backup_root is None:
            backup_root = review_backup_root

    migrated_entries: list[TransactionOverrideEntry] = []
    unmigrated_entries: list[TransactionOverrideEntry] = []
    skipped_override_ambiguous_count = 0
    skipped_override_unmatched_count = 0

    for entry in transaction_store.entries:
        if entry.transaction_id is None:
            migrated_entries.append(entry)
            continue

        candidate_ids = legacy_to_new.get(entry.transaction_id, [])
        if len(candidate_ids) == 1:
            migrated_entries.append(replace(entry, transaction_id=candidate_ids[0]))
            continue

        selector_matches = [
            compute_transaction_id(transaction)
            for transaction in staged_transactions
            if _transaction_selector_matches(entry, transaction)
        ]
        selector_match_ids = sorted(set(selector_matches))
        if len(selector_match_ids) == 1:
            migrated_entries.append(replace(entry, transaction_id=selector_match_ids[0]))
            continue

        unmigrated_entries.append(entry)
        if candidate_ids or selector_match_ids:
            skipped_override_ambiguous_count += 1
        else:
            skipped_override_unmatched_count += 1

    migrated_store, _updated, _inserted = upsert_transaction_override_entries(
        TransactionOverrideStore(entries=()),
        migrated_entries,
    )
    write_transaction_override_store(transaction_overrides_path, migrated_store)
    write_transaction_override_store(
        unmigrated_overrides_path,
        TransactionOverrideStore(entries=tuple(unmigrated_entries)),
    )

    review_state = load_review_state(review_state_path)
    migrated_review_rows: list[dict[str, object]] = []
    unmigrated_review_rows: list[dict[str, object]] = []
    migrated_review_state_count = 0
    skipped_review_state_ambiguous_count = 0
    skipped_review_state_unmatched_count = 0

    for row in review_state.to_dict(orient="records"):
        old_id = str(row["transaction_id"])
        candidate_ids = legacy_to_new.get(old_id, [])
        if len(candidate_ids) == 1:
            migrated_review_rows.append(
                {
                    "transaction_id": candidate_ids[0],
                    "reviewed": row["reviewed"],
                    "review_comment": row["review_comment"],
                    "updated_at": row["updated_at"],
                }
            )
            migrated_review_state_count += 1
            continue

        unmigrated_review_rows.append(
            {
                "transaction_id": old_id,
                "candidate_new_ids": "|".join(candidate_ids),
                "reviewed": row["reviewed"],
                "review_comment": row["review_comment"],
                "updated_at": row["updated_at"],
            }
        )
        if candidate_ids:
            skipped_review_state_ambiguous_count += 1
        else:
            skipped_review_state_unmatched_count += 1

    migrated_review_state = pd.DataFrame(
        migrated_review_rows,
        columns=list(REVIEW_STATE_COLUMNS),
    )
    if migrated_review_state.empty:
        migrated_review_state = pd.DataFrame(columns=list(REVIEW_STATE_COLUMNS))
    _write_review_state(review_state_path, migrated_review_state)

    pd.DataFrame(unmigrated_review_rows).to_csv(unmigrated_review_state_path, index=False)

    report_payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "staged_path": str(staged_path),
        "transaction_overrides_path": str(transaction_overrides_path),
        "review_state_path": str(review_state_path),
        "unmigrated_overrides_path": str(unmigrated_overrides_path),
        "unmigrated_review_state_path": str(unmigrated_review_state_path),
        "backup_dir": str(backup_root) if backup_root is not None else None,
        "migrated_override_count": len(migrated_store.entries)
        - len([entry for entry in migrated_store.entries if entry.transaction_id is None]),
        "skipped_override_ambiguous_count": skipped_override_ambiguous_count,
        "skipped_override_unmatched_count": skipped_override_unmatched_count,
        "migrated_review_state_count": migrated_review_state_count,
        "skipped_review_state_ambiguous_count": skipped_review_state_ambiguous_count,
        "skipped_review_state_unmatched_count": skipped_review_state_unmatched_count,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return TransactionIdMigrationResult(
        report_path=report_path,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=review_state_path,
        unmigrated_overrides_path=unmigrated_overrides_path,
        unmigrated_review_state_path=unmigrated_review_state_path,
        backup_dir=backup_root,
        migrated_override_count=report_payload["migrated_override_count"],
        skipped_override_ambiguous_count=skipped_override_ambiguous_count,
        skipped_override_unmatched_count=skipped_override_unmatched_count,
        migrated_review_state_count=migrated_review_state_count,
        skipped_review_state_ambiguous_count=skipped_review_state_ambiguous_count,
        skipped_review_state_unmatched_count=skipped_review_state_unmatched_count,
    )

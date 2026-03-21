import importlib.util
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from finance_tooling.migrate_transaction_ids import migrate_transaction_ids
from finance_tooling.models import Transaction
from finance_tooling.store import (
    compute_legacy_transaction_id,
    compute_path_based_transaction_id,
    compute_transaction_id,
)
from finance_tooling.transaction_overrides import (
    TransactionOverrideEntry,
    TransactionOverrideStore,
    load_transaction_override_store,
    write_transaction_override_store,
)
from finance_tooling.workflow.staging import write_staged_transactions

HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None
pytestmark = pytest.mark.skipif(not HAS_PYARROW, reason="pyarrow is required")


def _sample_transaction(source: Path, *, source_record_index: int) -> Transaction:
    return Transaction(
        booking_date=date(2026, 1, 2),
        description="Coffee shop",
        amount_native=Decimal("-4.50"),
        currency="EUR",
        source_file=source,
        bank="REVOLUT",
        parser="revolut",
        source_record_index=source_record_index,
    )


def test_migrate_transaction_ids_rewrites_unique_id_based_state(tmp_path: Path) -> None:
    source = tmp_path / "statement.pdf"
    source.write_text("x", encoding="utf-8")
    staged_path = tmp_path / "staged_transactions.parquet"
    transaction_overrides_path = tmp_path / "transaction_overrides.yaml"
    review_state_path = tmp_path / "review_state.parquet"
    report_path = tmp_path / "migration_report.json"
    unmigrated_overrides_path = tmp_path / "transaction_overrides_unmigrated.yaml"
    unmigrated_review_state_path = tmp_path / "review_state_unmigrated.csv"

    transaction = _sample_transaction(source, source_record_index=0)
    write_staged_transactions(staged_path, [transaction])

    old_id = compute_legacy_transaction_id(transaction)
    new_id = compute_transaction_id(transaction)
    write_transaction_override_store(
        transaction_overrides_path,
        TransactionOverrideStore(
            entries=(
                TransactionOverrideEntry(
                    override_id=None,
                    transaction_id=old_id,
                    fingerprint=None,
                    booking_date=None,
                    amount_native=None,
                    currency=None,
                    bank=None,
                    account_label=None,
                    category="Food",
                    set_category=True,
                    subcategory="Coffee",
                    set_subcategory=True,
                    project=None,
                    set_project=False,
                    project_tags=(),
                    set_project_tags=False,
                ),
            )
        ),
    )
    pd.DataFrame(
        [
            {
                "transaction_id": old_id,
                "reviewed": True,
                "review_comment": "done",
                "updated_at": "2026-03-08T10:00:00+00:00",
            }
        ]
    ).to_parquet(review_state_path, index=False)

    result = migrate_transaction_ids(
        staged_path=staged_path,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=review_state_path,
        report_path=report_path,
        unmigrated_overrides_path=unmigrated_overrides_path,
        unmigrated_review_state_path=unmigrated_review_state_path,
    )

    migrated_store, warnings = load_transaction_override_store(transaction_overrides_path)
    assert warnings == []
    assert len(migrated_store.entries) == 1
    assert migrated_store.entries[0].transaction_id == new_id
    migrated_review_state = pd.read_parquet(review_state_path)
    assert migrated_review_state.loc[0, "transaction_id"] == new_id
    assert result.migrated_override_count == 1
    assert result.migrated_review_state_count == 1


def test_migrate_transaction_ids_rewrites_path_based_current_ids(tmp_path: Path) -> None:
    source = tmp_path / "statement.pdf"
    source.write_text("x", encoding="utf-8")
    staged_path = tmp_path / "staged_transactions.parquet"
    transaction_overrides_path = tmp_path / "transaction_overrides.yaml"
    review_state_path = tmp_path / "review_state.parquet"
    report_path = tmp_path / "migration_report.json"
    unmigrated_overrides_path = tmp_path / "transaction_overrides_unmigrated.yaml"
    unmigrated_review_state_path = tmp_path / "review_state_unmigrated.csv"

    transaction = replace(
        _sample_transaction(source, source_record_index=0),
        source_document_id="doc-123",
    )
    write_staged_transactions(staged_path, [transaction])

    old_id = compute_path_based_transaction_id(replace(transaction, source_document_id=None))
    new_id = compute_transaction_id(transaction)
    write_transaction_override_store(
        transaction_overrides_path,
        TransactionOverrideStore(
            entries=(
                TransactionOverrideEntry(
                    override_id=None,
                    transaction_id=old_id,
                    fingerprint=None,
                    booking_date=None,
                    amount_native=None,
                    currency=None,
                    bank=None,
                    account_label=None,
                    category="Food",
                    set_category=True,
                    subcategory="Coffee",
                    set_subcategory=True,
                    project=None,
                    set_project=False,
                    project_tags=(),
                    set_project_tags=False,
                ),
            )
        ),
    )
    pd.DataFrame(
        [
            {
                "transaction_id": old_id,
                "reviewed": True,
                "review_comment": "done",
                "updated_at": "2026-03-08T10:00:00+00:00",
            }
        ]
    ).to_parquet(review_state_path, index=False)

    result = migrate_transaction_ids(
        staged_path=staged_path,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=review_state_path,
        report_path=report_path,
        unmigrated_overrides_path=unmigrated_overrides_path,
        unmigrated_review_state_path=unmigrated_review_state_path,
    )

    migrated_store, warnings = load_transaction_override_store(transaction_overrides_path)
    assert warnings == []
    assert migrated_store.entries[0].transaction_id == new_id
    migrated_review_state = pd.read_parquet(review_state_path)
    assert migrated_review_state.loc[0, "transaction_id"] == new_id
    assert result.migrated_override_count == 1
    assert result.migrated_review_state_count == 1


def test_migrate_transaction_ids_skips_ambiguous_split_rows(tmp_path: Path) -> None:
    source = tmp_path / "statement.pdf"
    source.write_text("x", encoding="utf-8")
    staged_path = tmp_path / "staged_transactions.parquet"
    transaction_overrides_path = tmp_path / "transaction_overrides.yaml"
    review_state_path = tmp_path / "review_state.parquet"
    report_path = tmp_path / "migration_report.json"
    unmigrated_overrides_path = tmp_path / "transaction_overrides_unmigrated.yaml"
    unmigrated_review_state_path = tmp_path / "review_state_unmigrated.csv"

    first = _sample_transaction(source, source_record_index=0)
    second = replace(first, source_record_index=1)
    write_staged_transactions(staged_path, [first, second])

    old_id = compute_legacy_transaction_id(first)
    write_transaction_override_store(
        transaction_overrides_path,
        TransactionOverrideStore(
            entries=(
                TransactionOverrideEntry(
                    override_id=None,
                    transaction_id=old_id,
                    fingerprint=None,
                    booking_date=None,
                    amount_native=None,
                    currency=None,
                    bank=None,
                    account_label=None,
                    category="Food",
                    set_category=True,
                    subcategory="Coffee",
                    set_subcategory=True,
                    project=None,
                    set_project=False,
                    project_tags=(),
                    set_project_tags=False,
                ),
            )
        ),
    )
    pd.DataFrame(
        [
            {
                "transaction_id": old_id,
                "reviewed": True,
                "review_comment": "done",
                "updated_at": "2026-03-08T10:00:00+00:00",
            }
        ]
    ).to_parquet(review_state_path, index=False)

    result = migrate_transaction_ids(
        staged_path=staged_path,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=review_state_path,
        report_path=report_path,
        unmigrated_overrides_path=unmigrated_overrides_path,
        unmigrated_review_state_path=unmigrated_review_state_path,
    )

    migrated_store, warnings = load_transaction_override_store(transaction_overrides_path)
    assert warnings == []
    assert len(migrated_store.entries) == 0
    skipped_store, skipped_warnings = load_transaction_override_store(unmigrated_overrides_path)
    assert skipped_warnings == []
    assert len(skipped_store.entries) == 1
    assert result.skipped_override_ambiguous_count == 1
    skipped_review_state = pd.read_csv(unmigrated_review_state_path)
    assert skipped_review_state.loc[0, "transaction_id"] == old_id
    assert result.skipped_review_state_ambiguous_count == 1

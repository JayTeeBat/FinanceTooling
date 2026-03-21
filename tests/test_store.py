import importlib.util
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finance_tooling.models import Transaction
from finance_tooling.store import (
    compute_legacy_transaction_id,
    compute_path_based_transaction_id,
    compute_transaction_id,
    upsert_transactions,
)

HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None
pytestmark = pytest.mark.skipif(not HAS_PYARROW, reason="pyarrow is required")


def _sample_transaction(source: Path) -> Transaction:
    return Transaction(
        booking_date=date(2026, 1, 2),
        description="Salary payment",
        amount_native=Decimal("1000.00"),
        currency="EUR",
        source_file=source,
        bank="Boursobank",
        parser="boursobank",
        amount_eur=Decimal("1000.00"),
        source_file_mtime=datetime.now(UTC),
    )


def test_compute_transaction_id_is_stable(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_text("x", encoding="utf-8")
    tx = _sample_transaction(source)

    assert compute_transaction_id(tx) == compute_transaction_id(tx)


def test_compute_transaction_id_uses_source_record_index(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_text("x", encoding="utf-8")
    tx_a = replace(_sample_transaction(source), source_record_index=0)
    tx_b = replace(_sample_transaction(source), source_record_index=1)

    assert compute_transaction_id(tx_a) != compute_transaction_id(tx_b)
    assert compute_legacy_transaction_id(tx_a) == compute_legacy_transaction_id(tx_b)


def test_compute_transaction_id_uses_source_document_id_over_path(tmp_path: Path) -> None:
    original_source = tmp_path / "sample.pdf"
    renamed_source = tmp_path / "renamed.pdf"
    original_source.write_text("x", encoding="utf-8")
    renamed_source.write_text("x", encoding="utf-8")

    original = replace(
        _sample_transaction(original_source),
        source_document_id="doc-123",
    )
    renamed = replace(
        _sample_transaction(renamed_source),
        source_document_id="doc-123",
    )

    assert compute_transaction_id(original) == compute_transaction_id(renamed)
    assert compute_path_based_transaction_id(original) != compute_path_based_transaction_id(renamed)


def test_upsert_transactions_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_text("x", encoding="utf-8")
    parquet_path = tmp_path / "transactions_master.parquet"

    tx = _sample_transaction(source)
    first = upsert_transactions(parquet_path, [tx])
    second = upsert_transactions(parquet_path, [tx])

    assert first.new_rows == 1
    assert second.new_rows == 0
    assert second.total_rows == 1


def test_upsert_transactions_replaces_existing_row_and_preserves_ingested_at(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.pdf"
    source.write_text("x", encoding="utf-8")
    parquet_path = tmp_path / "transactions_master.parquet"

    initial = _sample_transaction(source)
    first = upsert_transactions(parquet_path, [initial])
    original_ingested_at = first.dataframe.loc[0, "ingested_at"]

    updated = replace(
        initial,
        category="House",
        subcategory="Cleaning",
        category_confidence=1.0,
        category_source="transaction_override",
    )
    second = upsert_transactions(parquet_path, [updated])

    assert second.new_rows == 0
    assert second.total_rows == 1
    assert second.dataframe.loc[0, "category"] == "House"
    assert second.dataframe.loc[0, "subcategory"] == "Cleaning"
    assert second.dataframe.loc[0, "category_source"] == "transaction_override"
    assert second.dataframe.loc[0, "ingested_at"] == original_ingested_at


def test_upsert_transactions_replaces_rows_by_source_file_when_ids_change(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_text("x", encoding="utf-8")
    parquet_path = tmp_path / "transactions_master.parquet"

    initial = _sample_transaction(source)
    first = upsert_transactions(parquet_path, [initial])
    assert first.total_rows == 1

    changed_description = replace(initial, description="Salary payment updated")
    second = upsert_transactions(parquet_path, [changed_description])

    assert second.total_rows == 1
    assert second.new_rows == 1
    assert second.dataframe.loc[0, "description"] == "Salary payment updated"


def test_upsert_transactions_replaces_rows_by_source_document_id_across_path_change(
    tmp_path: Path,
) -> None:
    original_source = tmp_path / "sample.pdf"
    renamed_source = tmp_path / "renamed.pdf"
    original_source.write_text("x", encoding="utf-8")
    renamed_source.write_text("x", encoding="utf-8")
    parquet_path = tmp_path / "transactions_master.parquet"

    initial = replace(_sample_transaction(original_source), source_document_id="doc-123")
    first = upsert_transactions(parquet_path, [initial])
    assert first.total_rows == 1

    renamed = replace(
        initial,
        source_file=renamed_source,
        source_document_id="doc-123",
        description="Salary payment updated",
    )
    second = upsert_transactions(parquet_path, [renamed])

    assert second.total_rows == 1
    assert second.dataframe.loc[0, "source_file"] == str(renamed_source)
    assert second.dataframe.loc[0, "description"] == "Salary payment updated"


def test_upsert_transactions_keeps_repeated_rows_with_distinct_source_record_index(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.pdf"
    source.write_text("x", encoding="utf-8")
    parquet_path = tmp_path / "transactions_master.parquet"

    first = replace(_sample_transaction(source), source_record_index=0)
    second = replace(_sample_transaction(source), source_record_index=1)

    result = upsert_transactions(parquet_path, [first, second])

    assert result.total_rows == 2
    assert result.new_rows == 2

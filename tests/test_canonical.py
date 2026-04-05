import importlib.util
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from finance_tooling.canonical import (
    CANONICAL_TRANSACTION_COLUMNS,
    CanonicalTransaction,
    canonical_dataframe_from_transactions,
    canonical_transaction_from_enriched,
    canonical_transactions_from_dataframe,
    ensure_canonical_dataframe_schema,
)
from finance_tooling.models import Transaction
from finance_tooling.store import compute_transaction_id

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
        category="Income",
        subcategory="Salary",
        category_confidence=1.0,
        category_source="rule",
        category_rule_id="income.salary",
        cashflow_type="in",
        project="Core",
        project_tags=("salary", "monthly"),
        project_source="rule",
        reviewed=True,
        account_label="Main",
        source_document_id="doc-123",
        fx_rate_to_eur=Decimal("1.00"),
        fx_rate_date=date(2026, 1, 2),
        fx_source="ECB",
        amount_eur=Decimal("1000.00"),
        source_record_index=0,
        source_file_mtime=datetime(2026, 1, 2, tzinfo=UTC),
    )


def test_canonical_transaction_round_trip_from_enriched_transaction(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_text("x", encoding="utf-8")
    transaction = _sample_transaction(source)
    ingested_at = datetime(2026, 1, 3, tzinfo=UTC)

    canonical = canonical_transaction_from_enriched(
        transaction,
        transaction_id=compute_transaction_id(transaction),
        ingested_at=ingested_at,
    )

    assert isinstance(canonical, CanonicalTransaction)
    frame = canonical_dataframe_from_transactions([canonical])
    restored = canonical_transactions_from_dataframe(frame)

    assert restored == [canonical]
    assert list(frame.columns) == list(CANONICAL_TRANSACTION_COLUMNS)


def test_ensure_canonical_dataframe_schema_backfills_missing_columns() -> None:
    frame = pd.DataFrame(
        [
            {
                "transaction_id": "tx-1",
                "booking_date": "2026-01-02",
                "description": "Salary payment",
                "amount_native": 1000.0,
                "currency": "EUR",
                "bank": "Boursobank",
                "source_file": "/tmp/sample.pdf",
                "parser": "boursobank",
            }
        ]
    )

    normalized = ensure_canonical_dataframe_schema(frame)

    assert list(normalized.columns) == list(CANONICAL_TRANSACTION_COLUMNS)
    assert normalized.loc[0, "cashflow_type"] is None

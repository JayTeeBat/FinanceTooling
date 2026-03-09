from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from finance_tooling.models import Transaction
from finance_tooling.workflow.staging import read_staged_transactions, write_staged_transactions


def test_staging_roundtrip_preserves_transaction_fields(tmp_path: Path) -> None:
    staged_path = tmp_path / "staged_transactions.parquet"
    source_file = tmp_path / "statement.pdf"
    source_file.write_text("fake", encoding="utf-8")

    transaction = Transaction(
        booking_date=date(2024, 5, 6),
        description="Card payment",
        amount_native=Decimal("-10.25"),
        currency="EUR",
        source_file=source_file,
        bank="DummyBank",
        parser="dummy",
        category="Food",
        subcategory="Groceries",
        category_confidence=0.9,
        category_source="rule",
        category_rule_id="food_rule",
        project="ProjectAtlas",
        project_tags=("ProjectAtlas", "Family"),
        project_source="project_rule",
        account_label="Main",
        fx_rate_to_eur=Decimal("1.0"),
        fx_rate_date=date(2024, 5, 6),
        fx_source="BASE",
        amount_eur=Decimal("-10.25"),
        source_record_index=7,
        source_file_mtime=datetime.fromisoformat("2024-05-06T12:34:56+00:00"),
    )

    write_staged_transactions(staged_path, [transaction])
    loaded = read_staged_transactions(staged_path)

    assert len(loaded) == 1
    assert loaded[0] == transaction


def test_read_staged_transactions_validates_required_columns(tmp_path: Path) -> None:
    staged_path = tmp_path / "staged_transactions.parquet"
    dataframe = pd.DataFrame(
        [
            {
                "booking_date": "2024-05-06",
                "description": "Card payment",
                "amount_native": "-10.25",
                "currency": "EUR",
                "source_file": str(tmp_path / "statement.pdf"),
                "bank": "DummyBank",
            }
        ]
    )
    dataframe.to_parquet(staged_path, index=False)

    try:
        read_staged_transactions(staged_path)
    except ValueError as exc:
        message = str(exc)
        assert "missing columns" in message
        assert "parser" in message
    else:
        raise AssertionError("Expected ValueError for missing staged columns.")

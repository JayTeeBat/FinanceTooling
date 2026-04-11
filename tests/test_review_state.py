from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from finance_tooling.core.models import Transaction
from finance_tooling.core.store import compute_transaction_id
from finance_tooling.review.state import (
    apply_review_state,
    build_review_state_updates,
    load_review_state,
    upsert_review_state,
)


def test_upsert_and_load_review_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "review_state.parquet"
    updates = pd.DataFrame(
        [
            {
                "transaction_id": "tx-1",
                "review_status": "needs_rule",
                "reviewed": True,
                "review_comment": "checked",
                "updated_at": "2026-03-07T10:00:00+00:00",
            }
        ]
    )

    result = upsert_review_state(path, updates)

    assert result.rows_upserted == 1
    assert result.rows_inserted == 1
    loaded = load_review_state(path)
    assert loaded.loc[0, "transaction_id"] == "tx-1"
    assert loaded.loc[0, "review_status"] == "needs_rule"
    assert bool(loaded.loc[0, "reviewed"])
    assert loaded.loc[0, "review_comment"] == "checked"


def test_apply_review_state_marks_matching_transactions_reviewed(tmp_path: Path) -> None:
    review_state_path = tmp_path / "review_state.parquet"
    transaction = Transaction(
        booking_date=date(2026, 1, 2),
        description="Merchant 123",
        amount_native=Decimal("-12.34"),
        currency="EUR",
        source_file=tmp_path / "statement.pdf",
        bank="REVOLUT",
        parser="revolut",
    )
    transaction.source_file.write_text("fake", encoding="utf-8")
    transaction_id = compute_transaction_id(transaction)
    upsert_review_state(
        review_state_path,
        pd.DataFrame(
            [
                {
                    "transaction_id": transaction_id,
                    "reviewed": True,
                    "review_comment": "done",
                    "updated_at": "2026-03-07T10:00:00+00:00",
                }
            ]
        ),
    )

    updated = apply_review_state([transaction], review_state_path)

    assert len(updated) == 1
    assert updated[0].reviewed is True


def test_apply_review_state_preserves_source_document_id(tmp_path: Path) -> None:
    review_state_path = tmp_path / "review_state.parquet"
    transaction = Transaction(
        booking_date=date(2026, 1, 2),
        description="Merchant 123",
        amount_native=Decimal("-12.34"),
        currency="EUR",
        source_file=tmp_path / "statement.pdf",
        bank="REVOLUT",
        parser="revolut",
        source_document_id="doc-123",
    )
    transaction.source_file.write_text("fake", encoding="utf-8")
    transaction_id = compute_transaction_id(transaction)
    upsert_review_state(
        review_state_path,
        pd.DataFrame(
            [
                {
                    "transaction_id": transaction_id,
                    "reviewed": True,
                    "review_comment": "done",
                    "updated_at": "2026-03-07T10:00:00+00:00",
                }
            ]
        ),
    )

    updated = apply_review_state([transaction], review_state_path)

    assert len(updated) == 1
    assert updated[0].source_document_id == "doc-123"


def test_build_review_state_updates_skips_rows_without_transaction_id() -> None:
    updates = build_review_state_updates(
        [
            {
                "transaction_id": "tx-1",
                "review_status": "needs_rule",
                "reviewed": True,
                "review_comment": "keep",
            },
            {"transaction_id": None, "reviewed": True, "review_comment": "skip"},
        ],
        reviewed_column="reviewed",
        review_comment_column="review_comment",
        review_status_column="review_status",
    )

    assert updates["transaction_id"].tolist() == ["tx-1"]
    assert updates["review_status"].tolist() == ["needs_rule"]

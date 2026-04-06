from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from finance_tooling.canonical import canonical_dataframe_from_transactions
from finance_tooling.cashflow import (
    build_cashflow_yoy_summary,
    resolve_cashflow_types_for_dataframe,
)
from finance_tooling.classify import ClassificationRules, TaxonomyCategory
from finance_tooling.models import Transaction
from finance_tooling.store import canonicalize_transactions
from finance_tooling.transaction_overrides import load_transaction_override_store


def _rules() -> ClassificationRules:
    return ClassificationRules(
        rules=(),
        taxonomy={
            "income": TaxonomyCategory(
                name="Income",
                subcategories=("Salary",),
                cashflow_type="in",
            ),
            "shopping": TaxonomyCategory(
                name="Shopping",
                subcategories=("General Retail",),
                cashflow_type="out",
            ),
            "transfers": TaxonomyCategory(
                name="Transfers",
                subcategories=("Bank Transfer",),
                cashflow_type="transfer",
            ),
            "non personal transactions": TaxonomyCategory(
                name="Non Personal Transactions",
                subcategories=(),
                cashflow_type="exclude",
            ),
        },
    )


def _dataframe_for(tx: Transaction):
    return canonical_dataframe_from_transactions(
        canonicalize_transactions([tx], ingested_at=datetime(2026, 4, 6, tzinfo=UTC))
    )


def test_resolve_cashflow_types_internal_to_internal_becomes_transfer(tmp_path: Path) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Move to savings",
        amount_native=Decimal("-250.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Shopping",
        from_account_type="internal",
        to_account_type="internal",
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text("overrides: []\n", encoding="utf-8")
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "transfer"
    assert result.account_transfer_override_count == 1
    assert result.account_transfer_conflict_count == 1


def test_resolve_cashflow_types_explicit_override_beats_internal_transfer(tmp_path: Path) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Move to savings",
        amount_native=Decimal("-250.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Shopping",
        from_account_type="internal",
        to_account_type="internal",
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text(
        "\n".join(
            [
                "overrides:",
                "  - match:",
                "      booking_date: '2026-01-03'",
                "      amount_native: -250.00",
                "      currency: EUR",
                "      bank: HSBC",
                "    cashflow_type: out",
            ]
        ),
        encoding="utf-8",
    )
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "out"
    assert result.account_transfer_override_count == 0
    assert result.account_transfer_conflict_count == 0


def test_build_cashflow_yoy_summary_excludes_exclude_rows_from_metrics() -> None:
    transactions = [
        Transaction(
            booking_date=date(2025, 1, 3),
            description="Salary",
            amount_native=Decimal("1000.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Income",
            cashflow_type="in",
            amount_eur=Decimal("1000.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 10),
            description="Groceries",
            amount_native=Decimal("-200.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Shopping",
            cashflow_type="out",
            amount_eur=Decimal("-200.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 11),
            description="Pass-through spend",
            amount_native=Decimal("-300.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Non Personal Transactions",
            cashflow_type="exclude",
            amount_eur=Decimal("-300.00"),
        ),
    ]

    dataframe = canonical_dataframe_from_transactions(
        canonicalize_transactions(transactions, ingested_at=datetime(2026, 4, 6, tzinfo=UTC))
    )
    summary = build_cashflow_yoy_summary(dataframe)
    years = summary["years"]

    assert len(years) == 1
    assert years[0]["year"] == 2025
    assert years[0]["income"] == 1000.0
    assert years[0]["expenses"] == 200.0
    assert years[0]["net_cashflow"] == 800.0


def test_resolve_cashflow_types_falls_back_to_sign_for_positive_unmapped_rows(
    tmp_path: Path,
) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Misc credit",
        amount_native=Decimal("125.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Work",
        amount_eur=Decimal("125.00"),
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text("overrides: []\n", encoding="utf-8")
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "in"
    assert result.unknown_count == 0


def test_resolve_cashflow_types_falls_back_to_sign_for_negative_unmapped_rows(
    tmp_path: Path,
) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Misc debit",
        amount_native=Decimal("-25.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="House",
        amount_eur=Decimal("-25.00"),
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text("overrides: []\n", encoding="utf-8")
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "out"
    assert result.unknown_count == 0

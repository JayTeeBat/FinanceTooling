from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.store import upsert_transactions
from finance_tooling.workflow.category_carry_forward import apply_manual_category_carry_forward


def _transaction(
    source: Path,
    *,
    description: str,
    category: str = "Uncategorized",
    subcategory: str | None = None,
    category_source: str = "uncategorized",
) -> Transaction:
    return Transaction(
        booking_date=date(2025, 6, 24),
        description=description,
        amount_native=Decimal("-35.89"),
        currency="EUR",
        source_file=source,
        bank="LaBanquePostale",
        parser="labanquepostale",
        category=category,
        subcategory=subcategory,
        category_source=category_source,
    )


def test_apply_manual_category_carry_forward_uses_prefix_match_when_description_changes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "lbp.pdf"
    source.write_text("x", encoding="utf-8")
    master = tmp_path / "transactions_master.parquet"

    existing = _transaction(
        source,
        description=(
            "ACHAT CB E LECLERC 23.06.25 CARTE NUMERO 536 "
            "Totaldesoperations 9 143,20 10 248,02 Pour votre information"
        ),
        category="Groceries",
        subcategory="General Retail",
        category_source="transaction_override",
    )
    upsert_transactions(master, [existing])

    incoming = _transaction(
        source,
        description="ACHAT CB E LECLERC 23.06.25 CARTE NUMERO 536",
    )
    result = apply_manual_category_carry_forward([incoming], master_parquet_path=master)

    assert result.diagnostics.applied_count == 1
    assert result.diagnostics.ambiguous_skipped_count == 0
    assert result.transactions[0].category == "Groceries"
    assert result.transactions[0].subcategory == "General Retail"
    assert result.transactions[0].category_source == "transaction_override"


def test_apply_manual_category_carry_forward_skips_ambiguous_matches(tmp_path: Path) -> None:
    source = tmp_path / "hsbc.pdf"
    source.write_text("x", encoding="utf-8")
    master = tmp_path / "transactions_master.parquet"

    base = Transaction(
        booking_date=date(2017, 12, 18),
        description="VIS PRIMARK644 LONDON W5",
        amount_native=Decimal("-3.00"),
        currency="GBP",
        source_file=source,
        bank="HSBC",
        parser="hsbc",
        category="Shopping",
        subcategory=None,
        category_source="transaction_override",
    )
    another = replace(
        base,
        description="VIS PRIMARK644 LONDON W5 EXTRA",
        category="Leisure",
        category_source="transaction_override",
    )
    upsert_transactions(master, [base, another])

    incoming = replace(
        base,
        description="VIS PRIMARK644 LONDON W5",
        category="Uncategorized",
        subcategory=None,
        category_source="uncategorized",
    )
    # Force ambiguity by matching both existing descriptions through prefix logic.
    incoming = replace(incoming, description="VIS PRIMARK644 LONDON W5 E")

    result = apply_manual_category_carry_forward([incoming], master_parquet_path=master)

    assert result.diagnostics.applied_count == 0
    assert result.diagnostics.ambiguous_skipped_count == 1
    assert result.transactions[0].category == "Uncategorized"
    assert result.transactions[0].category_source == "uncategorized"
    assert result.warnings


def test_apply_manual_category_carry_forward_skips_generic_transfer_prefix_matches(
    tmp_path: Path,
) -> None:
    source = tmp_path / "lbp.pdf"
    source.write_text("x", encoding="utf-8")
    master = tmp_path / "transactions_master.parquet"

    base = Transaction(
        booking_date=date(2025, 1, 24),
        description="VIREMENT POUR REFERENCE : 0329023515430172",
        amount_native=Decimal("-1000.00"),
        currency="EUR",
        source_file=source,
        bank="LaBanquePostale",
        parser="labanquepostale",
        category="Transfers",
        subcategory="Savings Transfer",
        category_source="transaction_override",
    )
    another = replace(
        base,
        description="VIREMENT POUR REFERENCE : 0329023515430303",
    )
    upsert_transactions(master, [base, another])

    incoming = replace(
        base,
        description=(
            "VIREMENT POUR M THOMAZO HENRY COMPTE FR2010011000207559958299C76 "
            "DEFAULT REFERENCE : 0329023515430050"
        ),
        category="Transfers",
        subcategory="Account Transfer",
        category_source="rule",
    )

    result = apply_manual_category_carry_forward([incoming], master_parquet_path=master)

    assert result.diagnostics.applied_count == 0
    assert result.diagnostics.ambiguous_skipped_count == 0
    assert result.transactions[0].category == "Transfers"
    assert result.transactions[0].subcategory == "Account Transfer"
    assert result.transactions[0].category_source == "rule"
    assert result.warnings == []

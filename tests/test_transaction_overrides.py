from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.store import compute_transaction_id
from finance_tooling.transaction_overrides import (
    TransactionOverrideEntry,
    TransactionOverrideStore,
    apply_transaction_overrides,
    load_transaction_override_store,
)


def _tx(description: str, *, amount: str) -> Transaction:
    return Transaction(
        booking_date=date(2026, 2, 1),
        description=description,
        amount_native=Decimal(amount),
        currency="EUR",
        source_file=Path("/tmp/statement.pdf"),
        bank="REVOLUT",
        parser="revolut",
        category="Uncategorized",
        subcategory=None,
        category_confidence=0.0,
        category_source="uncategorized",
        account_label="Main",
    )


def test_load_transaction_override_store_supports_nested_match_block(tmp_path: Path) -> None:
    path = tmp_path / "transaction_overrides.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "overrides:",
                "  - id: tx-1",
                "    match:",
                "      fingerprint: airport transfer",
                "      bank: REVOLUT",
                "      account_label: MAIN",
                "      booking_date: '2026-02-01'",
                "      amount_native: -42.5",
                "      currency: EUR",
                "    category: Transport",
                "    subcategory: Taxi",
                "    cashflow_type: out",
                "    from_account_ref: revolut_main",
                "    to_account_type: external",
                "    project_tags: [Trip2026, Work]",
            ]
        ),
        encoding="utf-8",
    )

    store, warnings = load_transaction_override_store(path)

    assert warnings == []
    assert len(store.entries) == 1
    entry = store.entries[0]
    assert entry.override_id == "tx-1"
    assert entry.fingerprint == "airport transfer"
    assert entry.bank == "REVOLUT"
    assert entry.account_label == "MAIN"
    assert entry.booking_date == date(2026, 2, 1)
    assert entry.amount_native == Decimal("-42.5")
    assert entry.currency == "EUR"
    assert entry.category == "Transport"
    assert entry.subcategory == "Taxi"
    assert entry.cashflow_type == "out"
    assert entry.from_account_ref == "revolut_main"
    assert entry.to_account_type == "external"
    assert entry.project_tags == ("Trip2026", "Work")


def test_apply_transaction_overrides_uses_last_match_wins() -> None:
    target = _tx("Airport transfer 2026", amount="-42.50")
    untouched = _tx("Salary", amount="1000.00")
    target_id = compute_transaction_id(target)

    store = TransactionOverrideStore(
        entries=(
            TransactionOverrideEntry(
                override_id="by-fingerprint",
                transaction_id=None,
                fingerprint="airport transfer",
                booking_date=None,
                amount_native=None,
                currency=None,
                bank=None,
                account_label=None,
                category="Transport",
                set_category=True,
                subcategory="Taxi",
                set_subcategory=True,
                project=None,
                set_project=False,
                project_tags=(),
                set_project_tags=False,
            ),
            TransactionOverrideEntry(
                override_id="by-id",
                transaction_id=target_id,
                fingerprint=None,
                booking_date=None,
                amount_native=None,
                currency=None,
                bank=None,
                account_label=None,
                category="Travel",
                set_category=True,
                subcategory="Flights",
                set_subcategory=True,
                project=None,
                set_project=False,
                project_tags=("Trip2026", "Family"),
                set_project_tags=True,
                cashflow_type="out",
                set_cashflow_type=True,
                from_account_ref="revolut_main",
                set_from_account_ref=True,
                to_account_type="external",
                set_to_account_type=True,
            ),
        )
    )

    updated = apply_transaction_overrides([target, untouched], store)

    assert updated[0].category == "Travel"
    assert updated[0].subcategory == "Flights"
    assert updated[0].category_source == "transaction_override"
    assert updated[0].category_rule_id is None
    assert updated[0].category_confidence == 1.0
    assert updated[0].cashflow_type == "out"
    assert updated[0].from_account_ref == "revolut_main"
    assert updated[0].to_account_type == "external"
    assert updated[0].account_inference_source == "transaction_override"
    assert updated[0].project == "Trip2026"
    assert updated[0].project_tags == ("Trip2026", "Family")
    assert updated[0].project_source == "transaction_override"

    assert updated[1] == untouched

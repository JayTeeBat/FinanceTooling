from pathlib import Path

import pandas as pd

from finance_tooling.categorization.classify import ClassificationRules, TaxonomyCategory
from finance_tooling.planning.budgeting import (
    build_budget_status,
    build_monthly_planning_ledger,
    load_budget_config,
)


def test_build_budget_status_supports_category_and_project_targets(tmp_path: Path) -> None:
    budget_path = tmp_path / "budget_targets.yaml"
    budget_path.write_text(
        "\n".join(
            [
                "version: 1",
                "currency: EUR",
                "targets:",
                "  - month: '2026-01'",
                "    category_id: groceries.food_at_home",
                "    category: Groceries",
                "    project: null",
                "    amount: 100.0",
                "  - month: '2026-01'",
                "    category_id: transport.public_transport",
                "    category: Transport",
                "    project: Mobility",
                "    amount: 60.0",
            ]
        ),
        encoding="utf-8",
    )
    config, warnings = load_budget_config(budget_path)
    assert warnings == []

    rules = ClassificationRules(
        rules=(),
        taxonomy={
            "groceries.food_at_home": TaxonomyCategory(
                name="Groceries",
                subcategories=(),
                cashflow_type="out",
                economic_role="variable_expense",
                decision_role="essential",
                category_label="Groceries",
                subcategory_label="Food at Home",
            ),
            "transport.public_transport": TaxonomyCategory(
                name="Transport",
                subcategories=(),
                cashflow_type="out",
                economic_role="variable_expense",
                decision_role="essential",
                category_label="Transport",
                subcategory_label="Public Transport",
            ),
        },
    )
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-03",
                "transaction_id": "tx-1",
                "category": "Groceries",
                "category_id": "groceries.food_at_home",
                "project": "Family",
                "amount_eur": -50.0,
            },
            {
                "booking_date": "2026-01-19",
                "transaction_id": "tx-2",
                "category": "Groceries",
                "category_id": "groceries.food_at_home",
                "project": "Unassigned",
                "amount_eur": -20.0,
            },
            {
                "booking_date": "2026-01-21",
                "transaction_id": "tx-3",
                "category": "Transport",
                "category_id": "transport.public_transport",
                "project": "Mobility",
                "amount_eur": -80.0,
            },
            {
                "booking_date": "2026-01-28",
                "transaction_id": "tx-4",
                "category": "Transport",
                "category_id": "transport.public_transport",
                "project": "Mobility",
                "amount_eur": 20.0,
            },
            {
                "booking_date": "2026-01-29",
                "transaction_id": "tx-5",
                "category": "Transfers",
                "category_id": "transfers.savings_transfer",
                "subcategory": "Savings Transfer",
                "project": "Mobility",
                "cashflow_type": "transfer",
                "economic_role": "transfer",
                "decision_role": "not_applicable",
                "amount_eur": -100.0,
            },
            {
                "booking_date": "2026-01-30",
                "transaction_id": "tx-6",
                "category": "Non Personal Transactions",
                "category_id": "non.personal.transactions",
                "project": "",
                "cashflow_type": "exclude",
                "economic_role": "exclude",
                "decision_role": "not_applicable",
                "amount_eur": -15.0,
            },
        ]
    )

    ledger = build_monthly_planning_ledger(frame, classification_rules=rules)
    assert set(ledger["transaction_id"]) == {"tx-1", "tx-2", "tx-3", "tx-4", "tx-5", "tx-6"}
    ledger_by_id = ledger.set_index("transaction_id")
    assert ledger_by_id.loc["tx-1", "planning_bucket"] == "expense"
    assert ledger_by_id.loc["tx-1", "planning_amount_eur"] == 50.0
    assert ledger_by_id.loc["tx-5", "planning_bucket"] == "savings"
    assert ledger_by_id.loc["tx-5", "planning_amount_eur"] == 100.0
    assert ledger_by_id.loc["tx-6", "planning_bucket"] == "excluded"
    assert ledger_by_id.loc["tx-6", "planning_amount_eur"] == 0.0

    status = build_budget_status(frame, config, classification_rules=rules)
    status_rows = status.to_dict(orient="records")

    groceries_row = next(row for row in status_rows if row["category"] == "Groceries")
    assert groceries_row["actual_amount"] == 70.0
    assert groceries_row["variance"] == 30.0
    assert groceries_row["status"] == "on_track"
    assert groceries_row["category_id"] == "groceries.food_at_home"

    transport_row = next(row for row in status_rows if row["category"] == "Transport")
    assert transport_row["actual_amount"] == 80.0
    assert transport_row["variance"] == -20.0
    assert transport_row["status"] == "over_budget"
    assert transport_row["category_id"] == "transport.public_transport"


def test_load_budget_config_reports_duplicate_targets(tmp_path: Path) -> None:
    budget_path = tmp_path / "budget_targets.yaml"
    budget_path.write_text(
        "\n".join(
            [
                "targets:",
                "  - month: '2026-01'",
                "    category: Groceries",
                "    project: null",
                "    amount: 100.0",
                "  - month: '2026-01'",
                "    category: groceries",
                "    project: null",
                "    amount: 150.0",
            ]
        ),
        encoding="utf-8",
    )

    config, warnings = load_budget_config(budget_path)
    assert config.targets == ()
    assert len(warnings) == 1

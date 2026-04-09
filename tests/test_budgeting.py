from pathlib import Path

import pandas as pd

from finance_tooling.planning.budgeting import build_budget_status, load_budget_config


def test_build_budget_status_supports_category_and_project_targets(tmp_path: Path) -> None:
    budget_path = tmp_path / "budget_targets.yaml"
    budget_path.write_text(
        "\n".join(
            [
                "version: 1",
                "currency: EUR",
                "targets:",
                "  - month: '2026-01'",
                "    category: Groceries",
                "    project: null",
                "    amount: 100.0",
                "  - month: '2026-01'",
                "    category: Transport",
                "    project: Mobility",
                "    amount: 60.0",
            ]
        ),
        encoding="utf-8",
    )
    config, warnings = load_budget_config(budget_path)
    assert warnings == []

    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-03",
                "category": "Groceries",
                "project": "Family",
                "amount_eur": -50.0,
            },
            {
                "booking_date": "2026-01-19",
                "category": "Groceries",
                "project": "Unassigned",
                "amount_eur": -20.0,
            },
            {
                "booking_date": "2026-01-21",
                "category": "Transport",
                "project": "Mobility",
                "amount_eur": -80.0,
            },
            {
                "booking_date": "2026-01-28",
                "category": "Transport",
                "project": "Mobility",
                "amount_eur": 20.0,
            },
        ]
    )

    status = build_budget_status(frame, config)
    status_rows = status.to_dict(orient="records")

    groceries_row = next(row for row in status_rows if row["category"] == "Groceries")
    assert groceries_row["actual_amount"] == 70.0
    assert groceries_row["variance"] == 30.0
    assert groceries_row["status"] == "on_track"

    transport_row = next(row for row in status_rows if row["category"] == "Transport")
    assert transport_row["actual_amount"] == 80.0
    assert transport_row["variance"] == -20.0
    assert transport_row["status"] == "over_budget"


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

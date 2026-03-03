from pathlib import Path

import pandas as pd

from finance_tooling.projecting import assign_projects_to_dataframe, load_project_config


def test_assign_projects_uses_override_rule_and_fallback(tmp_path: Path) -> None:
    config_path = tmp_path / "project_rules.yaml"
    config_path.write_text(
        "\n".join(
            [
                "version: 1",
                "defaults:",
                "  fallback_project: Unassigned",
                "rules:",
                "  - id: project.mobility",
                "    priority: 10",
                "    project: Mobility",
                "    match: contains",
                "    patterns:",
                "      - transport for london",
                "    categories:",
                "      - Transport",
                "    expense_only: true",
                "overrides:",
                "  - fingerprint: bp hmrc tfc",
                "    project: Family",
                "    bank: HSBC",
                "    account_label: null",
            ]
        ),
        encoding="utf-8",
    )

    config, warnings = load_project_config(config_path)
    assert warnings == []

    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-10",
                "description": "BP HMRC TFC",
                "amount_native": -100.0,
                "amount_eur": -100.0,
                "bank": "HSBC",
                "account_label": None,
                "category": "Family",
            },
            {
                "booking_date": "2026-01-11",
                "description": "Transport for London",
                "amount_native": -20.0,
                "amount_eur": -20.0,
                "bank": "HSBC",
                "account_label": None,
                "category": "Transport",
            },
            {
                "booking_date": "2026-01-12",
                "description": "Salary",
                "amount_native": 500.0,
                "amount_eur": 500.0,
                "bank": "HSBC",
                "account_label": None,
                "category": "Income",
            },
        ]
    )

    assigned = assign_projects_to_dataframe(frame, config=config)
    assert assigned["project"].tolist() == ["Family", "Mobility", "Unassigned"]


def test_load_project_config_returns_warning_for_invalid_payload(tmp_path: Path) -> None:
    config_path = tmp_path / "project_rules.yaml"
    config_path.write_text("rules: not-a-list\n", encoding="utf-8")

    config, warnings = load_project_config(config_path)

    assert config.fallback_project == "Unassigned"
    assert config.rules == ()
    assert config.overrides == ()
    assert len(warnings) == 1

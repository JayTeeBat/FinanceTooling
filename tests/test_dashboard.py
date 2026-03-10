from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

import pandas as pd

from finance_tooling.dashboard import render_dashboard_html


def _extract_payload(html: str) -> dict[str, object]:
    match = re.search(
        r'<script id="dashboard-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("Embedded dashboard payload script not found")
    return json.loads(match.group(1))


def test_render_dashboard_html_embeds_transactions_projects_and_budget_targets(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-03",
                "description": "Transport for London",
                "amount_native": -12.50,
                "amount_eur": -12.50,
                "category": "Transport",
                "bank": "HSBC",
                "account_label": None,
            },
            {
                "booking_date": "2026-01-08",
                "description": "Salary",
                "amount_native": 1000.0,
                "amount_eur": 1000.0,
                "category": "Income",
                "bank": "HSBC",
                "account_label": None,
            },
            {
                "booking_date": "2026-01-10",
                "description": "Transfer to savings",
                "amount_native": -300.0,
                "amount_eur": -300.0,
                "category": "Transfers",
                "bank": "HSBC",
                "account_label": None,
            },
        ]
    )
    project_rules_path = tmp_path / "project_rules.yaml"
    project_rules_path.write_text(
        "\n".join(
            [
                "defaults:",
                "  fallback_project: Unassigned",
                "rules:",
                "  - id: project.mobility",
                "    priority: 5",
                "    project: Mobility",
                "    match: contains",
                "    patterns:",
                "      - transport for london",
                "    categories:",
                "      - Transport",
                "    expense_only: true",
            ]
        ),
        encoding="utf-8",
    )
    budget_targets_path = tmp_path / "budget_targets.yaml"
    budget_targets_path.write_text(
        "\n".join(
            [
                "targets:",
                "  - month: '2026-01'",
                "    category: Transport",
                "    project: Mobility",
                "    amount: 200.0",
            ]
        ),
        encoding="utf-8",
    )

    destination = tmp_path / "dashboard.html"
    render_dashboard_html(
        frame,
        destination,
        base_currency="EUR",
        files_scanned=3,
        files_failed=0,
        new_rows=2,
        project_rules_path=project_rules_path,
        budget_targets_path=budget_targets_path,
    )

    html = destination.read_text(encoding="utf-8")
    assert "Interactive Finance Dashboard" in html
    assert 'id="window-select"' in html
    assert "Last 3 Years" in html
    assert "Last 5 Years" in html
    assert "Last 10 Years" in html
    assert ">Transfers<" in html
    assert "Full History" in html
    assert "Specific Year" in html
    assert 'id="specific-year"' in html

    payload = _extract_payload(html)
    transactions_raw = payload["transactions"]
    assert isinstance(transactions_raw, list)
    transactions = cast(list[dict[str, object]], transactions_raw)
    assert transactions[0]["project"] == "Mobility"
    assert transactions[1]["project"] == "Unassigned"
    assert transactions[2]["is_transfer"] is True
    budget_targets_raw = payload["budget_targets"]
    assert isinstance(budget_targets_raw, list)
    budget_targets = cast(list[dict[str, object]], budget_targets_raw)
    assert budget_targets[0]["category"] == "Transport"
    assert budget_targets[0]["amount"] == 200.0


def test_render_dashboard_html_includes_config_warnings_when_loading_fails(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-03",
                "description": "Anything",
                "amount_native": -20.0,
                "amount_eur": -20.0,
                "category": "Shopping",
                "bank": "HSBC",
                "account_label": None,
            }
        ]
    )
    project_rules_path = tmp_path / "broken_project_rules.yaml"
    project_rules_path.write_text("rules: {bad: true}\n", encoding="utf-8")
    budget_targets_path = tmp_path / "broken_budget_targets.yaml"
    budget_targets_path.write_text("targets: duplicate\n", encoding="utf-8")

    destination = tmp_path / "dashboard.html"
    render_dashboard_html(
        frame,
        destination,
        base_currency="EUR",
        files_scanned=1,
        files_failed=0,
        new_rows=1,
        project_rules_path=project_rules_path,
        budget_targets_path=budget_targets_path,
    )

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    warnings = payload["warnings"]
    assert isinstance(warnings, list)
    assert len(warnings) == 2

from __future__ import annotations

import json
import re
from datetime import date, datetime
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
                "cashflow_type": "out",
                "bank": "HSBC",
                "account_label": None,
            },
            {
                "booking_date": "2026-01-08",
                "description": "Salary",
                "amount_native": 1000.0,
                "amount_eur": 1000.0,
                "category": "Income",
                "cashflow_type": "in",
                "bank": "HSBC",
                "account_label": None,
            },
            {
                "booking_date": "2026-01-10",
                "description": "Transfer to savings",
                "amount_native": -300.0,
                "amount_eur": -300.0,
                "category": "Transfers",
                "cashflow_type": "transfer",
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
    assert "normalizeCustomFullYearRange" in html
    assert "Last 3 Years" in html
    assert "Last 5 Years" in html
    assert "Last 10 Years" in html
    assert ">Transfers<" in html
    assert "Full History" in html
    assert "Specific Year" in html
    assert 'id="specific-year"' in html

    payload = _extract_payload(html)
    cashflow_yoy = payload["cashflow_yoy"]
    assert isinstance(cashflow_yoy, dict)
    assert "years" in cashflow_yoy
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
                "cashflow_type": "out",
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


def test_render_dashboard_html_includes_cashflow_type_warning_when_unknown_present(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-03",
                "description": "Mystery income",
                "amount_native": 20.0,
                "amount_eur": 20.0,
                "category": "Uncategorized",
                "cashflow_type": "unknown",
                "bank": "HSBC",
                "account_label": None,
            }
        ]
    )

    destination = tmp_path / "dashboard.html"
    render_dashboard_html(
        frame,
        destination,
        base_currency="EUR",
        files_scanned=1,
        files_failed=0,
        new_rows=1,
    )

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    warnings = cast(list[str], payload["warnings"])
    assert len(warnings) == 1
    assert "Cashflow type unresolved for 1 transaction" in warnings[0]
    assert "Uncategorized" in warnings[0]


def test_render_dashboard_html_includes_cashflow_type_exclude_warning_when_present(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-03",
                "description": "Pass-through expense",
                "amount_native": -20.0,
                "amount_eur": -20.0,
                "category": "Non Personal Transactions",
                "cashflow_type": "exclude",
                "bank": "HSBC",
                "account_label": None,
            }
        ]
    )

    destination = tmp_path / "dashboard.html"
    render_dashboard_html(
        frame,
        destination,
        base_currency="EUR",
        files_scanned=1,
        files_failed=0,
        new_rows=1,
    )

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    warnings = cast(list[str], payload["warnings"])
    assert len(warnings) == 1
    assert "Economic role exclude applies to 1 transaction" in warnings[0]
    assert "Non Personal Transactions" in warnings[0]


def test_render_dashboard_html_includes_account_boundary_warning_when_unknown_present(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-03",
                "description": "Mystery transfer",
                "amount_native": 20.0,
                "amount_eur": 20.0,
                "category": "Transfers",
                "cashflow_type": "transfer",
                "from_account_type": "unknown",
                "to_account_type": "internal",
                "account_inference_source": "unknown",
                "bank": "HSBC",
                "account_label": None,
            }
        ]
    )

    destination = tmp_path / "dashboard.html"
    render_dashboard_html(
        frame,
        destination,
        base_currency="EUR",
        files_scanned=1,
        files_failed=0,
        new_rows=1,
    )

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    warnings = cast(list[str], payload["warnings"])
    assert len(warnings) == 1
    assert "Account boundary unresolved for 1 transaction" in warnings[0]
    assert "unknown=1" in warnings[0]


def test_render_dashboard_html_includes_account_transfer_warning_when_boundary_reclassifies(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-03",
                "description": "Move to savings",
                "amount_native": -250.0,
                "amount_eur": -250.0,
                "category": "Shopping",
                "cashflow_type": "transfer",
                "economic_role": "transfer",
                "from_account_type": "internal",
                "to_account_type": "internal",
                "account_inference_source": "account_rule",
                "bank": "HSBC",
                "account_label": None,
            }
        ]
    )

    destination = tmp_path / "dashboard.html"
    render_dashboard_html(
        frame,
        destination,
        base_currency="EUR",
        files_scanned=1,
        files_failed=0,
        new_rows=1,
    )

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    warnings = cast(list[str], payload["warnings"])
    assert len(warnings) == 2
    assert "reclassified 1 internal-to-internal transaction as transfer" in warnings[0]
    assert "transfer conflicts remain on 1 categorized rows" in warnings[1]


def test_render_dashboard_html_vectorized_transaction_row_normalization(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": datetime(2026, 1, 5, 10, 30),
                "description": "Salary",
                "amount_native": 1000.0,
                "amount_eur": "1000.50",
                "category": " Income ",
                "cashflow_type": "in",
                "project": "  ",
                "bank": "HSBC",
                "account_label": None,
            },
            {
                "booking_date": pd.Timestamp("2026-01-03"),
                "description": "Transfer",
                "amount_native": -50.0,
                "amount_eur": -50.0,
                "category": "Transfers",
                "cashflow_type": "transfer",
                "project": "Savings",
                "bank": "HSBC",
                "account_label": None,
            },
            {
                "booking_date": date(2026, 1, 4),
                "description": "Unknown",
                "amount_native": -5.0,
                "amount_eur": None,
                "category": "",
                "cashflow_type": "unknown",
                "project": None,
                "bank": "HSBC",
                "account_label": None,
            },
            {
                "booking_date": "not-a-date",
                "description": "Bad",
                "amount_native": -1.0,
                "amount_eur": -1.0,
                "category": "Shopping",
                "cashflow_type": "out",
                "project": "Errand",
                "bank": "HSBC",
                "account_label": None,
            },
        ]
    )

    destination = tmp_path / "dashboard.html"
    render_dashboard_html(
        frame,
        destination,
        base_currency="EUR",
        files_scanned=4,
        files_failed=0,
        new_rows=4,
    )

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    transactions_raw = payload["transactions"]
    assert isinstance(transactions_raw, list)
    transactions = cast(list[dict[str, object]], transactions_raw)

    assert [row["booking_date"] for row in transactions] == [
        "2026-01-03",
        "2026-01-04",
        "2026-01-05",
    ]
    assert transactions[0]["is_transfer"] is True
    assert transactions[1]["category"] == "Uncategorized"
    assert transactions[1]["project"] == "Unassigned"
    assert transactions[1]["amount_eur"] == 0.0
    assert transactions[2]["category"] == "Income"
    assert transactions[2]["project"] == "Unassigned"
    assert transactions[2]["amount_eur"] == 1000.5


def test_render_dashboard_html_cashflow_income_uses_income_category_only(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2025-01-05",
                "description": "Salary",
                "amount_native": 1000.0,
                "amount_eur": 1000.0,
                "category": "Income",
                "cashflow_type": "in",
                "bank": "HSBC",
                "account_label": None,
            },
            {
                "booking_date": "2025-02-10",
                "description": "Refund",
                "amount_native": 80.0,
                "amount_eur": 80.0,
                "category": "Shopping",
                "cashflow_type": "out",
                "bank": "HSBC",
                "account_label": None,
            },
            {
                "booking_date": "2025-03-12",
                "description": "Groceries",
                "amount_native": -200.0,
                "amount_eur": -200.0,
                "category": "Groceries",
                "cashflow_type": "out",
                "bank": "HSBC",
                "account_label": None,
            },
        ]
    )

    destination = tmp_path / "dashboard.html"
    render_dashboard_html(
        frame,
        destination,
        base_currency="EUR",
        files_scanned=1,
        files_failed=0,
        new_rows=3,
        project_rules_path=None,
        budget_targets_path=None,
    )

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    cashflow_yoy = cast(dict[str, object], payload["cashflow_yoy"])
    years = cast(list[dict[str, object]], cashflow_yoy["years"])

    assert years[0]["year"] == 2025
    assert years[0]["income"] == 1000.0
    assert years[0]["expenses"] == 120.0
    assert years[0]["net_cashflow"] == 880.0

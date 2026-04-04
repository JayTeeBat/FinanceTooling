from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

import pandas as pd

from finance_tooling.household_healthcheck import render_household_healthcheck_html


def _extract_payload(html: str) -> dict[str, object]:
    match = re.search(
        r'<script id="household-healthcheck-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("Embedded healthcheck payload script not found")
    return json.loads(match.group(1))


def test_render_household_healthcheck_html_builds_expected_window_metrics(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-01-05",
                "description": "Salary",
                "amount_eur": 5000.0,
                "category": "Income",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-01-06",
                "description": "Mortgage",
                "amount_eur": -1500.0,
                "category": "Housing",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-01-07",
                "description": "Groceries",
                "amount_eur": -800.0,
                "category": "Groceries",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-01-08",
                "description": "Cash withdrawal",
                "amount_eur": -120.0,
                "category": "Cash",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-01-09",
                "description": "Retirement contribution",
                "amount_eur": -500.0,
                "category": "Retirement",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-01-10",
                "description": "Transfer to wallet",
                "amount_eur": -250.0,
                "category": "Transfers",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-01-11",
                "description": "Kid reserve",
                "amount_eur": -300.0,
                "category": "Shopping",
                "project": "Education reserve",
                "project_tags": "",
            },
            {
                "booking_date": "2026-01-12",
                "description": "Mystery vendor",
                "amount_eur": -200.0,
                "category": "Uncategorized",
                "project": "",
                "project_tags": "",
            },
        ]
    )

    destination = tmp_path / "household_healthcheck.html"
    render_household_healthcheck_html(frame, destination, base_currency="EUR")

    html = destination.read_text(encoding="utf-8")
    assert "Household Finance Healthcheck" in html
    payload = _extract_payload(html)
    windows_raw = payload["windows"]
    assert isinstance(windows_raw, dict)
    windows = cast(dict[str, dict[str, object]], windows_raw)
    last_3_months = windows["last_3_months"]
    metrics = cast(dict[str, float], last_3_months["metrics"])
    status = cast(dict[str, str], last_3_months["status"])

    assert metrics["avg_monthly_inflow"] == 1666.67
    assert metrics["avg_monthly_consumption_spend"] == 873.33
    assert metrics["avg_monthly_tracked_savings"] == 266.67
    assert metrics["avg_monthly_net_residual"] == 526.67
    assert metrics["tracked_savings_rate"] == 0.16
    assert metrics["essential_spending_ratio"] == 0.8779
    assert metrics["housing_cost_ratio"] == 0.3
    assert metrics["uncategorized_amount_ratio"] == 0.0238
    assert metrics["uncategorized_count_ratio"] == 0.1429
    assert status["tracked_savings_rate"] == "green"
    assert status["essential_spending_ratio"] == "red"
    assert status["housing_cost_ratio"] == "amber"

    top_uncategorized = cast(list[dict[str, object]], last_3_months["top_uncategorized"])
    assert top_uncategorized[0]["description"] == "mystery vendor"
    category_breakdown = cast(list[dict[str, object]], last_3_months["category_breakdown"])
    assert category_breakdown[0]["category"] == "Housing"
    assert all(item["category"] != "Transfers" for item in category_breakdown)


def test_render_household_healthcheck_html_uses_project_tags_for_savings_detection(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-03-01",
                "description": "Salary",
                "amount_eur": 3000.0,
                "category": "Income",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-03-02",
                "description": "Broker contribution",
                "amount_eur": -450.0,
                "category": "Shopping",
                "project": "",
                "project_tags": ("retirement", "long_term"),
            },
            {
                "booking_date": "2026-03-03",
                "description": "Weekend spending",
                "amount_eur": -600.0,
                "category": "Leisure",
                "project": "",
                "project_tags": "",
            },
        ]
    )

    destination = tmp_path / "household_healthcheck.html"
    render_household_healthcheck_html(frame, destination, base_currency="EUR")

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    windows = cast(dict[str, dict[str, object]], payload["windows"])
    year_to_date = windows["year_to_date"]
    metrics = cast(dict[str, float], year_to_date["metrics"])

    assert metrics["avg_monthly_tracked_savings"] == 150.0
    assert metrics["avg_monthly_consumption_spend"] == 200.0


def test_render_household_healthcheck_html_counts_transfer_savings_and_investment_as_savings(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "booking_date": "2026-03-01",
                "description": "Salary",
                "amount_eur": 4000.0,
                "category": "Income",
                "subcategory": "",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-03-02",
                "description": "To savings",
                "amount_eur": -300.0,
                "category": "Transfers",
                "subcategory": "Savings Transfer",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-03-03",
                "description": "To broker",
                "amount_eur": -450.0,
                "category": "Transfers",
                "subcategory": "Investment",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-03-04",
                "description": "Internal transfer",
                "amount_eur": -700.0,
                "category": "Transfers",
                "subcategory": "Bank Transfer",
                "project": "",
                "project_tags": "",
            },
            {
                "booking_date": "2026-03-05",
                "description": "Groceries",
                "amount_eur": -600.0,
                "category": "Groceries",
                "subcategory": "Supermarket",
                "project": "",
                "project_tags": "",
            },
        ]
    )

    destination = tmp_path / "household_healthcheck.html"
    render_household_healthcheck_html(frame, destination, base_currency="EUR")

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    windows = cast(dict[str, dict[str, object]], payload["windows"])
    year_to_date = windows["year_to_date"]
    metrics = cast(dict[str, float], year_to_date["metrics"])

    assert metrics["avg_monthly_tracked_savings"] == 250.0
    assert metrics["avg_monthly_consumption_spend"] == 200.0
    assert metrics["avg_monthly_net_residual"] == 883.33

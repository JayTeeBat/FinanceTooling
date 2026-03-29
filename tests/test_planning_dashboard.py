from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import TypedDict, cast

from finance_tooling.planning import build_planning_summary, load_planning_inputs
from finance_tooling.planning_dashboard import render_planning_hypothesis_html


class ChildBaseline(TypedDict):
    label: str
    current_age: float
    target_age: float
    target_fund_eur: float
    current_fund_eur: float
    expected_return_pct: float


class DashboardBaseline(TypedDict):
    as_of_date: str
    adult_1_age: float
    adult_2_age: float
    retirement_age_adult_1: float
    retirement_age_adult_2: float
    pension_adult_1_before_tax_eur: float
    pension_adult_2_before_tax_eur: float
    retirement_spending_before_tax_eur: float
    withdrawal_rate_pct: float
    current_retirement_assets_eur: float
    children: list[ChildBaseline]
    house_project_cost_eur: float
    house_contingency_pct: float
    house_target_years: float
    current_house_reserved_eur: float
    inflation_pct: float
    growth_return_pct: float
    house_return_pct: float
    current_investable_net_worth_eur: float
    current_home_value_eur: float
    mortgage_annual_rate_pct: float


def _extract_payload(html: str) -> dict[str, object]:
    match = re.search(
        r'<script id="planning-dashboard-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("Embedded planning payload script not found")
    return json.loads(match.group(1))


def _monthly_rate(expected_return_pct: float) -> float:
    annual_rate = expected_return_pct / 100.0
    return (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0


def _required_monthly_contribution(
    *,
    target_amount_eur: float,
    current_amount_eur: float,
    years_to_goal: float,
    expected_return_pct: float,
) -> float:
    if years_to_goal <= 0:
        return max(0.0, target_amount_eur - current_amount_eur)

    months_to_goal = max(1, round(years_to_goal * 12))
    monthly_rate = _monthly_rate(expected_return_pct)
    future_value_of_current = current_amount_eur * (1.0 + monthly_rate) ** months_to_goal
    remaining_target = target_amount_eur - future_value_of_current
    if remaining_target <= 0:
        return 0.0
    if abs(monthly_rate) < 1e-12:
        return remaining_target / months_to_goal
    annuity_factor = ((1.0 + monthly_rate) ** months_to_goal - 1.0) / monthly_rate
    return remaining_target / annuity_factor


def _inflate(amount_eur: float, years: float, inflation_pct: float) -> float:
    return amount_eur * (1.0 + inflation_pct / 100.0) ** max(0.0, years)


def _dashboard_goal_totals(baseline: DashboardBaseline) -> tuple[float, float, float]:
    adult_1_age = float(baseline["adult_1_age"])
    adult_2_age = float(baseline["adult_2_age"])
    retirement_age_1 = float(baseline["retirement_age_adult_1"])
    retirement_age_2 = float(baseline["retirement_age_adult_2"])
    years_to_retirement = max(
        0.0,
        min(retirement_age_1 - adult_1_age, retirement_age_2 - adult_2_age),
    )

    retirement_gap_today = max(
        0.0,
        float(baseline["retirement_spending_before_tax_eur"])
        - (
            float(baseline["pension_adult_1_before_tax_eur"])
            + float(baseline["pension_adult_2_before_tax_eur"])
        ),
    )
    retirement_gap_future = _inflate(
        retirement_gap_today,
        years_to_retirement,
        float(baseline["inflation_pct"]),
    )
    retirement_capital = retirement_gap_future / (float(baseline["withdrawal_rate_pct"]) / 100.0)
    retirement_monthly = _required_monthly_contribution(
        target_amount_eur=retirement_capital,
        current_amount_eur=float(baseline["current_retirement_assets_eur"]),
        years_to_goal=years_to_retirement,
        expected_return_pct=float(baseline["growth_return_pct"]),
    )

    education_monthly = 0.0
    for child in baseline["children"]:
        years_to_goal = max(0.0, float(child["target_age"]) - float(child["current_age"]))
        future_target = _inflate(
            float(child["target_fund_eur"]),
            years_to_goal,
            float(baseline["inflation_pct"]),
        )
        education_monthly += _required_monthly_contribution(
            target_amount_eur=future_target,
            current_amount_eur=float(child["current_fund_eur"]),
            years_to_goal=years_to_goal,
            expected_return_pct=float(child["expected_return_pct"]),
        )

    house_target_today = float(baseline["house_project_cost_eur"]) * (
        1.0 + float(baseline["house_contingency_pct"]) / 100.0
    )
    house_target_future = _inflate(
        house_target_today,
        float(baseline["house_target_years"]),
        float(baseline["inflation_pct"]),
    )
    house_monthly = _required_monthly_contribution(
        target_amount_eur=house_target_future,
        current_amount_eur=float(baseline["current_house_reserved_eur"]),
        years_to_goal=float(baseline["house_target_years"]),
        expected_return_pct=float(baseline["house_return_pct"]),
    )

    return retirement_monthly, education_monthly, house_monthly


def test_render_planning_hypothesis_html_includes_expected_controls(tmp_path: Path) -> None:
    inputs_path = tmp_path / "planning_inputs.yaml"
    inputs_path.write_text(
        """
household:
  adults:
    adult_1_date_of_birth: 1988-01-01
    adult_1_current_age: 38
    adult_2_date_of_birth: 1989-01-01
    adult_2_current_age: 37
  children:
    child_1_current_age: 13
    child_2_current_age: 11
    child_3_current_age: 7
income:
  taxable_household_income_eur: 102000
  estimated_net_household_income_eur: 85000
  annual_income_growth_pct: 2.0
liquidity:
  emergency_fund_target_months: 6
  essential_monthly_spend_eur: 4500
retirement:
  target_retirement_age_adult_1: 64
  target_retirement_age_adult_2: 64
  expected_annual_state_pension_adult_1_eur: 35000
  expected_annual_state_pension_adult_2_eur: 35000
  expected_annual_state_pension_eur: 70000
  expected_annual_state_pension_is_today_eur: true
  target_annual_spending_in_retirement_eur: 80000
  target_annual_spending_is_today_eur: true
  target_annual_spending_gap_eur:
  target_annual_spending_gap_is_today_eur: true
  safe_withdrawal_rate_pct: 3.0
  current_retirement_assets_eur: 50000
  monthly_retirement_contribution_eur: 0
  expected_nominal_return_pct: 6.0
education:
  child_1_target_fund_eur: 10000
  child_1_target_fund_is_today_eur: true
  child_1_target_age: 18
  child_1_current_fund_eur: 0
  child_1_expected_return_pct: 6.0
  child_2_target_fund_eur: 10000
  child_2_target_fund_is_today_eur: true
  child_2_target_age: 18
  child_2_current_fund_eur: 0
  child_2_expected_return_pct: 6.0
  child_3_target_fund_eur: 10000
  child_3_target_fund_is_today_eur: true
  child_3_target_age: 18
  child_3_current_fund_eur: 0
  child_3_expected_return_pct: 6.0
house_project:
  target_cost_eur: 100000
  target_cost_is_today_eur: true
  contingency_pct: 0
  target_date: 2031-03-16
  current_reserved_amount_eur: 50000
  expected_return_pct: 1.5
net_worth:
  current_total_net_worth_eur: 200000
  current_investable_net_worth_eur: 180000
  current_total_financial_assets_eur: 200000
  current_home_value_eur: 250000
  current_home_equity_eur: 0
  current_mortgage_balance_eur: 200000
mortgage:
  annual_rate_pct: 2.4
  monthly_payment_eur: 1300
  years_remaining: 17
assumptions:
  inflation_pct: 2.0
  cash_return_pct: 1.5
  conservative_growth_return_pct: 3.0
  growth_return_pct: 6.0
        """.strip(),
        encoding="utf-8",
    )
    destination = tmp_path / "playground.html"

    render_planning_hypothesis_html(inputs_path, destination)

    html = destination.read_text(encoding="utf-8")
    assert "Household Finance Hypothesis Playground" in html
    assert 'id="adult-1-dob"' in html
    assert 'id="retirement-age-adult-1"' in html
    assert 'id="pension-adult-1"' in html
    assert 'id="current-investable-net-worth"' in html
    assert 'id="current-home-value"' in html
    assert 'id="mortgage-rate"' in html
    assert 'id="home-growth"' in html
    assert 'id="retirement-spending"' in html
    assert 'id="child-1-fund"' in html
    assert 'id="child-2-fund"' in html
    assert 'id="child-3-fund"' in html
    assert 'id="house-cost"' in html
    assert 'id="growth-return"' in html
    payload = _extract_payload(html)
    baseline = cast(DashboardBaseline, payload["baseline"])
    assert baseline["retirement_age_adult_1"] == 64
    assert baseline["pension_adult_1_before_tax_eur"] == 35000
    assert baseline["current_investable_net_worth_eur"] == 180000
    assert baseline["current_home_value_eur"] == 250000
    assert baseline["mortgage_annual_rate_pct"] == 2.4
    assert baseline["children"][1]["target_fund_eur"] == 10000


def test_dashboard_baseline_matches_planning_summary() -> None:
    inputs_path = Path("planning/household_finance_360/09_planning_inputs.yaml")
    destination = Path("/tmp/planning_dashboard_test.html")

    render_planning_hypothesis_html(inputs_path, destination)

    payload = _extract_payload(destination.read_text(encoding="utf-8"))
    baseline = cast(DashboardBaseline, payload["baseline"])
    summary = build_planning_summary(
        load_planning_inputs(inputs_path),
        as_of_date=date.fromisoformat(str(baseline["as_of_date"])),
    )

    retirement_monthly, education_monthly, house_monthly = _dashboard_goal_totals(baseline)
    canonical = {goal.goal_name: goal.required_monthly_saving_eur for goal in summary.goal_results}

    assert math.isclose(retirement_monthly, canonical["retirement"], rel_tol=0.0, abs_tol=0.01)
    assert math.isclose(
        education_monthly,
        canonical["child_1_education"]
        + canonical["child_2_education"]
        + canonical["child_3_education"],
        rel_tol=0.0,
        abs_tol=0.01,
    )
    assert math.isclose(
        house_monthly,
        canonical["house_expansion"],
        rel_tol=0.0,
        abs_tol=0.01,
    )
    assert math.isclose(
        retirement_monthly + education_monthly + house_monthly,
        summary.total_required_monthly_saving_eur,
        rel_tol=0.0,
        abs_tol=0.01,
    )

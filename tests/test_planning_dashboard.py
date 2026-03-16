from __future__ import annotations

import json
import re
from pathlib import Path

from finance_tooling.planning_dashboard import render_planning_hypothesis_html


def _extract_payload(html: str) -> dict[str, object]:
    match = re.search(
        r'<script id="planning-dashboard-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("Embedded planning payload script not found")
    return json.loads(match.group(1))


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
    assert 'id="kids-fund"' in html
    assert 'id="house-cost"' in html
    assert 'id="growth-return"' in html
    payload = _extract_payload(html)
    baseline = payload["baseline"]
    assert isinstance(baseline, dict)
    assert baseline["retirement_age_adult_1"] == 64
    assert baseline["pension_adult_1_before_tax_eur"] == 35000
    assert baseline["current_investable_net_worth_eur"] == 180000
    assert baseline["current_home_value_eur"] == 250000
    assert baseline["mortgage_annual_rate_pct"] == 2.4

from __future__ import annotations

import json
from pathlib import Path

from finance_tooling.__main__ import main


def test_plan_savings_cli_writes_output(tmp_path: Path, capsys) -> None:
    inputs_path = tmp_path / "planning_inputs.yaml"
    output_path = tmp_path / "sizing.json"
    inputs_path.write_text(
        """
household:
  adults:
    adult_1_current_age: 38
    adult_2_current_age: 37
  children:
    child_1_current_age: 13
    child_2_current_age: 11
    child_3_current_age: 7
liquidity:
  emergency_fund_target_months: 6
  essential_monthly_spend_eur: 4000
retirement:
  target_retirement_age_adult_1: 62
  target_retirement_age_adult_2: 62
  expected_annual_state_pension_eur: 30000
  expected_annual_state_pension_is_today_eur: true
  target_annual_spending_in_retirement_eur: 60000
  target_annual_spending_is_today_eur: true
  target_annual_spending_gap_eur:
  target_annual_spending_gap_is_today_eur: true
  safe_withdrawal_rate_pct: 3.5
  current_retirement_assets_eur: 50000
  monthly_retirement_contribution_eur: 0
  expected_nominal_return_pct: 5
education:
  child_1_target_fund_eur: 20000
  child_1_target_fund_is_today_eur: true
  child_1_target_age: 18
  child_1_current_fund_eur: 5000
  child_1_expected_return_pct: 2
  child_2_target_fund_eur: 25000
  child_2_target_fund_is_today_eur: true
  child_2_target_age: 18
  child_2_current_fund_eur: 3000
  child_2_expected_return_pct: 3
  child_3_target_fund_eur: 30000
  child_3_target_fund_is_today_eur: true
  child_3_target_age: 18
  child_3_current_fund_eur: 2000
  child_3_expected_return_pct: 4
house_project:
  target_cost_eur: 100000
  target_cost_is_today_eur: true
  contingency_pct: 10
  target_date: "2030-03-15"
  current_reserved_amount_eur: 20000
  expected_return_pct: 1
assumptions:
  inflation_pct: 2
  cash_return_pct: 1
  conservative_growth_return_pct: 3
  growth_return_pct: 5
        """.strip(),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "plan-savings",
            "--inputs-path",
            str(inputs_path),
            "--output-path",
            str(output_path),
            "--as-of-date",
            "2026-03-15",
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Inflation assumption: 2.00%" in stdio.out
    assert "Total required monthly savings" in stdio.out
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["as_of_date"] == "2026-03-15"
    assert payload["inflation_pct"] == 2
    assert len(payload["goal_results"]) == 5

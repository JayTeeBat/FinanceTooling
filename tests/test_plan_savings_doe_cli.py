from __future__ import annotations

from pathlib import Path

from finance_tooling.__main__ import main


def test_plan_savings_doe_cli_writes_output(tmp_path: Path, capsys) -> None:
    base_inputs_path = tmp_path / "planning_inputs.yaml"
    doe_inputs_path = tmp_path / "doe.yaml"
    output_path = tmp_path / "doe.csv"
    base_inputs_path.write_text(
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
  essential_monthly_spend_eur: 4500
retirement:
  target_retirement_age_adult_1: 62
  target_retirement_age_adult_2: 62
  expected_annual_state_pension_eur: 60000
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
  child_1_target_fund_eur: 10000
  child_1_target_fund_is_today_eur: true
  child_1_target_age: 18
  child_1_current_fund_eur: 0
  child_1_expected_return_pct: 5
  child_2_target_fund_eur: 10000
  child_2_target_fund_is_today_eur: true
  child_2_target_age: 18
  child_2_current_fund_eur: 0
  child_2_expected_return_pct: 5
  child_3_target_fund_eur: 10000
  child_3_target_fund_is_today_eur: true
  child_3_target_age: 18
  child_3_current_fund_eur: 0
  child_3_expected_return_pct: 5
house_project:
  target_cost_eur: 0
  target_cost_is_today_eur: true
  contingency_pct: 0
  target_date: "2031-03-15"
  current_reserved_amount_eur: 0
  expected_return_pct: 1.5
assumptions:
  inflation_pct: 2.0
  cash_return_pct: 1.5
  conservative_growth_return_pct: 3.0
  growth_return_pct: 5.0
        """.strip(),
        encoding="utf-8",
    )
    doe_inputs_path.write_text(
        """
house_target_date: "2031-03-15"
house_contingency_pct: 0
ranges:
  retirement_ages: [64]
  pension_before_tax_eur: [60000]
  retirement_spending_before_tax_eur: [60000]
  kids_target_fund_eur: [10000]
  house_project_cost_eur: [0]
  inflation_pct: [1.5]
  expected_return_pct: [6.0]
        """.strip(),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "plan-savings-doe",
            "--base-inputs-path",
            str(base_inputs_path),
            "--doe-inputs-path",
            str(doe_inputs_path),
            "--output-path",
            str(output_path),
            "--as-of-date",
            "2026-03-16",
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Scenario count: 1" in stdio.out
    assert output_path.exists()

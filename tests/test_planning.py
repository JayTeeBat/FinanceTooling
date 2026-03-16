from __future__ import annotations

import json
from pathlib import Path

from finance_tooling.planning import (
    build_planning_summary,
    load_planning_inputs,
    write_planning_summary,
)


def test_build_planning_summary_computes_goal_savings() -> None:
    inputs = {
        "household": {
            "adults": {"adult_1_current_age": 38, "adult_2_current_age": 37},
            "children": {
                "child_1_current_age": 13,
                "child_2_current_age": 11,
                "child_3_current_age": 7,
            },
        },
        "liquidity": {
            "emergency_fund_target_months": 6,
            "essential_monthly_spend_eur": 4000,
        },
        "retirement": {
            "target_retirement_age_adult_1": 62,
            "target_retirement_age_adult_2": 62,
            "expected_annual_state_pension_eur": 30000,
            "expected_annual_state_pension_is_today_eur": True,
            "target_annual_spending_in_retirement_eur": 60000,
            "target_annual_spending_is_today_eur": True,
            "target_annual_spending_gap_eur": "",
            "target_annual_spending_gap_is_today_eur": True,
            "safe_withdrawal_rate_pct": 3.5,
            "current_retirement_assets_eur": 50000,
            "monthly_retirement_contribution_eur": 0,
            "expected_nominal_return_pct": 5,
        },
        "education": {
            "child_1_target_fund_eur": 20000,
            "child_1_target_fund_is_today_eur": True,
            "child_1_target_age": 18,
            "child_1_current_fund_eur": 5000,
            "child_1_expected_return_pct": 2,
            "child_2_target_fund_eur": 25000,
            "child_2_target_fund_is_today_eur": True,
            "child_2_target_age": 18,
            "child_2_current_fund_eur": 3000,
            "child_2_expected_return_pct": 3,
            "child_3_target_fund_eur": 30000,
            "child_3_target_fund_is_today_eur": True,
            "child_3_target_age": 18,
            "child_3_current_fund_eur": 2000,
            "child_3_expected_return_pct": 4,
        },
        "house_project": {
            "target_cost_eur": 100000,
            "target_cost_is_today_eur": True,
            "contingency_pct": 10,
            "target_date": "2030-03-15",
            "current_reserved_amount_eur": 20000,
            "expected_return_pct": 1,
        },
        "assumptions": {
            "inflation_pct": 2,
            "cash_return_pct": 1,
            "conservative_growth_return_pct": 3,
            "growth_return_pct": 5,
        },
    }

    summary = build_planning_summary(inputs, as_of_date=None)

    assert summary.inflation_pct == 2
    assert summary.retirement_annual_gap_today_eur == 30000
    assert summary.retirement_annual_gap_eur > summary.retirement_annual_gap_today_eur
    assert round(summary.retirement_target_capital_today_eur, 2) == 857142.86
    assert summary.retirement_target_capital_eur > summary.retirement_target_capital_today_eur
    assert summary.emergency_fund_target_eur == 24000
    goal_names = {result.goal_name for result in summary.goal_results}
    assert goal_names == {
        "retirement",
        "child_1_education",
        "child_2_education",
        "child_3_education",
        "house_expansion",
    }
    child_1_goal = next(
        result for result in summary.goal_results if result.goal_name == "child_1_education"
    )
    assert child_1_goal.inflation_adjusted_target_amount_eur > child_1_goal.base_target_amount_eur
    assert summary.total_required_monthly_saving_eur > 0


def test_write_planning_summary_outputs_json(tmp_path: Path) -> None:
    inputs = {
        "household": {
            "adults": {"adult_1_current_age": 38, "adult_2_current_age": 37},
            "children": {
                "child_1_current_age": 13,
                "child_2_current_age": 11,
                "child_3_current_age": 7,
            },
        },
        "liquidity": {
            "emergency_fund_target_months": 6,
            "essential_monthly_spend_eur": 4000,
        },
        "retirement": {
            "target_retirement_age_adult_1": 62,
            "target_retirement_age_adult_2": 62,
            "expected_annual_state_pension_eur": 30000,
            "expected_annual_state_pension_is_today_eur": True,
            "target_annual_spending_in_retirement_eur": 60000,
            "target_annual_spending_is_today_eur": True,
            "target_annual_spending_gap_eur": "",
            "target_annual_spending_gap_is_today_eur": True,
            "safe_withdrawal_rate_pct": 3.5,
            "current_retirement_assets_eur": 50000,
            "monthly_retirement_contribution_eur": 0,
            "expected_nominal_return_pct": 5,
        },
        "education": {
            "child_1_target_fund_eur": 20000,
            "child_1_target_fund_is_today_eur": True,
            "child_1_target_age": 18,
            "child_1_current_fund_eur": 5000,
            "child_1_expected_return_pct": 2,
            "child_2_target_fund_eur": 25000,
            "child_2_target_fund_is_today_eur": True,
            "child_2_target_age": 18,
            "child_2_current_fund_eur": 3000,
            "child_2_expected_return_pct": 3,
            "child_3_target_fund_eur": 30000,
            "child_3_target_fund_is_today_eur": True,
            "child_3_target_age": 18,
            "child_3_current_fund_eur": 2000,
            "child_3_expected_return_pct": 4,
        },
        "house_project": {
            "target_cost_eur": 100000,
            "target_cost_is_today_eur": True,
            "contingency_pct": 10,
            "target_date": "2030-03-15",
            "current_reserved_amount_eur": 20000,
            "expected_return_pct": 1,
        },
        "assumptions": {
            "inflation_pct": 2,
            "cash_return_pct": 1,
            "conservative_growth_return_pct": 3,
            "growth_return_pct": 5,
        },
    }
    output_path = tmp_path / "sizing.json"

    summary = build_planning_summary(inputs)
    write_planning_summary(output_path, summary)

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["retirement_target_capital_eur"] == summary.retirement_target_capital_eur
    assert loaded["inflation_pct"] == 2
    assert len(loaded["goal_results"]) == 5


def test_load_planning_inputs_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "inputs.yaml"
    path.write_text("- not-a-mapping\n", encoding="utf-8")

    try:
        load_planning_inputs(path)
    except ValueError as exc:
        assert "must be a mapping" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError")

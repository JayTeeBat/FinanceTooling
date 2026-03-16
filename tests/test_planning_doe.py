from __future__ import annotations

from pathlib import Path

from finance_tooling.planning import build_planning_doe_rows, write_planning_doe_rows


def _base_inputs() -> dict[str, object]:
    return {
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
            "essential_monthly_spend_eur": 4500,
        },
        "retirement": {
            "target_retirement_age_adult_1": 62,
            "target_retirement_age_adult_2": 62,
            "expected_annual_state_pension_eur": 60000,
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
            "child_1_target_fund_eur": 10000,
            "child_1_target_fund_is_today_eur": True,
            "child_1_target_age": 18,
            "child_1_current_fund_eur": 0,
            "child_1_expected_return_pct": 5,
            "child_2_target_fund_eur": 10000,
            "child_2_target_fund_is_today_eur": True,
            "child_2_target_age": 18,
            "child_2_current_fund_eur": 0,
            "child_2_expected_return_pct": 5,
            "child_3_target_fund_eur": 10000,
            "child_3_target_fund_is_today_eur": True,
            "child_3_target_age": 18,
            "child_3_current_fund_eur": 0,
            "child_3_expected_return_pct": 5,
        },
        "house_project": {
            "target_cost_eur": 0,
            "target_cost_is_today_eur": True,
            "contingency_pct": 0,
            "target_date": "2031-03-15",
            "current_reserved_amount_eur": 0,
            "expected_return_pct": 1.5,
        },
        "assumptions": {
            "inflation_pct": 2,
            "cash_return_pct": 1.5,
            "conservative_growth_return_pct": 3,
            "growth_return_pct": 5,
        },
    }


def test_build_planning_doe_rows_expands_grid() -> None:
    rows = build_planning_doe_rows(
        _base_inputs(),
        {
            "house_target_date": "2031-03-15",
            "house_contingency_pct": 0,
            "ranges": {
                "retirement_ages": [64, 65],
                "pension_before_tax_eur": [60000, 85000],
                "retirement_spending_before_tax_eur": [60000, 100000],
                "kids_target_fund_eur": [10000],
                "house_project_cost_eur": [0, 100000],
                "inflation_pct": [1.5],
                "expected_return_pct": [4, 8],
            },
        },
    )

    assert len(rows) == 32
    assert rows[0].total_required_monthly_saving_eur <= rows[-1].total_required_monthly_saving_eur
    assert {row.retirement_age for row in rows} == {64, 65}
    assert {row.pension_before_tax_eur for row in rows} == {60000.0, 85000.0}
    assert {row.retirement_spending_before_tax_eur for row in rows} == {60000.0, 100000.0}


def test_write_planning_doe_rows_outputs_csv(tmp_path: Path) -> None:
    rows = build_planning_doe_rows(
        _base_inputs(),
        {
            "house_target_date": "2031-03-15",
            "house_contingency_pct": 0,
            "ranges": {
                "retirement_ages": [64],
                "pension_before_tax_eur": [60000],
                "retirement_spending_before_tax_eur": [60000],
                "kids_target_fund_eur": [10000],
                "house_project_cost_eur": [0],
                "inflation_pct": [2.0],
                "expected_return_pct": [6],
            },
        },
    )
    output_path = tmp_path / "doe.csv"

    write_planning_doe_rows(output_path, rows)

    text = output_path.read_text(encoding="utf-8")
    assert "scenario_name" in text
    assert "total_required_monthly_saving_eur" in text

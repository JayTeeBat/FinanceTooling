"""Planning calculations for household goal sizing."""

from __future__ import annotations

import copy
import csv
import itertools
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class GoalSizingResult:
    """Monthly savings requirement for a single goal."""

    goal_name: str
    base_target_amount_eur: float
    inflation_adjusted_target_amount_eur: float
    current_amount_eur: float
    years_to_goal: float
    expected_return_pct: float
    required_monthly_saving_eur: float


@dataclass(frozen=True)
class PlanningSummary:
    """Computed savings requirements across goals."""

    as_of_date: str
    inflation_pct: float
    retirement_target_capital_eur: float
    retirement_target_capital_today_eur: float
    retirement_annual_gap_eur: float
    retirement_annual_gap_today_eur: float
    emergency_fund_target_eur: float
    goal_results: tuple[GoalSizingResult, ...]
    total_required_monthly_saving_eur: float


@dataclass(frozen=True)
class PlanningDoeRow:
    """Flattened scenario row for planning DOE output."""

    scenario_name: str
    retirement_age: int
    pension_before_tax_eur: float
    retirement_spending_before_tax_eur: float
    kids_target_fund_eur: float
    house_project_cost_eur: float
    inflation_pct: float
    expected_return_pct: float
    required_monthly_retirement_saving_eur: float
    required_monthly_education_saving_eur: float
    required_monthly_house_saving_eur: float
    total_required_monthly_saving_eur: float


def load_planning_inputs(path: Path) -> dict[str, Any]:
    """Load planning inputs from a YAML file."""
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Planning inputs must be a mapping: {path}")
    return loaded


def _require_section(inputs: dict[str, Any], key: str) -> dict[str, Any]:
    section = inputs.get(key)
    if not isinstance(section, dict):
        raise ValueError(f"Missing or invalid '{key}' section in planning inputs.")
    return section


def _require_number(section: dict[str, Any], key: str) -> float:
    value = section.get(key)
    if value is None:
        raise ValueError(f"Missing required numeric value: {key}")
    if isinstance(value, bool):
        raise ValueError(f"Invalid numeric value for {key}: {value}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for {key}: {value}") from exc


def _optional_number(section: dict[str, Any], key: str, *, default: float = 0.0) -> float:
    value = section.get(key)
    if value in {None, ""}:
        return default
    if isinstance(value, bool):
        raise ValueError(f"Invalid numeric value for {key}: {value}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for {key}: {value}") from exc


def _require_sequence(section: dict[str, Any], key: str) -> tuple[float, ...]:
    raw_value = section.get(key)
    if not isinstance(raw_value, list) or not raw_value:
        raise ValueError(f"Missing or invalid non-empty list value: {key}")
    parsed_values: list[float] = []
    for value in raw_value:
        if isinstance(value, bool):
            raise ValueError(f"Invalid numeric list value for {key}: {value}")
        try:
            parsed_values.append(float(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid numeric list value for {key}: {value}") from exc
    return tuple(parsed_values)


def _require_iso_date(section: dict[str, Any], key: str) -> date:
    raw_value = section.get(key)
    if not raw_value:
        raise ValueError(f"Missing required ISO date value: {key}")
    if isinstance(raw_value, date):
        return raw_value
    if not isinstance(raw_value, str):
        raise ValueError(f"Invalid ISO date value for {key}: {raw_value}")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date value for {key}: {raw_value}") from exc


def _optional_bool(section: dict[str, Any], key: str, *, default: bool) -> bool:
    value = section.get(key)
    if value in {None, ""}:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"Invalid boolean value for {key}: {value}")


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


def _years_until(target_date: date, *, as_of_date: date) -> float:
    delta_days = (target_date - as_of_date).days
    return max(0.0, delta_days / 365.25)


def _inflate_amount(
    amount_eur: float,
    *,
    years: float,
    inflation_pct: float,
    amount_is_today_eur: bool,
) -> float:
    if not amount_is_today_eur:
        return amount_eur
    return amount_eur * (1.0 + inflation_pct / 100.0) ** max(0.0, years)


def build_planning_summary(
    inputs: dict[str, Any],
    *,
    as_of_date: date | None = None,
) -> PlanningSummary:
    """Build goal-level monthly savings requirements from planning inputs."""
    effective_date = as_of_date or date.today()
    household = _require_section(inputs, "household")
    retirement = _require_section(inputs, "retirement")
    education = _require_section(inputs, "education")
    house_project = _require_section(inputs, "house_project")
    liquidity = _require_section(inputs, "liquidity")
    assumptions = _require_section(inputs, "assumptions")
    inflation_pct = _require_number(assumptions, "inflation_pct")

    adult_1_age = _require_number(_require_section(household, "adults"), "adult_1_current_age")
    adult_2_age = _require_number(_require_section(household, "adults"), "adult_2_current_age")
    retirement_age_1 = _require_number(retirement, "target_retirement_age_adult_1")
    retirement_age_2 = _require_number(retirement, "target_retirement_age_adult_2")
    years_to_retirement = max(
        0.0,
        min(retirement_age_1 - adult_1_age, retirement_age_2 - adult_2_age),
    )

    target_spending_today = _require_number(retirement, "target_annual_spending_in_retirement_eur")
    target_spending_nominal = _inflate_amount(
        target_spending_today,
        years=years_to_retirement,
        inflation_pct=inflation_pct,
        amount_is_today_eur=_optional_bool(
            retirement,
            "target_annual_spending_is_today_eur",
            default=True,
        ),
    )
    state_pension_today = _require_number(retirement, "expected_annual_state_pension_eur")
    state_pension_nominal = _inflate_amount(
        state_pension_today,
        years=years_to_retirement,
        inflation_pct=inflation_pct,
        amount_is_today_eur=_optional_bool(
            retirement,
            "expected_annual_state_pension_is_today_eur",
            default=True,
        ),
    )
    annual_spending_gap = retirement.get("target_annual_spending_gap_eur")
    if annual_spending_gap in {None, ""}:
        annual_spending_gap_today = max(0.0, target_spending_today - state_pension_today)
        annual_spending_gap_value = max(0.0, target_spending_nominal - state_pension_nominal)
    else:
        annual_spending_gap_today = _require_number(retirement, "target_annual_spending_gap_eur")
        annual_spending_gap_value = _inflate_amount(
            annual_spending_gap_today,
            years=years_to_retirement,
            inflation_pct=inflation_pct,
            amount_is_today_eur=_optional_bool(
                retirement,
                "target_annual_spending_gap_is_today_eur",
                default=True,
            ),
        )
    safe_withdrawal_rate_pct = _require_number(retirement, "safe_withdrawal_rate_pct")
    if safe_withdrawal_rate_pct <= 0:
        raise ValueError("safe_withdrawal_rate_pct must be greater than zero.")
    retirement_target_capital = annual_spending_gap_value / (safe_withdrawal_rate_pct / 100.0)
    retirement_target_capital_today = annual_spending_gap_today / (safe_withdrawal_rate_pct / 100.0)
    retirement_return_pct = _require_number(retirement, "expected_nominal_return_pct")
    current_retirement_assets = _require_number(retirement, "current_retirement_assets_eur")

    goal_results: list[GoalSizingResult] = [
        GoalSizingResult(
            goal_name="retirement",
            base_target_amount_eur=retirement_target_capital_today,
            inflation_adjusted_target_amount_eur=retirement_target_capital,
            current_amount_eur=current_retirement_assets,
            years_to_goal=years_to_retirement,
            expected_return_pct=retirement_return_pct,
            required_monthly_saving_eur=_required_monthly_contribution(
                target_amount_eur=retirement_target_capital,
                current_amount_eur=current_retirement_assets,
                years_to_goal=years_to_retirement,
                expected_return_pct=retirement_return_pct,
            ),
        )
    ]

    children = _require_section(household, "children")
    for child_number in (1, 2, 3):
        current_age = _require_number(children, f"child_{child_number}_current_age")
        target_age = _require_number(education, f"child_{child_number}_target_age")
        years_to_goal = max(0.0, target_age - current_age)
        target_amount = _require_number(education, f"child_{child_number}_target_fund_eur")
        inflation_adjusted_target_amount = _inflate_amount(
            target_amount,
            years=years_to_goal,
            inflation_pct=inflation_pct,
            amount_is_today_eur=_optional_bool(
                education,
                f"child_{child_number}_target_fund_is_today_eur",
                default=True,
            ),
        )
        current_amount = _require_number(education, f"child_{child_number}_current_fund_eur")
        expected_return_pct = _require_number(
            education,
            f"child_{child_number}_expected_return_pct",
        )
        goal_results.append(
            GoalSizingResult(
                goal_name=f"child_{child_number}_education",
                base_target_amount_eur=target_amount,
                inflation_adjusted_target_amount_eur=inflation_adjusted_target_amount,
                current_amount_eur=current_amount,
                years_to_goal=years_to_goal,
                expected_return_pct=expected_return_pct,
                required_monthly_saving_eur=_required_monthly_contribution(
                    target_amount_eur=inflation_adjusted_target_amount,
                    current_amount_eur=current_amount,
                    years_to_goal=years_to_goal,
                    expected_return_pct=expected_return_pct,
                ),
            )
        )

    house_target_cost = _require_number(house_project, "target_cost_eur")
    contingency_pct = _optional_number(house_project, "contingency_pct")
    house_target_date = _require_iso_date(house_project, "target_date")
    house_years = _years_until(house_target_date, as_of_date=effective_date)
    house_target_amount_today = house_target_cost * (1.0 + contingency_pct / 100.0)
    house_target_amount = _inflate_amount(
        house_target_amount_today,
        years=house_years,
        inflation_pct=inflation_pct,
        amount_is_today_eur=_optional_bool(
            house_project,
            "target_cost_is_today_eur",
            default=True,
        ),
    )
    current_house_reserve = _require_number(house_project, "current_reserved_amount_eur")
    house_return_pct = _require_number(house_project, "expected_return_pct")
    goal_results.append(
        GoalSizingResult(
            goal_name="house_expansion",
            base_target_amount_eur=house_target_amount_today,
            inflation_adjusted_target_amount_eur=house_target_amount,
            current_amount_eur=current_house_reserve,
            years_to_goal=house_years,
            expected_return_pct=house_return_pct,
            required_monthly_saving_eur=_required_monthly_contribution(
                target_amount_eur=house_target_amount,
                current_amount_eur=current_house_reserve,
                years_to_goal=house_years,
                expected_return_pct=house_return_pct,
            ),
        )
    )

    emergency_target = _require_number(liquidity, "emergency_fund_target_months") * _require_number(
        liquidity, "essential_monthly_spend_eur"
    )
    total_required = sum(result.required_monthly_saving_eur for result in goal_results)
    return PlanningSummary(
        as_of_date=effective_date.isoformat(),
        inflation_pct=inflation_pct,
        retirement_target_capital_eur=retirement_target_capital,
        retirement_target_capital_today_eur=retirement_target_capital_today,
        retirement_annual_gap_eur=annual_spending_gap_value,
        retirement_annual_gap_today_eur=annual_spending_gap_today,
        emergency_fund_target_eur=emergency_target,
        goal_results=tuple(goal_results),
        total_required_monthly_saving_eur=total_required,
    )


def write_planning_summary(path: Path, summary: PlanningSummary) -> None:
    """Write planning summary to a JSON file."""
    payload = asdict(summary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_planning_doe_rows(
    base_inputs: dict[str, Any],
    doe_inputs: dict[str, Any],
    *,
    as_of_date: date | None = None,
) -> tuple[PlanningDoeRow, ...]:
    """Build a scenario grid by varying selected planning assumptions."""
    ranges = _require_section(doe_inputs, "ranges")
    house_target_date = _require_iso_date(doe_inputs, "house_target_date")
    house_contingency_pct = _optional_number(doe_inputs, "house_contingency_pct")
    retirement_ages = _require_sequence(ranges, "retirement_ages")
    pension_values = _require_sequence(ranges, "pension_before_tax_eur")
    retirement_spending_values = _require_sequence(
        ranges,
        "retirement_spending_before_tax_eur",
    )
    kids_fund_sizes = _require_sequence(ranges, "kids_target_fund_eur")
    house_costs = _require_sequence(ranges, "house_project_cost_eur")
    inflation_values = _require_sequence(ranges, "inflation_pct")
    expected_returns = _require_sequence(ranges, "expected_return_pct")

    rows: list[PlanningDoeRow] = []
    for (
        retirement_age,
        pension_before_tax_eur,
        retirement_spending_before_tax_eur,
        kids_target_fund_eur,
        house_project_cost_eur,
        inflation_pct,
        expected_return_pct,
    ) in itertools.product(
        retirement_ages,
        pension_values,
        retirement_spending_values,
        kids_fund_sizes,
        house_costs,
        inflation_values,
        expected_returns,
    ):
        scenario_inputs = copy.deepcopy(base_inputs)
        retirement = _require_section(scenario_inputs, "retirement")
        education = _require_section(scenario_inputs, "education")
        house_project = _require_section(scenario_inputs, "house_project")
        assumptions = _require_section(scenario_inputs, "assumptions")

        retirement["target_retirement_age_adult_1"] = retirement_age
        retirement["target_retirement_age_adult_2"] = retirement_age
        retirement["expected_annual_state_pension_eur"] = pension_before_tax_eur
        retirement["target_annual_spending_in_retirement_eur"] = (
            retirement_spending_before_tax_eur
        )
        retirement["expected_nominal_return_pct"] = expected_return_pct
        for child_number in (1, 2, 3):
            education[f"child_{child_number}_target_fund_eur"] = kids_target_fund_eur
            education[f"child_{child_number}_expected_return_pct"] = expected_return_pct
        house_project["target_cost_eur"] = house_project_cost_eur
        house_project["target_date"] = house_target_date.isoformat()
        house_project["contingency_pct"] = house_contingency_pct
        assumptions["inflation_pct"] = inflation_pct

        summary = build_planning_summary(scenario_inputs, as_of_date=as_of_date)
        retirement_saving = next(
            result.required_monthly_saving_eur
            for result in summary.goal_results
            if result.goal_name == "retirement"
        )
        education_saving = sum(
            result.required_monthly_saving_eur
            for result in summary.goal_results
            if result.goal_name.endswith("_education")
        )
        house_saving = next(
            result.required_monthly_saving_eur
            for result in summary.goal_results
            if result.goal_name == "house_expansion"
        )
        rows.append(
            PlanningDoeRow(
                scenario_name=(
                    f"ret{int(retirement_age)}"
                    f"_p{int(pension_before_tax_eur / 1000)}k"
                    f"_sp{int(retirement_spending_before_tax_eur / 1000)}k"
                    f"_kids{int(kids_target_fund_eur / 1000)}k"
                    f"_house{int(house_project_cost_eur / 1000)}k"
                    f"_infl{str(inflation_pct).replace('.', '_')}"
                    f"_r{str(expected_return_pct).replace('.', '_')}"
                ),
                retirement_age=int(retirement_age),
                pension_before_tax_eur=float(pension_before_tax_eur),
                retirement_spending_before_tax_eur=float(retirement_spending_before_tax_eur),
                kids_target_fund_eur=float(kids_target_fund_eur),
                house_project_cost_eur=float(house_project_cost_eur),
                inflation_pct=float(inflation_pct),
                expected_return_pct=float(expected_return_pct),
                required_monthly_retirement_saving_eur=retirement_saving,
                required_monthly_education_saving_eur=education_saving,
                required_monthly_house_saving_eur=house_saving,
                total_required_monthly_saving_eur=summary.total_required_monthly_saving_eur,
            )
        )
    return tuple(sorted(rows, key=lambda row: row.total_required_monthly_saving_eur))


def write_planning_doe_rows(path: Path, rows: tuple[PlanningDoeRow, ...]) -> None:
    """Write planning DOE rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("Cannot write empty DOE rows.")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

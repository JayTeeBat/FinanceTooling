# Household Finance 360

This folder is a lightweight operating system for your household finances.
It complements the transaction-ingestion pipeline by giving you one place to
organize:

- income and recurring expenses
- monthly budget tracking
- long-term goals
- net worth tracking
- decision logs and periodic reviews

Suggested use:

1. Keep the repo pipeline for statement ingestion, normalization, and
   categorization.
2. Use this folder for planning, targets, and higher-level monitoring.
3. Review the whole system monthly, quarterly, and annually.

## Structure

- `00_household_profile.md`
  Household snapshot, goals, account ownership, and core planning assumptions.
- `01_accounts_inventory.csv`
  Master list of accounts, loans, wrappers, owners, and purpose.
- `02_monthly_cashflow_budget.csv`
  Monthly budget plan and actuals by category.
- `03_net_worth_snapshot.csv`
  Point-in-time balance tracking for assets and liabilities.
- `04_goal_plan.yaml`
  Goal definitions for retirement, education, house expansion, and reserves.
- `05_investment_policy.md`
  Risk rules, account-role mapping, and asset-location policy.
- `06_monitoring_checklist.md`
  Monthly, quarterly, and annual review checklist.
- `07_decision_log.md`
  Record major money decisions and the reasoning behind them.
- `08_annual_review_template.md`
  Year-end review template.
- `09_planning_inputs.yaml`
  Baseline assumptions for retirement, education, house project, and savings.
- `10_scenario_matrix.csv`
  Side-by-side scenario comparison table for required monthly savings.
- `11_sizing_guide.md`
  Guide for turning planning assumptions into monthly savings targets.
- `12_sizing_output.json`
  Generated output from the savings-sizing command.
- `workflow.md`
  Step-by-step operating cadence for using the files.

## Calculator

Use the built-in sizing command to convert assumptions into monthly savings
needs:

```bash
uv run plan-savings
```

The calculator explicitly supports hypotheses on:

- inflation
- stock / portfolio yield by goal
- retirement age
- kids fund size

Optional overrides:

```bash
uv run plan-savings \
  --inputs-path planning/household_finance_360/09_planning_inputs.yaml \
  --output-path planning/household_finance_360/12_sizing_output.json \
  --as-of-date 2026-03-15
```

## Recommended operating model

- Monthly: update cashflow, new balances, and goal progress.
- Quarterly: rebalance if needed, refresh forecasts, and review spending drift.
- Annually: refresh assumptions, tax strategy, insurance, estate planning, and
  long-term targets.

## Design principles

- One source of truth per topic.
- Keep short-term cash needs separate from long-term investments.
- Manage each goal on its own timeline.
- Track both flows (income/spending) and stock (net worth).
- Keep a written decision log so future choices remain consistent.

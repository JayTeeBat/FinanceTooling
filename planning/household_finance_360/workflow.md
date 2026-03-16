# Workflow

This workflow is designed to be simple enough to maintain every month while
still giving a full view of household finances.

## 1. Set up the structure once

Fill these files first:

- `00_household_profile.md`
- `01_accounts_inventory.csv`
- `04_goal_plan.yaml`
- `05_investment_policy.md`

These four files define the household baseline:

- who owns what
- what each account is for
- what the main goals are
- how money should be allocated by time horizon

## 2. Monthly workflow

Run this cadence once per month after the latest statements are imported.

1. Run the repo ingestion flow if you want refreshed categorized transaction
   outputs.
2. Update `02_monthly_cashflow_budget.csv` with:
   - net income
   - fixed expenses
   - variable expenses
   - transfers to savings/investments
3. Update `03_net_worth_snapshot.csv` with end-of-month balances.
4. Review `04_goal_plan.yaml` and refresh:
   - current balances
   - target amounts
   - target dates
   - estimated funding gaps
5. Add any notable decisions to `07_decision_log.md`.
6. If assumptions changed, refresh `09_planning_inputs.yaml` and your active
   rows in `10_scenario_matrix.csv`.

Monthly outputs:

- spending vs budget
- savings rate
- current net worth
- progress toward house / education / retirement goals
- whether the required monthly savings still fit the household surplus

## 3. Quarterly workflow

Every quarter:

1. Review whether actual spending matches the household priorities.
2. Check if the house-expansion timeline changed.
3. Reduce investment risk for nearer education goals as children age.
4. Verify retirement contributions are still on track.
5. Review account sprawl and close anything redundant.

Quarterly questions:

- Are we overspending in any recurring category?
- Is medium-term money exposed to too much market risk?
- Are retirement contributions being squeezed by short-term projects?
- Do our account wrappers still match the purpose of each goal?

## 4. Annual workflow

Once a year, complete `08_annual_review_template.md`.

Focus on:

- household income changes
- tax optimization opportunities
- insurance coverage
- beneficiary / estate review
- major capital projects
- target allocation by goal
- next-year savings plan

## 5. Recommended dashboard metrics

Track these metrics consistently:

- net monthly income
- monthly savings amount
- savings rate
- fixed-cost ratio
- total net worth
- liquid net worth
- debt outstanding
- retirement assets
- education assets
- house-project assets
- funding gap by goal

## 6. Suggested planning rules for your situation

For a family with 3 children, a mortgage, and a medium-term house expansion:

- Keep emergency reserves separate from project savings.
- Keep house-expansion money low risk if needed within 5 years.
- Manage education on separate child timelines.
- Keep retirement as a persistent monthly contribution, not a residual goal.
- Do not prioritize prepaying a 2.1% fixed mortgage over diversified long-term
  investing unless your broader risk tolerance or liquidity needs justify it.

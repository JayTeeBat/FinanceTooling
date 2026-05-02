# Planning Stage Integration Plan

## Summary

The pipeline needs a first-class `planning` stage after `transform`.

V1 should focus on transaction-derived KPIs built from the canonical transform
corpus. It should not fold in the existing scenario-planning tools yet. Those
tools remain useful, but they answer a different question: long-range goal
sizing from assumptions rather than KPI evaluation from observed transactions.

The planning stage should consume canonical transform outputs, compute
decision-facing KPIs, and emit both machine-readable artifacts and a dedicated
HTML dashboard.

## Chosen Defaults

- Public stage name: `planning`
- Primary CLI: `uv run planning`
- Primary input: `processed/transform/transform_transactions.parquet`
- Primary output directory: `processed/planning/`
- Initial UI surface: separate `planning_dashboard.html`
- V1 scope: transaction-derived cashflow health KPIs
- Budgeting role: included when budget targets exist, but not the whole stage

## Stage Responsibility

`planning` should be downstream of `transform`.

It should:

- read canonical transaction outputs
- build a traceable monthly planning ledger
- compute cashflow health KPIs
- compute budget-vs-actual status when targets are configured
- write planning artifacts for reporting and review
- render a dedicated HTML planning dashboard

It should not:

- parse raw statement files
- re-run ingest
- re-run transform
- perform category matching
- infer account boundaries
- mutate review state or transaction overrides

## Public Interface

Recommended command shape:

```text
uv run planning
uv run planning --input-transactions-path <path>
uv run planning --output-dir <dir>
uv run planning --budget-targets-path <path>
uv run planning --verbose
```

Default paths should come from the existing settings object where possible:

- input transactions: `settings.master_parquet_path`
- budget targets: `settings.budget_targets_path`
- output directory: `settings.output_path.parent`

The command should fail clearly if the canonical transform output is missing.
It should warn, not fail, when budget targets are absent.

## Planned Artifacts

The stage should write:

- `planning_ledger.parquet`
- `planning_ledger.csv`
- `planning_kpi_summary.json`
- `planning_budget_status.csv`
- `planning_dashboard.html`

`planning_ledger` is the audit base. All dashboard and summary totals should be
traceable back to ledger rows by `transaction_id`.

## KPI Model

V1 KPIs should be grounded in canonical fields:

- `transaction_id`
- `booking_date`
- `category_id`
- `reporting_category_id`
- `cashflow_type`
- `economic_role`
- `decision_role`
- `amount_eur`
- `project`

Core V1 KPI families:

- true household income
- true spend excluding transfers and excluded rows
- fixed versus variable expense
- essential versus discretionary spend
- savings flows
- investment flows
- debt-service flows
- tax flows
- planning surplus
- savings rate
- budget target utilization when targets exist
- unknown or excluded semantic exposure for review

The stage should prefer semantic fields over display labels and sign-only
heuristics.

## Technical Recommendations

Reuse existing planning helpers first:

- `build_monthly_planning_ledger(...)`
- `build_budget_status(...)`
- `load_budget_config(...)`

Add a small planning summary builder for monthly and YTD KPI aggregation. Keep
that builder separate from the HTML renderer so JSON, CSV, and dashboard output
all share the same definitions.

Keep the existing scenario-planning commands separate for now:

- `plan-savings`
- `plan-savings-doe`
- `plan-hypothesis-page`

Those commands can later be linked to observed KPI outputs, but they should not
define the first integrated planning stage.

## HTML Surface

Render a dedicated `planning_dashboard.html`.

The first version should be an operational dashboard rather than a marketing or
scenario page. It should emphasize:

- monthly KPI trend cards
- YTD KPI cards
- budget status table
- planning bucket breakdown
- semantic data-quality warnings
- drill-down links or embedded transaction IDs where practical

The existing `transform_dashboard.html` should remain stable while this stage
is introduced.

`update` should invoke `planning` by default after `transform`; use
`--skip-planning` to keep the old transform-only stop point.

## Test Plan

Add tests for:

- CLI dispatch and default path resolution
- missing transform output failure
- missing budget target warning
- planning ledger generation from a small canonical fixture
- KPI summary correctness for income, expense, fixed, variable, essential,
  discretionary, savings, investment, debt-service, tax, excluded, and unknown
  rows
- budget status generation when targets are configured
- HTML renderer writes a self-contained document with valid embedded JSON

Acceptance criteria:

- `planning` does not invoke ingest or transform
- all KPI totals reconcile to `planning_ledger`
- excluded rows do not affect household cashflow KPIs
- transfer rows affect only the planning buckets implied by canonical semantics
- the HTML output is separate from the existing transform dashboard

## Follow-Up Integration

After V1 lands, evaluate whether to connect observed planning KPIs to the
scenario-planning workspace. A useful later bridge would compare actual savings,
investment, and debt-service flows against required monthly goal funding from
the existing household planning engine.

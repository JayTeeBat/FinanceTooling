# Transaction Model Improvement Plan

## End Goal

The transaction model should support a personal finance tool that can generate
trusted high-level KPIs and let an operator drill from each KPI back to the
transactions that explain it.

The target product should make it easy to answer questions such as:

- How much true income did the household receive?
- How much was spent, excluding internal transfers and explicitly excluded
  flows?
- What share of spending is fixed versus variable?
- What share of spending is essential versus discretionary?
- How much money moved into savings, investments, or debt repayment?
- Which transactions, categories, accounts, or review gaps explain a KPI?

The model should therefore preserve durable transaction facts while projecting
multiple reporting surfaces from those facts:

- purpose category: what the transaction was for
- cash movement: what happened to household cash
- economic role: whether the flow is income, fixed expense, variable expense,
  other expense, transfer, or excluded
- decision role: whether the flow supports essential spend, discretionary
  spend, savings, investment, debt service, tax, or another decision surface
- account boundary: whether money moved inside or outside the household account
  perimeter
- review quality: whether classification is rule-derived, manually reviewed,
  overridden, uncertain, or uncategorized

## Current Assessment

The current architecture is a strong base.

- `category_id` is already the durable semantic assignment.
- `reporting_category_id`, `category`, and `subcategory` are derived reporting
  labels.
- `cashflow_type` separates household cash movement from purpose category.
- `economic_role` is being expanded to separate true income, fixed expenses,
  variable expenses, generic expense-side activity, transfers, and excluded
  flows.
- Canonical outputs include source lineage, FX-enriched amounts, review state,
  account-boundary fields, and classification provenance.

The main remaining gap is that financial decision surfaces are not yet
first-class enough. Fixed versus variable expenses, essential versus
discretionary spend, savings, investment, and debt-service interpretation should
not be squeezed into the purpose taxonomy. They are orthogonal reporting
dimensions derived from taxonomy metadata, account rules, recurring-pattern
signals, and explicit overrides.

The current implementation direction is to encode fixed versus variable expense
directly in `economic_role`. This plan accepts that as the new starting point.
The next step is to make the expanded role contract explicit and consistent
across taxonomy, transform, summaries, and dashboards.

Known current inconsistency: some rows can have `economic_role = transfer` while
their `cashflow_type` remains `in` or `out`. This happens when taxonomy or
classification identifies a row as transfer-like, but account-boundary
resolution cannot prove both sides are internal household accounts. In that
case, current cashflow resolution falls back to the transaction sign, while
economic-role resolution can still inherit transfer semantics from taxonomy.
For example, a February 2026 row categorized as `Transfers / Account Transfer`
with only `from_account_type = internal` and an unknown destination may become
`cashflow_type = out` and `economic_role = transfer`.

This mismatch is confusing for dashboards. A metric named "transfer volume"
must state whether it counts all transfer-role/category rows or only neutral
internal transfers. Going forward, taxonomy-declared `cashflow_type` should be
enforced unless an explicit override or stronger account-boundary rule says
otherwise.

Target `economic_role` values:

- `income`
- `fixed_expense`
- `variable_expense`
- `expense`
- `transfer`
- `exclude`
- `unknown`

Use `expense` only when a transaction is expense-side but fixed/variable status
is not yet known. Use `unknown` only when the pipeline cannot safely resolve the
economic role at all.

Keep `decision_role` separate. It should answer a different question:
essential/discretionary/savings/investment/debt/tax/excluded. That keeps
`economic_role` from becoming a catch-all for every dashboard slice.

## Target Model

Keep the canonical transaction row as the source of truth, with three broad
groups of fields.

### Durable Facts

These fields identify what happened and where the row came from:

- `transaction_id`
- `booking_date`
- `description`
- `amount_native`
- `currency`
- `amount_eur`
- `fx_rate_to_eur`
- `bank`
- `account_label`
- `source_document_id`
- `source_file`
- `source_record_index`
- `parser`

### Durable Assignment

These fields describe stable operator intent:

- `category_id`: durable purpose bucket
- transaction overrides by `transaction_id` or selector
- project tags where a transaction belongs to a known life/project context
- review state

`category_id` should stay purpose-first. It should not encode merchant identity,
payment channel, billing cadence, fixed/variable status, or review state.

### Derived Reporting Semantics

These fields are recomputed during transform and may evolve as reporting policy
improves:

- `reporting_category_id`
- `category`
- `subcategory`
- `cashflow_type`: `in`, `out`, `transfer`, `exclude`, `unknown`
- `economic_role`: `income`, `fixed_expense`, `variable_expense`, `expense`,
  `transfer`, `exclude`, `unknown`
- `decision_role`: `essential`, `discretionary`, `savings`, `investment`,
  `debt_service`, `tax`, `excluded`, `unknown`
- account-boundary fields: `from_account_ref`, `to_account_ref`,
  `from_account_type`, `to_account_type`, `account_inference_source`

Unknown should be explicit. For financial decisions, an unknown value is better
than a confident-looking guess.

## Derivation Rules

The semantic order should be deterministic and explainable.

1. Classify the transaction into durable `category_id`.
2. Apply transaction-level overrides.
3. Resolve `reporting_category_id`, `category`, and `subcategory` from taxonomy.
4. Infer account boundaries from statement account registry and counterparty
   rules.
5. Resolve `cashflow_type`:
   - explicit transaction override wins
   - taxonomy-declared `cashflow_type` is enforced by default
   - internal-to-internal account movement becomes `transfer`
   - excluded taxonomy/reporting policy becomes `exclude`
   - otherwise sign determines `in` or `out`
6. Resolve `economic_role`:
   - `transfer` and `exclude` follow `cashflow_type`
   - true income taxonomy or employer evidence becomes `income`
   - taxonomy metadata can classify expense-side flows as `fixed_expense` or
     `variable_expense`
   - unresolved expense-side flows become `expense` or, if policy chooses a
     conservative default, `variable_expense`
7. Resolve decision dimensions:
   - taxonomy metadata provides default `decision_role`
   - account-boundary and transfer subtype can refine savings, investment, and
     debt-service roles
   - transaction overrides remain the escape hatch

## Example Projections

| Transaction | Purpose category | Cashflow | Economic role | Decision role |
| --- | --- | --- | --- | --- |
| Salary payment | `income.salary` | `in` | `income` | `unknown` |
| Grocery purchase | `groceries.food_at_home` | `out` | `variable_expense` | `essential` |
| Grocery refund | `groceries.food_at_home` | `in` | `variable_expense` | `essential` |
| Rent payment | `housing.rent` | `out` | `fixed_expense` | `essential` |
| Transfer to owned savings | `transfers.savings_transfer` | `transfer` | `transfer` | `savings` |
| Broker contribution | `transfers.investment_transfer` | `transfer` | `transfer` | `investment` |
| Friend reimbursement for shared dinner | `excluded.shared_expense_settlement` | `exclude` | `exclude` | `excluded` |

## Multi-PR Breakdown

### PR 1: Document The Target Model

Status: this document.

- Record the end goal and target semantic model.
- Clarify which fields are durable facts, durable assignments, and derived
  reporting semantics.
- State that fixed/variable analysis starts in expanded `economic_role`, while
  `decision_role` remains a separate dimension.
- Capture an incremental PR path so future implementation work can stay small.

### PR 2: Harden The Expanded `economic_role` Contract

- Add or finalize typed constants/shared semantic helpers for expanded
  `economic_role` values.
- Define expense-like roles as `expense`, `fixed_expense`, and
  `variable_expense`.
- Make taxonomy parsing, rules, defaults, normalization, summary metrics, and
  dashboard code accept the same role vocabulary.
- Make the fallback policy explicit: either unresolved spend-side rows become
  `expense`, or ordinary unresolved outflows become `variable_expense`.
- Add compatibility handling for older canonical data that only has
  `economic_role = expense`.

### PR 3: Add `decision_role` Contracts

- Add typed constants or shared semantic helpers for `decision_role`.
- Extend taxonomy config parsing to accept optional `decision_role` metadata.
- Add a canonical output column for `decision_role`.
- Recompute them during transform alongside category labels, `cashflow_type`,
  and `economic_role`.
- Default unresolved values to `unknown`.
- Add compatibility handling for existing canonical parquet files missing the
  new columns.

### PR 4: Populate Baseline Taxonomy Metadata

- Add conservative expanded `economic_role` and `decision_role` defaults to the
  starter taxonomy.
- Mark obvious fixed-expense/essential buckets such as rent, utilities,
  insurance, and local taxes.
- Mark obvious variable-expense/essential buckets such as groceries and routine
  transport.
- Mark obvious variable-expense/discretionary buckets such as dining, shopping,
  and leisure.
- Leave ambiguous buckets as `unknown` until they have a stable policy.

### PR 5: Strengthen Account Boundary Semantics

- Document the account registry as part of the finance model, not just a helper
  for transfer detection.
- Add or refine diagnostics for unresolved account sides and
  category-versus-account-boundary conflicts.
- Use account-boundary signals to identify internal savings and investment
  movement without counting them as income or expense.
- Keep parser-provided `bank` and `account_label` as source context; introduce a
  canonical account reference only when the account config can populate it
  reliably.

### PR 6: Align KPI Computation On Canonical Semantics

- Refactor older reporting helpers that still rely on sign-only logic or
  `category == Transfers`.
- Standardize KPI definitions:
  - income from `economic_role == income`
  - expenses from expense-like economic roles: `expense`, `fixed_expense`, and
    `variable_expense`
  - transfers from `cashflow_type == transfer`
  - exclusions from `cashflow_type == exclude` or `economic_role == exclude`
  - fixed/variable split from `economic_role`
  - essential/discretionary/savings/investment/debt/tax views from
    `decision_role`
- Add regression coverage for refunds, reimbursements, internal transfers,
  excluded flows, and unknown semantics.

### PR 7: Split Overview And Transaction Explorer

- Create a high-level finance overview focused on decision KPIs.
- Create a dense transaction explorer focused on evidence and drill-down.
- Overview should show income, expenses, net cashflow, cashflow margin, transfer
  volume, savings/investment contribution, fixed/variable split,
  essential/discretionary split, uncategorized exposure, and review coverage.
- Explorer should expose transaction-level evidence: transaction ID, date,
  description, native/EUR amount, category IDs, labels, rule/source/confidence,
  cashflow type, economic role, reporting dimensions, account-boundary fields,
  project tags, reviewed state, bank/account, and source metadata.
- Keep legacy dashboard output temporarily for compatibility.

## Testing Strategy

Add tests at three levels.

### Semantic Derivation Tests

- Positive refund in a variable-expense category remains
  `economic_role = variable_expense`.
- Internal-to-internal movement becomes `cashflow_type = transfer`.
- Excluded category becomes cashflow/economic exclusion.
- Fixed/variable economic roles and decision-role fields derive from taxonomy
  metadata.
- Missing metadata produces `unknown`.
- Transaction-level overrides take precedence over derived defaults.

### Transform Contract Tests

- New columns exist in canonical parquet, CSV, and optional JSON output.
- Existing canonical data without the new columns can still be read and
  rewritten.
- Transform recomputes derived reporting fields across the full canonical
  corpus.
- Summary diagnostics report unknown counts for decision roles and unresolved
  economic roles.

### Reporting Tests

- KPI calculations use canonical semantics, not sign-only rules.
- Refunds reduce expense-side spend instead of inflating income.
- Transfers do not affect income/expense/net cashflow.
- Excluded rows do not affect personal cashflow KPIs.
- Fixed/variable economic-role splits reconcile to expense-side totals.
- Decision-role splits reconcile to their parent KPI totals.

## Acceptance Criteria

The improved model is ready when:

- every canonical transaction has explicit values for cashflow, economic role,
  and decision role;
- unknown values are visible in diagnostics and drill-down views;
- high-level KPIs can be traced back to filtered transaction rows;
- dashboard and summary calculations use the same semantic definitions;
- review/import workflows can correct category and exceptional semantics without
  forcing broad taxonomy rewrites;
- the purpose taxonomy remains understandable and stable.

## Non-Goals

- Do not turn `category_id` into a catch-all for every analysis surface.
- Do not silently rewrite historical `category_id` values as part of ordinary
  transform runs.
- Do not infer fixed/variable or essential/discretionary status from merchant
  names alone when taxonomy/account evidence is insufficient.
- Do not add a separate `expense_nature` field unless expanded
  `economic_role` proves too overloaded for stable reporting.
- Do not hide unknown semantics inside dashboard totals without diagnostics.

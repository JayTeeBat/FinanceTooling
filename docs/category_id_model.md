# Stable `category_id` Model

This repository now separates transaction categorization into two layers:

- durable assignment: `category_id`
- derived reporting projection: `reporting_category_id`, `category`, `subcategory`

## Core Idea

`category_id` is the durable semantic key stored on each transaction.

Examples:

- `shopping.marketplace`
- `groceries.supermarket`
- `income.salary`
- `transfers.bank_transfer`

The reporting layer is rebuilt on every real `transform`:

- `reporting_category_id`
- `category`
- `subcategory`
- `cashflow_type`
- `economic_role`

That means label cleanup is automatic, but historical semantic reassignment is
not.

Semantic split:

- `cashflow_type` describes household cash movement
  - `transfer` for owned-account movement
  - `exclude` for explicitly excluded flows
  - otherwise sign-based: positive => `in`, negative => `out`
- `economic_role` describes economic meaning
  - `income` for true income categories
  - `expense` for ordinary spend and expense-side inflows such as refunds or
    reimbursements
  - `transfer` / `exclude` follow final `cashflow_type`

## Config Model

`category_rules.yaml` is ID-first:

```yaml
taxonomy:
  shopping.marketplace:
    labels:
      category: Shopping
      subcategory: Marketplace
    economic_role: expense
    status: active

  dining.restaurants:
    deprecated_to: leisure.dining_out
    labels:
      category: Dining
      subcategory: Restaurants
    status: deprecated

rules:
  - id: shopping.amazon
    category_id: shopping.marketplace
    match: contains
    patterns:
      - amazon
```

`transaction_overrides.yaml` should prefer `category_id`, though legacy
`category` / `subcategory` inputs are still accepted during migration.

## Transform Behavior

Default `transform` does this:

1. classify staged rows to durable `category_id`
2. apply transaction overrides and review edits to durable `category_id`
3. merge into canonical parquet without rewriting historical `category_id`
4. recompute reporting fields across the full merged canonical corpus

That recomputation uses:
- taxonomy for durable category labels and default `economic_role`
- account boundary for transfer detection
- sign for non-transfer, non-excluded `cashflow_type`

This preserves trust:

- current labels stay consistent
- deprecated IDs can map to current reporting IDs
- historical meaning does not silently change when rules evolve

For the human decision process when choosing buckets, see
`docs/taxonomy_guide.md`. For the higher-level taxonomy philosophy and known
target-vs-current divergences, see `docs/taxonomy_spec.md`.

## Current Note On Refunds

The durable-ID architecture supports taxonomy evolution, including cases where
the current executable taxonomy is not yet the preferred target philosophy.

At the moment:

- the executable taxonomy still includes `refunds.*`
- the target philosophy documented in `docs/taxonomy_spec.md` is to keep
  refunds in the original purpose bucket whenever that purpose is known

That disagreement is a taxonomy-policy issue, not a flaw in the category-ID
model itself. It can be resolved later through deprecation plus an explicit
migration.

## Review Workflow

`review-export` remains label-based for humans:

- editable: `category`, `subcategory`
- read-only context: `original_category_id`, `original_reporting_category_id`

`review-import` behavior:

- unchanged labels preserve the original durable `category_id`
- edited labels resolve to the current active taxonomy ID
- imported overrides write durable category state; reporting labels are derived
  on the next `transform`

## Lifecycle

### 1. Soft label change

Example:

- `Dining / Restaurants` becomes `Leisure / Dining out`

Process:

- keep the same `category_id`
- update taxonomy labels only
- no canonical rewrite

### 2. Category ID continuity break

Example:

- old ID: `dining.restaurants`
- new ID: `leisure.dining_out`

Process:

- add the new active ID
- mark the old ID with `deprecated_to`
- stop rules and new review imports from emitting the old ID
- keep historical canonical rows untouched
- reporting resolves old rows through `reporting_category_id`

### 3. Full history rewrite

Use only when you intentionally want to rewrite historical semantic meaning.

Process:

- generate a migration plan
- back up canonical parquet and overrides
- rewrite historical `category_id`
- rewrite overrides still pointing at the old ID

This must stay an explicit migration step, not part of default `transform`.

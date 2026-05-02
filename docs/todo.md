# TODO

Repository-level backlog items that are useful to preserve but not yet scoped
as an active work package.

## Categorization and Taxonomy

- Bugfix: enforce taxonomy-declared `cashflow_type` during transform so
  transfer taxonomy rows do not silently fall back to `in` or `out` unless an
  explicit override or stronger account-boundary rule says otherwise.
- Migrate overly specific category patterns to more generic reusable rules.
- Implement a transaction categorization diff review workflow for comparing
  transform runs, surfacing row-level category changes, and tracing lost or
  gained categorization back to the triggering rules.
- Migrate transactions to also include the account owner where current account
  labeling does not distinguish ownership clearly enough.
- Add a taxonomy/reporting surface for fixed expenses, variable expenses, and
  savings so reports can quickly distinguish those item types.

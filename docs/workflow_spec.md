# Workflow Specification

## Purpose

This document defines the intended end-to-end workflow for the finance tooling
pipeline. It covers the three main operational stages:

1. `ingest` - read raw statement files and normalize them into staged data.
2. `transform` - produce canonical transactions and reporting semantics.
3. `planning` - derive decision-facing KPIs such as budget actuals and monthly
   planning summaries.

The pipeline is designed so that each stage has a single responsibility and a
clear output contract. Downstream reporting and dashboards should consume the
canonical outputs, not re-derive their own semantics.

## Terminology

- `ingest`: raw-file parsing, normalization, staging, and source inventory
  tracking.
- `transform`: canonical transaction build step that applies categorization,
  overrides, account inference, FX normalization, and semantic derivation.
- `planning`: decision-informing evaluation layer that turns canonical
  transactions into budget-vs-actual and monthly KPI outputs.
- `reporting`: presentation surfaces such as dashboards and summaries that
  visualize the canonical and planning outputs.

`planning` is the preferred name for the last decision-informing stage because
it is broader than budgeting alone. Budget actuals are one of its primary
outputs, but the same layer also supports monthly planning ledgers and other
decision KPIs.

## Workflow Overview

### 1. Ingest

The ingest stage reads statement files from the raw input tree and produces a
staged transaction artifact.

Primary responsibilities:

- discover source files and statement inventory
- parse bank-specific statements into normalized transaction rows
- capture reconciliation and completeness diagnostics
- write staged transaction state and ingest manifests

Primary outputs:

- `processed/ingest/ingest_staged_transactions.parquet`
- `processed/ingest/ingest_staged_batch_manifest.json`
- `processed/ingest/ingest_summary.json` when requested
- `processed/ingest/workflow_source_inventory.json`

Ingest should not assign durable categorization outcomes. It prepares normalized
rows for the transform stage.

### 2. Transform

The transform stage reads staged transactions and produces the canonical corpus.
It is the semantic center of the pipeline.

Primary responsibilities:

- apply `category_id` assignment and review overrides
- resolve `reporting_category_id`, `category`, and `subcategory`
- infer account boundaries
- compute `cashflow_type`, `economic_role`, and `decision_role`
- persist canonical transaction exports and transform summaries
- keep the no-op cache available for unchanged staged/config/review inputs

`decision_role` is part of the canonical transform output, but
`not_applicable` is the display bucket for income, transfer, and excluded rows.

Recommended evaluation order for the transform stage:

1. `cashflow_type` identifies transfers and excluded rows first, so they can be
   removed from income/expense pattern analysis.
2. `economic_role` then identifies non-personal or otherwise out-of-scope rows
   such as associations, work expenses, and similar exclusions.
3. `decision_role` finally classifies the remaining spend-side rows into
   planning buckets.

That order keeps the transform output layered and avoids making
`decision_role` responsible for detecting out-of-scope flows that were already
resolved by cashflow or economic-role semantics.

Primary outputs:

- `processed/transform/transform_transactions.parquet`
- `processed/transform/transform_transactions.csv`
- `processed/transform/transform_run_summary.json`
- `processed/transform/transform_dashboard.html`
- `processed/state/workflow_review_state.parquet`
- `processed/state/transform_source_registry.json`
- `processed/state/workflow_pipeline_state.json`

Transform is intentionally transform-only. It does not re-run ingest or
planning.

### 3. Planning

The planning stage turns canonical transactions into decision-facing
evaluation views.

Primary responsibilities:

- build a row-level monthly planning ledger traceable back to source
  transactions
- compute budget-vs-actual status using stable IDs and semantic filters
- group flows into planning buckets such as expense, transfer, savings,
  investment, debt service, tax, and excluded
  - transfer subtypes are derived from semantic fields, not from the
    `decision_role` display bucket
- support KPI evaluation that is stable across dashboards and future planning
  surfaces

Primary outputs:

- monthly planning ledger data structures
- budget status comparisons
- planning summaries for downstream reporting or dashboarding

The planning layer should consume canonical fields rather than display labels or
sign-only heuristics. It should prefer:

- `transaction_id`
- `category_id`
- `cashflow_type`
- `economic_role`
- `decision_role`

## Semantic Contract

The canonical transaction row is the source of truth for downstream work.

Durable facts:

- booking and source metadata
- amounts and currencies
- parser identity
- source document lineage

Durable assignment:

- `category_id`
- transaction overrides
- review state
- project tags where applicable

Derived reporting semantics:

- `reporting_category_id`
- `category`
- `subcategory`
- `cashflow_type`
- `economic_role`
- `decision_role`
- account-boundary fields

The pipeline should keep these concerns separate:

- purpose/category assignment says what the transaction is about
- cashflow semantics say how money moved
- economic role says how the row should be interpreted economically
- decision role says how the row should be treated for planning and KPI
  evaluation

## Stage Boundaries

### Ingest to Transform

Transform consumes only staged transaction artifacts and the relevant state
files. It should not depend on raw parsing logic beyond the staged outputs.

### Transform to Planning

Planning consumes the canonical transaction corpus. It should not re-run
categorization or account inference.

### Planning to Reporting

Reporting should render the outputs of planning and transform. It may format or
slice the data, but it should not own core semantic rules.

## Operational Rules

- Re-running `ingest` should only be necessary when raw source files or parser
  behavior changes.
- Re-running `transform` should be necessary when staged data, review state,
  taxonomy/configuration, or transform logic changes.
- `transform --force` may be used to bypass the no-op cache and recompute the
  canonical corpus without re-running ingest.
- `update` should run `planning` by default after `transform`; use
  `--skip-planning` to stop at the transform stage.
- Planning outputs should be reproducible from the canonical corpus and stable
  semantic rules.
- Budgeting logic should rely on semantic fields and stable identifiers, not on
  display labels or raw sign checks.

## Recommended CLI Sequence

The common operator flow is:

```text
ingest -> transform -> planning / reporting
```

For review-driven categorization work:

```text
review-export -> manual edit -> review-import -> transform
```

For decision-analysis work:

```text
transform -> planning
```

## Relationship To Other Docs

- `docs/transaction_model_improvement_plan.md` captures the longer-term target
  semantic model and the implementation path.
- `docs/taxonomy_spec.md` defines the categorization and semantic taxonomy
  rules.
- `docs/categorization_review_workflow.md` and
  `docs/category_rules_review_workflow.md` cover review and rule maintenance.

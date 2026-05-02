# Roadmap

This roadmap aggregates the repository's current direction, near-term focus,
and preserved backlog. It is intentionally practical: items here should guide
the next useful work without turning every idea into an active commitment.

## Current Direction

Build reliable Python tooling for personal finance monitoring. The immediate
focus is accurate bank statement ingestion, normalization, categorization, and
review. The longer-term direction is a maintainable pipeline for analysis,
categorization, reconciliation, planning, and reporting.

## Current Public Workflow Surface

Keep the operator-facing workflow centered on the existing CLI commands:

- `ingest`
- `transform`
- `update`
- `review-export`
- `review-import`
- `workflow-status`

Canonical transform outputs live under `processed/outputs/`:

- `transform_transactions.csv`
- `transform_transactions.parquet`
- `transform_run_summary.json`
- `transform_dashboard.html`

Staged ingest state lives under `processed/state/`, especially:

- `ingest_staged_transactions.parquet`
- `ingest_staged_batch_manifest.json`

## Near-Term Priorities

1. Validate the 2026 categorization workflow end to end.

Run monthly or quarterly review cycles for January through December 2026 using:

```text
review-export -> manual review -> review-import -> transform
```

Track before/after month-scoped `uncategorized_count` and
`uncategorized_ratio` from `outputs/transform_transactions.csv` and
`outputs/transform_run_summary.json`.

Keep reusable categorization logic centralized in `config/category_rules.yaml`
and use `transaction_overrides.yaml` only for true transaction-level manual
corrections.

Capture high-frequency residual fingerprints discovered during 2026 review and
feed them back into reusable rule updates.

Add scoped `review-export` filters for taxonomy/category buckets so an operator
can export review rows by `category`, `subcategory`, `category_id`, or
`reporting_category_id` without exporting all categorized transactions first.

2. Improve transform iteration speed for targeted review/config changes.

True no-op fast paths already exist for unchanged runs. The remaining gap is
that small review-state or config edits still require a full transform when
any transform work is needed.

Prefer targeted transform scopes or similarly minimal recomputation before
adding more workflow surface area.

3. Expand planning and reporting only when it serves the core pipeline.

The repo includes planning, budgeting, and reporting modules plus the
`planning/household_finance_360/` workspace. Keep additions to that surface
intentional and secondary to the ingestion and categorization workflow unless
the task explicitly targets planning features.

The next planning-step implementation target is a first-class decision/KPI
stage API that consumes the canonical transform output and exposes budget
actuals, monthly planning ledgers, and other decision-facing summaries as a
named workflow surface rather than only as library helpers.

4. Keep quality gates mandatory.

Continue enforcing:

- `uv run ruff check .`
- `uv run ruff format .`
- `uv run ty check src/finance_tooling tests`
- `uv run pytest`

## Backlog

Preserved repo-level follow-up ideas that are not yet scoped as active work:

- Clean up granular config rules, especially overly specific category patterns,
  by migrating repeated transaction-level fingerprints into generic reusable
  rules.
- Add a canonical statement account identifier on transactions using the
  snake_case format `<bank>_<account_holder>_<last_4_digits_of_account>`, while
  keeping parser-provided `bank` and `account_label` fields as source context.
- Add a taxonomy/reporting surface for fixed expenses, variable expenses, and
  savings so reports can quickly distinguish those item types.
- Split finance presentation into two clear HTML layers:
  `finance_overview.html` for high-level KPIs and financial structure, and
  `transaction_explorer.html` for dense transaction/account/category/
  economic-role exploration. Keep legacy dashboard paths temporarily for
  compatibility.
- Add a first-class `planning` or `budget-status` workflow command that reads
  canonical transform outputs and emits budget-vs-actual and monthly planning
  KPI artifacts without re-running ingest or transform.
- Add `review-export` filters for taxonomy/category buckets, such as
  `--category`, `--subcategory`, `--category-id`, and
  `--reporting-category-id`.

## Success Target

Process all 2026 months through the review workflow at least once and reduce
month-scoped uncategorized ratios without worsening reconciliation metrics.

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

Canonical ingest, transform, and planning outputs live under
`processed/ingest/`, `processed/transform/`, and `processed/planning/`:

- `transform_transactions.csv`
- `transform_transactions.parquet`
- `transform_run_summary.json`
- `transform_dashboard.html`

Shared workflow state lives under `processed/state/`, especially:

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

2. Implement the first-class planning stage as the next major workflow item.

The repo already has reusable planning helpers, but the missing piece is a
dedicated `planning` stage that consumes canonical transform outputs and emits
traceable KPIs, budget-vs-actual views, and a separate planning dashboard.

Keep this on the roadmap as the next big feature after the current ingestion
and categorization work.

The stage should:

- read canonical transaction outputs
- build a row-level monthly planning ledger
- compute decision-facing KPIs
- compute budget-vs-actual status when targets are configured
- write planning artifacts for reporting and review
- render a dedicated `planning_dashboard.html`

`update` should run `planning` by default after `transform`; `transform`
remains transform-only and `--skip-planning` preserves the old stop point.

3. Improve transform iteration speed for targeted review/config changes.

True no-op fast paths already exist for unchanged runs. The remaining gap is
that small review-state or config edits still require a full transform when
any transform work is needed.

Prefer targeted transform scopes or similarly minimal recomputation before
adding more workflow surface area.

4. Add pipeline observability and corpus diff reporting.

Make it easy to understand how each run changes the corpus and the
categorization state.

Track corpus-level diffs on every run, including transaction count deltas and
EUR amount deltas.

For full-refresh ingest, report how many new transactions were added and how
many existing logical rows were rekeyed because parser output changed. Keep a
reviewable export of those changed rows for HIL inspection.

For full-refresh transform, report category-change deltas in count and EUR
amount, surface stale transaction overrides, and export all rows whose
category changed for HIL review.

5. Expand planning and reporting only when it serves the core pipeline.

The repo includes planning, budgeting, and reporting modules plus the
`planning/household_finance_360/` workspace. Keep additions to that surface
intentional and secondary to the ingestion and categorization workflow unless
the task explicitly targets planning features.

The next planning-step implementation target is a first-class decision/KPI
stage API that consumes the canonical transform output and exposes budget
actuals, monthly planning ledgers, and other decision-facing summaries as a
named workflow surface rather than only as library helpers.

6. Keep quality gates mandatory.

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

## Success Target

Process all 2026 months through the review workflow at least once and reduce
month-scoped uncategorized ratios without worsening reconciliation metrics.

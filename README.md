# Finance Tooling

Python tooling for monitoring personal finances, starting with import pipelines for
bank statements and expanding toward categorization, reconciliation, and reporting.

For higher-level household planning alongside the transaction pipeline, see the
starter workspace in `planning/household_finance_360/`.

## Quick Start

```bash
uv sync --all-groups
uv run update
```

`update` and `ingest` are incremental by default. They scan the full raw corpus
but only parse source documents that have not yet been committed into the
canonical dataset.

## Public API

This tool's primary public API is its workflow CLI plus a small set of stable
files under `processed/ingest/`, `processed/transform/`, and
`processed/planning/`.

Normal workflow commands print concise summaries by default and avoid emitting
artifact paths. Use `--verbose` when you want fuller metric breakdowns for
troubleshooting.

Recommended day-to-day commands:

- `uv run update`
- `uv run review-export`
- `uv run review-import`
- `uv run workflow-status`

Advanced/recovery commands:

- `uv run ingest`
- `uv run transform`

Canonical operator-facing outputs under `${FINANCE_PROCESSED_PATH}/transform/`:

- `household_healthcheck.html` (secondary compatibility dashboard)
- `transform_transactions.parquet`
- `transform_transactions.csv`
- `transform_run_summary.json` (finance/reporting summary)
- `transform_dashboard.html` (primary finance dashboard)

Canonical ingest state under `${FINANCE_PROCESSED_PATH}/ingest/`:

- `ingest_staged_transactions.parquet`
- `ingest_staged_batch_manifest.json`
- `ingest_summary.json` when requested

Canonical shared state and diagnostics under `${FINANCE_PROCESSED_PATH}/state/`:

- `workflow_pipeline_state.json`
- `workflow_review_state.parquet`
- `transform_source_registry.json`
- `workflow_fx_rates_history.parquet`
- `transform_completeness_report.json` when diagnostics are enabled

Canonical planning outputs under `${FINANCE_PROCESSED_PATH}/planning/`:

- `planning_ledger.parquet`
- `planning_ledger.csv`
- `planning_kpi_summary.json`
- `planning_budget_status.csv`
- `planning_dashboard.html`

Compatibility-only optional export:

- `transform_transactions.json` when JSON export is explicitly enabled

Deprecated / compatibility-only surface:

- `household_healthcheck.html` is retained as a secondary compatibility dashboard.
- legacy `processed/state/` and `processed/outputs/` read fallbacks are still
  supported temporarily, but the code now warns when those fallback paths are
  used so they can be migrated to `processed/ingest/`, `processed/transform/`,
  and `processed/planning/`.
- `finance_tooling.healthcheck()` is deprecated and should not be used for new integrations.

## Workflow Overview (Newcomer)

Use this sequence when processing new statements and optionally refining
categorization.

### 1) Update (recommended end-to-end refresh)

If you do not need a manual review stop, use:

```bash
uv run update
```

This runs `ingest`, `transform`, and `planning` end-to-end and refreshes the
canonical outputs in `${FINANCE_PROCESSED_PATH}/ingest/`,
`${FINANCE_PROCESSED_PATH}/transform/`, and
`${FINANCE_PROCESSED_PATH}/planning/`.

### 2) Optional review (human-in-the-loop categorization)

- Export review rows:

```bash
uv run review-export
```

- Edit `${FINANCE_PROCESSED_PATH}/transactions_review.xlsx`.
- The review workbook includes:
  - `reviewed`: persistent review-progress marker
  - `review_comment`: freeform review note
  - `normalized_description`: normalized description helper for search/filtering
- Dry-run import:

```bash
uv run review-import --dry-run
```

- Apply reviewed changes:

```bash
uv run review-import
```

- Apply reviewed changes without rebuilding outputs:

```bash
uv run review-import --no-run-transform
```

Detailed guides:

- Transaction review import/export workflow: `docs/categorization_review_workflow.md`
- Category rule create/amend/delete workflow: `docs/category_rules_review_workflow.md`

### 3) What the workflow writes

`update` and `transform`:
- Reads staged data.
- Requires the staged batch manifest created by `ingest`.
- Applies category rules, project rules, and transaction overrides.
- Carries forward prior manual category/subcategory (`transaction_override`)
  when parser cleanup changes transaction descriptions but the same transaction can be
  matched deterministically.
- Creates one pre-run snapshot under `${FINANCE_STATEMENTS_PATH}/../backup/<snapshot_id>/`
  containing the current `processed/` tree plus active config files. Retention keeps
  the latest `3` snapshots for each retained run day and the latest `7` run days that
  actually had pipeline activity.
- For local disaster recovery beyond these workflow snapshots, use the decrypted-vault
  restic backup helper described in `docs/decrypted_vault_backup.md`.
- Writes canonical outputs under `${FINANCE_PROCESSED_PATH}/outputs/`:
  `household_healthcheck.html`, `transform_transactions.parquet`,
  `transform_transactions.csv`, `transform_run_summary.json`, and
  `transform_dashboard.html`.
- Writes operational diagnostics under `${FINANCE_PROCESSED_PATH}/state/`,
  including `workflow_pipeline_state.json`,
  `transform_completeness_report.json`, and, when explicitly enabled for
  compatibility, `transform_transactions.json`.
- In incremental mode, upserts only the staged source documents into the master
  parquet, then rebuilds summary/dashboard/export artifacts from the full merged
  canonical dataset.
- Projects persisted `reviewed` state into canonical outputs so review progress
  survives across sessions and appears in `transform_transactions.csv`.

`transform_run_summary.json` is the machine-discoverable finance summary. It
includes finance KPIs such as categorization coverage, carry-forward
diagnostics, and the year-over-year cashflow block used by the primary finance
dashboard.

Canonical transaction outputs now include `cashflow_type`, derived during
`transform` from household-account boundary, exclusion policy, transaction sign,
and optional transaction-level overrides.
Canonical outputs also now include inferred account-boundary fields:
`from_account_ref`, `to_account_ref`, `from_account_type`,
`to_account_type`, and `account_inference_source`.
Canonical categorization is now durable-ID based:

- `category_id`: stored semantic category assignment
- `reporting_category_id`: active taxonomy target after deprecation mapping
- `category` / `subcategory`: current display labels derived from taxonomy

Rules and transaction overrides should now prefer `category_id`. Display labels
remain a derived reporting layer and review-workflow UX layer. See:

- `docs/category_id_model.md` for the technical durable-ID model
- `docs/taxonomy_guide.md` for the quick bucket-picking guide
- `docs/taxonomy_spec.md` for evolving taxonomy philosophy, edge cases, and
  change-review criteria

Cashflow definitions used by the finance dashboard and `cashflow_yoy` summary:
- `cashflow_type = in`: contributes to income
- `cashflow_type = out`: contributes to expense
- `cashflow_type = transfer`: excluded from income/expense/net
- `cashflow_type = exclude`: ignored for personal cashflow reporting
- `Net cashflow = Income - Expense`

Practical policy:
- household-owned counterparty movements become `cashflow_type = transfer`
- excluded categories become `cashflow_type = exclude`
- otherwise positive rows are `cashflow_type = in` and negative rows are
  `cashflow_type = out`
- positive expense-side inflows such as refunds are not income; they stay in an
  expense-like `economic_role`
- if a transaction-level exception is needed, set `cashflow_type` directly in
  `transaction_overrides.yaml`

Canonical outputs also include `economic_role`, which the primary dashboard now
uses for displayed income/expenses balance metrics:
- `economic_role = income`: true income categories such as salary, interest,
  benefits, or business income
- `economic_role = fixed_expense`: recurring structural commitments such as
  rent, utilities, telecom, insurance, recurring taxes, and subscription-style
  bills
- `economic_role = variable_expense`: ordinary discretionary or usage-based
  spend such as groceries, dining, shopping, transport usage, leisure, travel,
  healthcare purchases, cash withdrawals, and ambiguous outgoing rows
- `economic_role = expense`: legacy-compatible expense-side rows, including
  unresolved positive refunds/reimbursements where no fixed/variable category
  applies
- `economic_role = transfer`: excluded from the income/expenses balance
- `economic_role = exclude`: ignored in the income/expenses balance

Dashboard expense totals treat `fixed_expense`, `variable_expense`, and legacy
`expense` as expense-like. Category taxonomy should prefer the fixed/variable
split for new outgoing classifications; rule-level `economic_role` overrides
can mark recurring subscriptions as fixed without changing their purpose bucket.

Account-boundary inference is configured separately in `account_rules.yaml`:
- `internal_accounts` defines personal/internal statement accounts
- `counterparty_rules` infers the emitting or receiving counterparty side
- transaction-level account exceptions can be set in `transaction_overrides.yaml`

Carry-forward diagnostics include:
- `manual_category_carry_forward_applied_count`
- `manual_category_carry_forward_ambiguous_skipped_count`
- `manual_category_carry_forward_unmatched_count`

### 4) Dashboard

Dashboard output:
- Primary: `${FINANCE_PROCESSED_PATH}/transform/transform_dashboard.html`
- Secondary compatibility view: `${FINANCE_PROCESSED_PATH}/transform/household_healthcheck.html`
- Open the primary dashboard after `transform` or `update`.

### Advanced and recovery commands

Use these when you intentionally need stage-level control rather than the
normal `update` flow.

#### `uv run ingest`

- Scans statements under `FINANCE_STATEMENTS_PATH`.
- Builds a content-based source inventory so raw-file renames do not change
  document identity.
- Ignores duplicate raw files with identical content and records them in
  `${FINANCE_PROCESSED_PATH}/state/workflow_source_inventory.json`.
- Loads `${FINANCE_PROCESSED_PATH}/state/transform_source_registry.json` to decide which
  representative source documents are already committed.
- In the default incremental path, parses only never-committed representative
  source documents. Modified or missing previously committed files are reported
  as stale conditions and require a guarded full refresh to re-sync history.
- Parses and normalizes raw transaction records.
- Reuses the same unified pre-run snapshot model under
  `${FINANCE_STATEMENTS_PATH}/../backup/<snapshot_id>/`.
- Writes staged data to `${FINANCE_PROCESSED_PATH}/state/ingest_staged_transactions.parquet`.
- Writes a self-describing staged batch manifest to
  `${FINANCE_PROCESSED_PATH}/state/ingest_staged_batch_manifest.json`.
- Optionally writes ingest diagnostics to
  `${FINANCE_PROCESSED_PATH}/state/ingest_summary.json` with
  `--emit-ingest-summary`.

#### `uv run transform`

- Rebuilds canonical outputs from staged transactions without re-running ingest.
- Add `--force` to bypass the no-op cache and recompute transform outputs even
  when staged data, review state, and config are unchanged.
- Useful after explicit staged-state changes or when `review-import`
  should not be the trigger for a rebuild.

`transform` remains transform-only. It does not run `ingest` or `planning`.

`update` runs `planning` by default after `transform`. Use `--skip-planning`
to stop at the transform stage.

### Guarded full refresh

Use a full refresh only when you intentionally want to reparse and rebuild the
entire representative raw corpus under current raw/config state.

Preview the impact first:

```bash
uv run update --full-refresh --dry-run
```

The real run is intentionally two-step. Plain `--full-refresh` prints a warning,
impact summary, and a confirmation token, then exits without mutating state.
Only a matching token allows execution:

```bash
uv run update --full-refresh --confirm-full-refresh <token>
```

The same guardrail applies to `uv run ingest --full-refresh`.

Why it is guarded:
- it can prune canonical rows for committed source documents that are no longer
  present in raw inputs
- it can reclassify historical transactions under current category/project
  config
- it is the explicit way to resolve stale state caused by modified raw files,
  missing raw files, or config drift

### Status snapshot

To inspect the current raw/staged/transformed pipeline state:

```bash
uv run workflow-status
```

This writes `${FINANCE_PROCESSED_PATH}/state/workflow_pipeline_state.json` and prints a compact
health summary, including duplicate raw-source detection, staged-vs-transform
timestamp drift, committed source-registry state, stale reasons, full-refresh
risk, parser diagnostics, and reconciliation/data-quality diagnostics.

### Review command examples

```bash
uv run review-export \
  --include-categorized \
  --start-date "2026-01-01" \
  --end-date "2026-03-31"

# explicit paths
uv run review-export \
  --normalized-path "$FINANCE_PROCESSED_PATH/transform/transform_transactions.csv" \
  --output-path "$FINANCE_PROCESSED_PATH/transactions_review.xlsx"

# edit transactions_review.xlsx (set category/subcategory, reviewed, notes)

# defaults (review file from processed path, overrides from env or data-adjacent config,
# then rebuild canonical outputs)
uv run review-import

# safe preview before writing
uv run review-import --dry-run

# apply import without rebuilding outputs
uv run review-import --no-run-transform

# explicit paths
uv run review-import \
  --review-path "$FINANCE_PROCESSED_PATH/transactions_review.xlsx" \
  --transaction-overrides-path "$FINANCE_STATEMENTS_PATH/../config/transaction_overrides.yaml"
```

By default, `review-import` aborts when existing override-load warnings are present.
When backups are enabled, `review-import` writes into the same unified
`${FINANCE_STATEMENTS_PATH}/../backup/` snapshot root used by `ingest`,
`transform`, and `update`; it no longer creates per-file `.bak` copies beside
live config files.
Use `--allow-load-warnings` only for deliberate recovery flows.
For `review-export`, output is uncategorized-only by default; use
`--include-categorized` to include already-categorized rows. Optional
`--start-date` and `--end-date` apply inclusive `booking_date` filters.
Additional review filters:
- `--min-amount`
- `--max-amount`
- `--contains`
- `--bank`
- `--account-label`
- `--only-unreviewed`
- `--dark-safe` / `--no-dark-safe`

Use `--min-amount` / `--max-amount` for inclusive signed `amount_native`
bounds. Existing `--min-abs-amount` / `--max-abs-amount` remain available for
absolute-value filtering, but signed and absolute amount filters cannot be
combined in the same invocation.

For `.xlsx` review exports, dark-safe rendering is enabled by default. It
writes explicit light text on dark fills so the workbook stays readable in dark
LibreOffice/Excel setups without manual theme tweaks. Override via
`--no-dark-safe` or `FINANCE_REVIEW_EXPORT_DARK_SAFE=false`.

Review progress is stored separately in
`${FINANCE_PROCESSED_PATH}/state/workflow_review_state.parquet` by default and projected into
`transform_transactions.csv` as the `reviewed` column after `transform`.

Transaction identity now includes a parser-assigned `source_record_index` so
repeated same-day same-amount statement rows do not collapse into a single
canonical transaction during `transform`. This field is persisted in staged and
canonical outputs for auditability, but it is not shown in the human review
workbook.
Transaction identity also now uses a content-based `source_document_id`, so
renaming or moving an unchanged raw statement file does not produce a different
canonical transaction ID. The original `source_file` path is still retained for
audit/debugging, but it is no longer treated as stable identity.

Transaction-level corrections and project tags are configured in:

- `${FINANCE_STATEMENTS_PATH}/../config/transaction_overrides.yaml`
- `${FINANCE_STATEMENTS_PATH}/../config/project_overrides.yaml`

If you are upgrading from an older processed corpus that used path-based
transaction IDs, do a fresh rebuild from raw statements first. Any recovery of
old ID-keyed manual state should be handled as a one-off migration exercise,
not as part of the normal public CLI workflow.

Related docs and diagrams:

- `docs/category_rules_review_workflow.md`
- `docs/categorization_review_workflow.md`
- `docs/diagrams/categorization_review_hitl_flow.puml`
- `docs/diagrams/categorization_review_import_guardrails.puml`

## Statement Workflow and Configuration

The workflow reads environment variables from `.env` in the repository root (if present),
and falls back to process environment variables.

Minimum required variables:

```bash
export FINANCE_STATEMENTS_PATH="/path/to/statements"
export FINANCE_PROCESSED_PATH="/path/to/processed"
```

Supported advanced overrides:

```bash
export FINANCE_DASHBOARD_PATH="/path/to/output/dashboard.html"
export FINANCE_MASTER_PARQUET_PATH="/path/to/output/transform/transform_transactions.parquet"
export FINANCE_EXPORT_CSV_PATH="/path/to/output/transform/transform_transactions.csv"
export FINANCE_EXPORT_JSON_PATH="/path/to/output/transform/transform_transactions.json"
export FINANCE_STAGED_TRANSACTIONS_PATH="/path/to/output/ingest/ingest_staged_transactions.parquet"
export FINANCE_BASE_CURRENCY="EUR"
export FINANCE_INGEST_WORKERS="1"
export FINANCE_CATEGORY_RULES_PATH="/path/to/data/config/category_rules.yaml"
export FINANCE_PROJECT_RULES_PATH="/path/to/data/config/project_rules.yaml"
export FINANCE_TRANSACTION_OVERRIDES_PATH="/path/to/data/config/transaction_overrides.yaml"
export FINANCE_REVIEW_STATE_PATH="/path/to/output/state/workflow_review_state.parquet"
export FINANCE_REVIEW_EXPORT_DARK_SAFE="true"

uv run update
```

Additional compatibility/internal overrides still exist for advanced users,
including per-file artifact paths, JSON export toggles, FX cache settings, and
text-cache settings. Most operators should leave those at their defaults and
rely on the standard `outputs/` and `state/` layout under
`FINANCE_PROCESSED_PATH`.

Categorization is deterministic and rules-first. When no categorization env vars are
set, the workflow expects:

- `<FINANCE_STATEMENTS_PATH>/../config/category_rules.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/project_rules.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/budget_targets.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/project_overrides.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/transaction_overrides.yaml`

The repository includes starter templates and examples:

- `config/category_rules.yaml`
- `config/project_rules.yaml`
- `config/budget_targets.yaml`
- `config/project_overrides.yaml`
- `config/transaction_overrides.yaml`

These repo copies are intentionally generic and should be treated as example
starting points, not as production-ready personal finance configs.

Supported formats for all five config files are YAML (`.yaml`/`.yml`) and JSON (`.json`).
Project assignment rules are loaded from `FINANCE_PROJECT_RULES_PATH` and budgets
from `FINANCE_BUDGET_TARGETS_PATH` (both optional; missing files degrade gracefully
to `Unassigned` projects and no budget targets).
Project assignment precedence is:
`transaction_overrides` > `project_overrides.overrides` > `project_overrides.rules`.

HSBC ingestion is PDF-only. For each HSBC statement month, opening/closing balances
extracted from the PDF are used to validate parsed transaction totals. Balance
mismatches are emitted as warnings and included in transform-summary reconciliation metrics.

## Outputs

- `processed/ingest/`
  - `ingest_staged_transactions.parquet`
  - `ingest_staged_batch_manifest.json`
  - `ingest_summary.json` when `--emit-ingest-summary` is used
  - `workflow_source_inventory.json`
- `processed/transform/`
  - `household_healthcheck.html`
  - `transform_dashboard.html`
  - `transform_transactions.parquet`
  - `transform_transactions.csv`
  - `transform_run_summary.json`
- `processed/state/`
  - `transform_source_registry.json`
  - `workflow_pipeline_state.json`
  - `workflow_review_state.parquet`
  - `workflow_fx_rates_history.parquet`
  - `transform_completeness_report.json` when diagnostics are enabled
- `processed/planning/`
  - `planning_ledger.parquet`
  - `planning_ledger.csv`
  - `planning_kpi_summary.json`
  - `planning_budget_status.csv`
  - `planning_dashboard.html`
- Compatibility-only optional export:
  - `transform_transactions.json` when JSON export is enabled
- Unified snapshot backups under `${FINANCE_STATEMENTS_PATH}/../backup/`

## Developer Notes

### Tech Stack

- `uv` for environment and dependency management
- `ruff` for linting and formatting
- `ty` for static type analysis
- `pre-commit` for local quality gates
- `pytest` for automated tests

### Code Map

Main CLI entrypoints live in modules named after the commands:

- `src/finance_tooling/commands/ingest.py`
- `src/finance_tooling/commands/review_export.py`
- `src/finance_tooling/commands/review_import.py`
- `src/finance_tooling/commands/transform.py`
- `src/finance_tooling/commands/update.py`

Shared stage orchestration lives under:

- `src/finance_tooling/workflow/ingest_stage.py`
- `src/finance_tooling/workflow/transform_stage.py`
- `src/finance_tooling/workflow/update_stage.py`

Implementation modules are being consolidated into focused subpackages:

- `src/finance_tooling/core/` for config, models, storage, extraction, backup, and source scanning
- `src/finance_tooling/categorization/` for classification, overrides, account inference, and project assignment
- `src/finance_tooling/review/` for review export/import/state helpers
- `src/finance_tooling/reporting/` for dashboards, metrics, completeness, and workflow diagnostics
- `src/finance_tooling/planning/` for planning calculations, budgeting, and planning dashboards
- `src/finance_tooling/audits/` for audit-only analysis tools
- `src/finance_tooling/maintenance/` for migrations and maintenance-only utilities

### Development Commands

```bash
uv run ruff check .
uv run ruff format .
uv run ty check src/finance_tooling tests
uv run pytest
uv run pytest --cov=src/finance_tooling --cov-report=term-missing --durations=10
uv run pre-commit run --all-files
```

### Performance Check

The packaged public CLI does not expose `perf-check`, but the internal command
module is still available when you intentionally want an isolated full-corpus
performance run.

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"
PERF_PROCESSED_PATH="/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed_perf/${STAMP}"

FINANCE_PROCESSED_PATH="${PERF_PROCESSED_PATH}" \
FINANCE_FX_AUTO_FETCH=false \
FINANCE_INGEST_WORKERS=4 \
FINANCE_INGEST_TEXT_CACHE_ENABLED=true \
uv run python -m finance_tooling.maintenance.perf_check
```

The run writes standard artifacts plus `performance_summary.json` under the
isolated `FINANCE_PROCESSED_PATH`, including total runtime and per-stage timings
(`ingest`, `hsbc_merge`, `enrichment`, `reporting`).
Set `FINANCE_INGEST_WORKERS` to override the ingestion worker count. The default
is adaptive and uses up to `4` workers. Set `FINANCE_INGEST_WORKERS=1` to force
serial ingestion.
Set `FINANCE_INGEST_TEXT_CACHE_ENABLED=true` to persist extracted PDF text in
`<FINANCE_STATEMENTS_PATH>/../cache/ingest_text_cache.parquet` (or override path via
`FINANCE_INGEST_TEXT_CACHE_PATH`) and speed up repeated runs.

### Repository Layout

```text
src/
  finance_tooling/      # package entrypoints; implementation now lives in subpackages
    core/              # config, models, storage, extraction, backups, fx
    categorization/    # classification, overrides, account/project inference
    review/            # review export/import/state
    reporting/         # dashboards, metrics, completeness, diagnostics
    planning/          # planning calculations and planning dashboards
    audits/            # audit-only analysis tools
    maintenance/       # migrations and maintenance-only tools
    workflow/          # pipeline orchestration
    commands/          # CLI entrypoints
    parsers/           # bank parser plugins
tests/
```

### Parser Conformance Fixtures

Parser conformance samples live under:

`tests/fixtures/parser_samples/synthetic_cases.json`

The conformance harness (`tests/test_parser_conformance.py`) validates parser-level
transaction count, sign distribution, and reconciliation status from fixture cases.
Add new entries as parser behavior is expanded or when snapshot text extracted from
real PDFs is available.

Parser routing uses score-based selection (`match_score`) with diagnostics
captured in `${FINANCE_PROCESSED_PATH}/state/workflow_pipeline_state.json`.

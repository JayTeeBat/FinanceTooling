# Finance Tooling

Python tooling for monitoring personal finances, starting with import pipelines for
bank statements and expanding toward categorization, reconciliation, and reporting.

For higher-level household planning alongside the transaction pipeline, see the
starter workspace in `planning/household_finance_360/`.

## Tech Stack

- `uv` for environment and dependency management
- `ruff` for linting and formatting
- `ty` for static type analysis
- `pre-commit` for local quality gates
- `pytest` for automated tests

## Quick Start

```bash
uv sync --all-groups
uv run update
```

## Workflow Overview (Newcomer)

Use this sequence when processing new statements and optionally refining
categorization.

### 1) Ingest (parse and stage)

What it does:
- Scans statements under `FINANCE_STATEMENTS_PATH`.
- Builds a content-based source inventory so raw-file renames do not change
  document identity.
- Ignores duplicate raw files with identical content and records them in
  `${FINANCE_PROCESSED_PATH}/source_inventory.json`.
- Parses and normalizes raw transaction records.
- Creates a pre-run backup snapshot of the current staged parquet under
  `${FINANCE_PROCESSED_PATH}/backup/ingest/<run_id>/` and keeps the latest 10
  ingest runs.
- Writes staged data to `${FINANCE_PROCESSED_PATH}/staged_transactions.parquet`.
- Writes ingest diagnostics to `${FINANCE_PROCESSED_PATH}/ingest_summary.json`.

```bash
uv run ingest
```

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

- Apply and rebuild normalized outputs immediately:

```bash
uv run review-import --run-transform
```

Detailed guides:

- Transaction review import/export workflow: `docs/categorization_review_workflow.md`
- Category rule create/amend/delete workflow: `docs/category_rules_review_workflow.md`

### 3) Transform (apply rules/overrides and build final outputs)

```bash
uv run transform
```

What it does:
- Reads staged data.
- Applies category rules, project rules, and transaction overrides.
- Carries forward prior manual category/subcategory (`transaction_override`)
  when parser cleanup changes transaction descriptions but the same transaction can be
  matched deterministically.
- Creates a pre-run backup snapshot of the current master parquet under
  `${FINANCE_PROCESSED_PATH}/backup/transform/<run_id>/` and the current
  categorization/project configs under `${FINANCE_STATEMENTS_PATH}/../config/backup/transform/<run_id>/`.
  The latest 10 transform runs are retained.
- Writes canonical outputs (`transactions_master.parquet`,
  `transactions_normalized.csv/json`, `run_summary.json`, dashboard).
- Projects persisted `reviewed` state into canonical outputs so review progress
  survives across sessions and appears in `transactions_normalized.csv`.

`run_summary.json` also includes carry-forward diagnostics:
- `manual_category_carry_forward_applied_count`
- `manual_category_carry_forward_ambiguous_skipped_count`
- `manual_category_carry_forward_unmatched_count`

### 4) Dashboard

Dashboard output:
- `${FINANCE_PROCESSED_PATH}/finance_dashboard.html`
- Open it in a browser after `transform` or `update`.

### Single-command path

If you do not need a manual review stop, use:

```bash
uv run update
```

This runs `ingest` then `transform` end-to-end.
It also takes the same stage-scoped backups before each stage, so a full
`update` run creates one ingest backup run and one transform backup run.

### Status snapshot

To inspect the current raw/staged/transformed pipeline state:

```bash
uv run workflow-status
```

This writes `${FINANCE_PROCESSED_PATH}/pipeline_state.json` and prints a compact
health summary, including duplicate raw-source detection, staged-vs-transform
timestamp drift, and whether the current raw corpus still matches the last
ingested source inventory.

## Code Map

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

### Review command examples

```bash
uv run review-export \
  --include-categorized \
  --start-date "2026-01-01" \
  --end-date "2026-03-31"

# explicit paths
uv run review-export \
  --normalized-path "$FINANCE_PROCESSED_PATH/transactions_normalized.csv" \
  --output-path "$FINANCE_PROCESSED_PATH/transactions_review.xlsx"

# edit transactions_review.xlsx (set category/subcategory, reviewed, notes)

# defaults (review file from processed path, overrides from env or data-adjacent config)
uv run review-import

# safe preview before writing
uv run review-import --dry-run

# apply import and rebuild normalized outputs
uv run review-import --run-transform

# explicit paths
uv run review-import \
  --review-path "$FINANCE_PROCESSED_PATH/transactions_review.xlsx" \
  --transaction-overrides-path "$FINANCE_STATEMENTS_PATH/../config/transaction_overrides.yaml"
```

By default, `review-import` aborts when existing override-load warnings are present.
When backups are enabled, it now stores timestamped config backups under the
config `backup/` folder by default instead of cluttering the main config
directory.
`transform` also snapshots `category_rules.yaml` into the same config `backup/`
folder before enrichment, and retention keeps only the latest `10` backups for
both `category_rules.yaml` and `transaction_overrides.yaml` using FIFO
pruning.
Use `--allow-load-warnings` only for deliberate recovery flows.
For `review-export`, output is uncategorized-only by default; use
`--include-categorized` to include already-categorized rows. Optional
`--start-date` and `--end-date` apply inclusive `booking_date` filters.
Additional review filters:
- `--contains`
- `--bank`
- `--account-label`
- `--only-unreviewed`
- `--dark-safe` / `--no-dark-safe`

For `.xlsx` review exports, dark-safe rendering is enabled by default. It
writes explicit light text on dark fills so the workbook stays readable in dark
LibreOffice/Excel setups without manual theme tweaks. Override via
`--no-dark-safe` or `FINANCE_REVIEW_EXPORT_DARK_SAFE=false`.

Review progress is stored separately in
`${FINANCE_PROCESSED_PATH}/review_state.parquet` by default and projected into
`transactions_normalized.csv` as the `reviewed` column after `transform`.

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

Legacy fingerprint-level category overrides can be migrated into exact-match
rules with:

```bash
uv run migrate-category-overrides-to-rules
```

If you are upgrading from an older processed corpus that used path-based
transaction IDs, do a fresh rebuild from raw statements and then migrate
ID-keyed manual state with:

```bash
uv run update
uv run migrate-transaction-ids
```

That command rewrites uniquely mappable `transaction_overrides` and
`review_state` entries to the current transaction IDs, and writes sidecar files
for ambiguous or unmatched rows instead of guessing.

If you are upgrading from a corpus built before `source_record_index` was added
to transaction identity, the same command remains the right follow-up after
rerunning ingest:

```bash
uv run migrate-transaction-ids
```

Related docs and diagrams:

- `docs/category_rules_review_workflow.md`
- `docs/categorization_review_workflow.md`
- `docs/diagrams/categorization_review_hitl_flow.puml`
- `docs/diagrams/categorization_review_import_guardrails.puml`

Commit-to-commit metrics log update:

```bash
uv run metrics-log-update \
  --summary-path "$FINANCE_PROCESSED_PATH/run_summary.json" \
  --log-path "docs/metrics_commit_log.csv" \
  --log-path-by-bank "docs/metrics_commit_log_by_bank.csv"
```

This writes percentage-based parsing/categorization metrics keyed by commit hash
for quick trend checks, plus a per-bank categorization percentage breakdown.

## Development Commands

```bash
uv run ruff check .
uv run ruff format .
uv run ty check src/finance_tooling tests
uv run pytest
uv run pre-commit run --all-files
```

## Performance Check

For a safe full-corpus performance run, use an isolated processed directory so
the standard destination is untouched.

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"
PERF_PROCESSED_PATH="/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed_perf/${STAMP}"

FINANCE_PROCESSED_PATH="${PERF_PROCESSED_PATH}" \
FINANCE_FX_AUTO_FETCH=false \
FINANCE_INGEST_WORKERS=4 \
FINANCE_INGEST_TEXT_CACHE_ENABLED=true \
uv run perf-check
```

The run writes standard artifacts plus `performance_summary.json` under the
isolated `FINANCE_PROCESSED_PATH`, including total runtime and per-stage timings
(`ingest`, `hsbc_merge`, `enrichment`, `reporting`).
Set `FINANCE_INGEST_WORKERS` to `>1` to enable multiprocessing during ingestion
prep; default is `1`.
Set `FINANCE_INGEST_TEXT_CACHE_ENABLED=true` to persist extracted PDF text in
`<FINANCE_STATEMENTS_PATH>/../cache/ingest_text_cache.parquet` (or override path via
`FINANCE_INGEST_TEXT_CACHE_PATH`) and speed up repeated runs.

## Statement Workflow and Configuration

The workflow reads environment variables from `.env` in the repository root (if present),
and falls back to process environment variables.

Minimum required variables:

```bash
export FINANCE_STATEMENTS_PATH="/path/to/statements"
export FINANCE_PROCESSED_PATH="/path/to/processed"
```

Optional overrides:

```bash
export FINANCE_DASHBOARD_PATH="/path/to/output/dashboard.html"
export FINANCE_MASTER_PARQUET_PATH="/path/to/output/transactions_master.parquet"
export FINANCE_EXPORT_CSV_PATH="/path/to/output/transactions_normalized.csv"
export FINANCE_EXPORT_JSON_PATH="/path/to/output/transactions_normalized.json"
export FINANCE_STAGED_TRANSACTIONS_PATH="/path/to/output/staged_transactions.parquet"
export FINANCE_BASE_CURRENCY="EUR"
export FINANCE_FX_CACHE_PATH="/path/to/output/fx_rates_history.parquet"
export FINANCE_FX_AUTO_FETCH="true"
export FINANCE_INGEST_WORKERS="1"
export FINANCE_INGEST_TEXT_CACHE_ENABLED="false"
export FINANCE_INGEST_TEXT_CACHE_PATH="/path/to/output/ingest_text_cache.parquet"
export FINANCE_CATEGORY_RULES_PATH="/path/to/data/config/category_rules.yaml"
export FINANCE_PROJECT_RULES_PATH="/path/to/data/config/project_rules.yaml"
export FINANCE_BUDGET_TARGETS_PATH="/path/to/data/config/budget_targets.yaml"
export FINANCE_PROJECT_OVERRIDES_PATH="/path/to/data/config/project_overrides.yaml"
export FINANCE_TRANSACTION_OVERRIDES_PATH="/path/to/data/config/transaction_overrides.yaml"
export FINANCE_REVIEW_STATE_PATH="/path/to/output/review_state.parquet"
export FINANCE_REVIEW_EXPORT_DARK_SAFE="true"

uv run update
```

`FINANCE_STATEMENTS_PATH` and `FINANCE_PROCESSED_PATH` are required. Per-file
output env vars remain optional; when omitted, artifacts are written under
`FINANCE_PROCESSED_PATH`.

Categorization is deterministic and rules-first. When no categorization env vars are
set, the workflow expects:

- `<FINANCE_STATEMENTS_PATH>/../config/category_rules.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/project_rules.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/budget_targets.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/project_overrides.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/transaction_overrides.yaml`

The repository includes starter templates:

- `config/category_rules.yaml`
- `config/project_rules.yaml`
- `config/budget_targets.yaml`
- `config/project_overrides.yaml`
- `config/transaction_overrides.yaml`

Supported formats for all five config files are YAML (`.yaml`/`.yml`) and JSON (`.json`).
Project assignment rules are loaded from `FINANCE_PROJECT_RULES_PATH` and budgets
from `FINANCE_BUDGET_TARGETS_PATH` (both optional; missing files degrade gracefully
to `Unassigned` projects and no budget targets).
Project assignment precedence is:
`transaction_overrides` > `project_overrides.overrides` > `project_overrides.rules`.

HSBC ingestion is PDF-only. For each HSBC statement month, opening/closing balances
extracted from the PDF are used to validate parsed transaction totals. Balance
mismatches are emitted as warnings and included in run-summary reconciliation metrics.

## Outputs

- Self-contained interactive HTML dashboard (offline, single-file)
- Canonical parquet master store (`transactions_master.parquet`)
- FX history cache (`fx_rates_history.parquet`)
- Normalized CSV + JSON exports
- Run summary JSON
- Source inventory JSON (`source_inventory.json`)
- Pipeline state JSON (`pipeline_state.json`)
- Automatic backup run folders under `processed/backup/ingest`,
  `processed/backup/transform`, and `config/backup/transform`

## Repository Layout

```text
src/
  finance_tooling/      # package modules and parser plugins
tests/
```

## Parser Conformance Fixtures

Parser conformance samples live under:

`tests/fixtures/parser_samples/synthetic_cases.json`

The conformance harness (`tests/test_parser_conformance.py`) validates parser-level
transaction count, sign distribution, and reconciliation status from fixture cases.
Add new entries as parser behavior is expanded or when snapshot text extracted from
real PDFs is available.

Parser routing uses score-based selection (`match_score`) with diagnostics captured
in `run_summary.json` under `parser_selection_diagnostics`.

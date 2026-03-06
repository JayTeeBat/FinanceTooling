# Finance Tooling

Python tooling for monitoring personal finances, starting with import pipelines for
bank statements and expanding toward categorization, reconciliation, and reporting.

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
- Parses and normalizes raw transaction records.
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

- Edit `${FINANCE_PROCESSED_PATH}/fallback_category_review.csv`.
- Dry-run import:

```bash
uv run review-import --dry-run
```

- Apply reviewed changes:

```bash
uv run review-import
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
- Applies category rules, category overrides, project rules, and transaction overrides.
- Carries forward prior manual category/subcategory (`override` or `transaction_override`)
  when parser cleanup changes transaction descriptions but the same transaction can be
  matched deterministically.
- Writes canonical outputs (`transactions_master.parquet`,
  `transactions_normalized.csv/json`, `run_summary.json`, dashboard).

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

### Review command examples

```bash
uv run review-export \
  --include-categorized \
  --start-date "2026-01-01" \
  --end-date "2026-03-31"

# explicit paths
uv run review-export \
  --normalized-path "$FINANCE_PROCESSED_PATH/transactions_normalized.csv" \
  --output-path "$FINANCE_PROCESSED_PATH/fallback_category_review.csv"

# edit fallback_category_review.csv (set category/subcategory)

# defaults (review file from processed path, overrides from env or data-adjacent config)
uv run review-import

# safe preview before writing
uv run review-import --dry-run

# explicit paths
uv run review-import \
  --review-path "$FINANCE_PROCESSED_PATH/fallback_category_review.csv" \
  --overrides-path "$FINANCE_STATEMENTS_PATH/../config/category_overrides.yaml"
```

Default upsert key is normalized `description` fingerprint + `bank`. Add
`--include-account-label-scope` on import to include `account_label` in the key.
By default, `review-import` aborts when existing override-load warnings are present.
Use `--allow-load-warnings` only for deliberate recovery flows.
Rows whose `category_source` is not `fallback` are skipped by default; override with
`--allow-non-fallback-import`.
For `review-export`, output remains fallback-only by default; use
`--include-categorized` to include already-categorized rows. Optional
`--start-date` and `--end-date` apply inclusive `booking_date` filters.

Transaction-level corrections and project tags are configured in:

- `${FINANCE_STATEMENTS_PATH}/../config/transaction_overrides.yaml`
- `${FINANCE_STATEMENTS_PATH}/../config/project_overrides.yaml`

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
export FINANCE_CATEGORY_OVERRIDES_PATH="/path/to/data/config/category_overrides.yaml"
export FINANCE_PROJECT_RULES_PATH="/path/to/data/config/project_rules.yaml"
export FINANCE_BUDGET_TARGETS_PATH="/path/to/data/config/budget_targets.yaml"
export FINANCE_PROJECT_OVERRIDES_PATH="/path/to/data/config/project_overrides.yaml"
export FINANCE_TRANSACTION_OVERRIDES_PATH="/path/to/data/config/transaction_overrides.yaml"

uv run update
```

`FINANCE_STATEMENTS_PATH` and `FINANCE_PROCESSED_PATH` are required. Per-file
output env vars remain optional; when omitted, artifacts are written under
`FINANCE_PROCESSED_PATH`.

Categorization is deterministic and rules-first. When no categorization env vars are
set, the workflow expects:

- `<FINANCE_STATEMENTS_PATH>/../config/category_rules.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/category_overrides.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/project_rules.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/budget_targets.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/project_overrides.yaml`
- `<FINANCE_STATEMENTS_PATH>/../config/transaction_overrides.yaml`

The repository includes starter templates:

- `config/category_rules.yaml`
- `config/category_overrides.yaml`
- `config/project_rules.yaml`
- `config/budget_targets.yaml`
- `config/project_overrides.yaml`
- `config/transaction_overrides.yaml`

Supported formats for all six config files are YAML (`.yaml`/`.yml`) and JSON (`.json`).
Manual correction rules in `FINANCE_CATEGORY_OVERRIDES_PATH` take precedence over
standard categorization rules.
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

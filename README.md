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
uv run python -m finance_tooling
```

Manual categorization review roundtrip:

```bash
uv run python -m finance_tooling review-export \
  --normalized-path "$FINANCE_PROCESSED_PATH/transactions_normalized.csv" \
  --output-path "$FINANCE_PROCESSED_PATH/fallback_category_review.csv"

# edit fallback_category_review.csv (set category/subcategory)

uv run python -m finance_tooling review-import \
  --review-path "$FINANCE_PROCESSED_PATH/fallback_category_review.csv" \
  --overrides-path "config/category_overrides.yaml"
```

Default upsert key is normalized `description` fingerprint + `bank`. Add
`--include-account-label-scope` on import to include `account_label` in the key.

Commit-to-commit metrics log update:

```bash
uv run python -m finance_tooling metrics-log-update \
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
FINANCE_HSBC_CSV_PATH="${FINANCE_STATEMENTS_PATH}" \
uv run python -m finance_tooling.perf_check
```

The run writes standard artifacts plus `performance_summary.json` under the
isolated `FINANCE_PROCESSED_PATH`, including total runtime and per-stage timings
(`ingest`, `hsbc_merge`, `enrichment`, `reporting`).
Set `FINANCE_INGEST_WORKERS` to `>1` to enable multiprocessing during ingestion
prep; default is `1`.
Set `FINANCE_INGEST_TEXT_CACHE_ENABLED=true` to persist extracted PDF text in
`<FINANCE_STATEMENTS_PATH>/../cache/ingest_text_cache.parquet` (or override path via
`FINANCE_INGEST_TEXT_CACHE_PATH`) and speed up repeated runs.

## Workflow Diagrams

PlantUML source diagrams for the workflow live in:

- `docs/workflow_full_corpus.puml`
- `docs/workflow_incremental_ingestion.puml`

They document the full-corpus execution path and the incremental ingestion path
(stateful file classification, closed-period handling, snapshots, and guardrails).

If you have PlantUML available locally, you can render them with:

```bash
plantuml docs/workflow_full_corpus.puml docs/workflow_incremental_ingestion.puml
```

## Statement Workflow

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
export FINANCE_BASE_CURRENCY="EUR"
export FINANCE_FX_CACHE_PATH="/path/to/output/fx_rates_history.parquet"
export FINANCE_FX_AUTO_FETCH="true"
export FINANCE_INGEST_WORKERS="1"
export FINANCE_INGEST_TEXT_CACHE_ENABLED="false"
export FINANCE_INGEST_TEXT_CACHE_PATH="/path/to/output/ingest_text_cache.parquet"
export FINANCE_HSBC_CSV_PATH="/path/to/hsbc.csv_or_folder"
export FINANCE_CATEGORY_RULES_PATH="/path/to/output/category_rules.yaml"
export FINANCE_CATEGORY_OVERRIDES_PATH="/path/to/output/category_overrides.yaml"

uv run python -m finance_tooling
```

`FINANCE_STATEMENTS_PATH` and `FINANCE_PROCESSED_PATH` are required.
Per-file output env vars remain optional; when omitted, artifacts are written under
`FINANCE_PROCESSED_PATH`.

The workflow recursively scans statement PDFs, uses bank-specific parsers
(LaBanquePostale, HSBC, Boursobank, Revolut + generic fallback), classifies
transactions, auto-fetches historical daily ECB FX rates and applies conversion
using transaction booking dates (with previous business-day fallback), upserts into
a canonical parquet store, and generates dashboard + exports.

Categorization is deterministic and rules-first. When no categorization env vars are
set, the workflow expects:

- `<FINANCE_PROCESSED_PATH>/category_rules.yaml`
- `<FINANCE_PROCESSED_PATH>/category_overrides.yaml`

The repository includes starter templates:

- `config/category_rules.yaml`
- `config/category_overrides.yaml`

Supported formats for both files are YAML (`.yaml`/`.yml`) and JSON (`.json`).
Manual correction rules in `FINANCE_CATEGORY_OVERRIDES_PATH` take precedence over
standard categorization rules.

When `FINANCE_HSBC_CSV_PATH` is set, the workflow also imports HSBC CSV files and
merges HSBC sources by statement month (`YYYY-MM-DD` in file names). For months where
both HSBC CSV and PDF transactions exist, source selection is adaptive: the pipeline
compares reconciliation error against PDF opening/closing balances and keeps the source
with lower absolute mismatch. HSBC PDF parsing is used as fallback when no monthly CSV
is available, and a CSV-only month is retained when no matching PDF exists.

Before overlap selection, HSBC CSV transactions are remapped to statement months using
PDF statement periods (booking date in statement `start -> end` window). This prevents
month-boundary spillover from CSV export file boundaries.

For each HSBC month with a matching PDF statement, opening/closing balances extracted
from the PDF are used to validate the selected transaction set (CSV or PDF fallback).
Balance mismatches are emitted as warnings and included in run summary reconciliation
metrics.

## Outputs

- HTML dashboard
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

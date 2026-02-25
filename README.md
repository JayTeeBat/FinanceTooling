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

## Development Commands

```bash
uv run ruff check .
uv run ruff format .
uv run ty check src/finance_tooling tests
uv run pytest
uv run pre-commit run --all-files
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
export FINANCE_HSBC_CSV_PATH="/path/to/hsbc.csv_or_folder"

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

# Pipeline Performance Baseline

## Objective

Capture a reproducible full-corpus runtime baseline with per-stage timings
without mutating the standard processed output path.

## Run Protocol

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"
PERF_PROCESSED_PATH="/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed_perf/${STAMP}"

FINANCE_STATEMENTS_PATH="/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw" \
FINANCE_PROCESSED_PATH="${PERF_PROCESSED_PATH}" \
FINANCE_HSBC_CSV_PATH="/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw" \
FINANCE_FX_AUTO_FETCH=false \
FINANCE_INGEST_WORKERS=4 \
uv run python -m finance_tooling.perf_check
```

Artifacts are written to `PERF_PROCESSED_PATH`, including:

- `run_summary.json`
- `completeness_report.json`
- `performance_summary.json`

## Baseline Snapshot (To Fill After Run)

- Run timestamp: `2026-02-26`
- Processed path: `/tmp/finance_tooling_processed_perf_20260226-222002`
- Total duration (s): `131.241`
- Ingest duration (s): `127.002` (`96.77%`)
- HSBC merge duration (s): `0.080` (`0.06%`)
- Enrichment duration (s): `2.770` (`2.11%`)
- Reporting duration (s): `1.389` (`1.06%`)
- Files scanned: `199`
- Transactions parsed: `12306`
- Throughput:
  - Files/s: `1.516`
  - Transactions/s: `93.766`
- Quality counters:
  - Reconciliation fail count: `22`
  - Parser low-confidence file count: `0`
  - Uncategorized ratio: `0.9059`

## Improvement Backlog Template

Prioritize by largest stage share first.

1. Ingest hot-path reductions
- Candidate work:
  - Cache first-page text + flattened full-text once per file and pass through parser selection/period parsing.
  - Add optional multiprocess PDF extraction worker pool behind an env flag for full-corpus runs.
  - Isolate parser warning construction from hot loops where possible.
- Validation: reduce `ingest` duration from `127.002s` while preserving reconciliation counts.

2. Enrichment optimization
- Candidate work:
  - Memoize `source_file.stat()` by unique file path and reuse across rows.
  - Batch FX cache lookups by `(currency, booking_date)` keys before per-row mapping.
- Validation: reduce `enrichment` duration from `2.770s` with unchanged warning semantics.

3. Reporting/store optimization
- Candidate work:
  - Avoid duplicate serialization passes where possible (CSV/JSON from one canonical frame).
  - Measure parquet write engine options for append/upsert path.
- Validation: reduce `reporting` duration from `1.389s` with identical row counts and summaries.

## Comparison Run (workers=4)

- Run timestamp: `2026-02-26`
- Processed path: `/tmp/finance_tooling_processed_perf_workers4_20260226-223247`
- Total duration (s): `63.051` (`-51.96%` vs baseline)
- Ingest duration (s): `60.032` (`-52.73%` vs baseline)
- Quality counters parity:
  - Reconciliation fail count: `22` (unchanged)
  - Parser low-confidence file count: `0` (unchanged)
  - Uncategorized ratio: `0.9059` (unchanged)

## Comparison Run (workers=4 + text cache enabled)

Two-pass run using the same isolated processed directory:

```bash
FINANCE_INGEST_TEXT_CACHE_ENABLED=true
```

- Run 1 (cache warm-up):
  - Total duration (s): `68.217`
  - Ingest duration (s): `64.716`
- Run 2 (cache hits):
  - Total duration (s): `5.715`
  - Ingest duration (s): `2.709`
  - Cache hits: `199`
  - Cache misses: `0`
  - Cache writes: `0`
- Quality counters (run 2):
  - Reconciliation fail count: `22` (unchanged)
  - Uncategorized ratio: `0.9059` (unchanged)

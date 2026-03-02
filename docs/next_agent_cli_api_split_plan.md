# CLI API Split Plan: ingest / transform / update

## Objective

Restructure the CLI into a clean, stage-oriented API:

- `ingest`: strictly scan/parse statement sources into a staged normalized artifact.
- `transform`: strictly apply categorization + FX enrichment from staged input.
- `update`: run `ingest` then `transform` (with optional stage skips).

## Scope

### In scope

- New command contract for `ingest`, `transform`, `update`.
- Stage split in orchestration (`pipeline.py`) without changing core parser behavior.
- Staged artifact contract for ingest->transform handoff.
- Backward-compatible deprecation path for legacy `run`.
- Tests/docs updates for the new command surface.

### Out of scope

- Parser rule logic changes.
- Categorization model improvements.
- Reconciliation policy changes unrelated to command split.

## Command Contract

### `python -m finance_tooling ingest`

Purpose: ingest only (discover, parse, HSBC merge, incremental state updates).

Required behavior:

- Supports incremental/full selection:
  - `--ingest-mode {new,changed,new-or-changed,all}`
- Supports state/period/snapshot controls:
  - `--state-path <path>`
  - `--replace-source-on-reingest {true,false}`
  - `--allow-closed-period-ingest`
  - `--snapshot-before-run {true,false}`
  - `--strict-guardrails {true,false}`
- Writes staged output (default):
  - `${FINANCE_PROCESSED_PATH}/staged_transactions.parquet`
- Writes ingest-only summary:
  - `${FINANCE_PROCESSED_PATH}/ingest_summary.json`
- Must not apply FX conversion or category taxonomy.

### `python -m finance_tooling transform`

Purpose: transform only (category + FX + final persistence/reporting).

Required behavior:

- Input:
  - `--input-staged-path <path>` (default staged artifact path)
- Controls:
  - `--metrics-scope {both,run,global}`
  - `--strict-guardrails {true,false}`
- Runs:
  - `enrich_transactions`
  - `persist_and_report`
- Writes existing final artifacts:
  - `transactions_master.parquet`
  - `transactions_normalized.csv/json`
  - `run_summary.json`
  - `completeness_report.json`
  - dashboard HTML

### `python -m finance_tooling update`

Purpose: combined orchestration.

Default:

- Runs `ingest` then `transform`.

Optional control:

- `--ingest-only`
- `--transform-only`

### Legacy `run`

- Keep as alias to `update` for one release.
- Emit deprecation warning with explicit migration message.

## Architecture Changes

## Pipeline entrypoints

Refactor `pipeline.py` to expose:

- `run_ingest(settings, ...) -> IngestExecutionResult`
- `run_transform(settings, *, staged_path, ...) -> WorkflowResult`
- `run_update(settings, ...) -> WorkflowResult | IngestExecutionResult`
- Keep `run_workflow` compatibility wrapper pointing to `run_update`.

## New staging module

Add `src/finance_tooling/workflow/staging.py`:

- `write_staged_transactions(path: Path, transactions: list[Transaction]) -> StagingWriteResult`
- `read_staged_transactions(path: Path) -> list[Transaction]`
- Validate required canonical columns and fail with actionable error messages.

## Config additions

Add to `config.py`:

- `FINANCE_STAGED_TRANSACTIONS_PATH`
- `Settings.staged_transactions_path: Path`
- Default: `${FINANCE_PROCESSED_PATH}/staged_transactions.parquet`

## CLI changes

Refactor `__main__.py`:

- Add parser/handlers for `ingest`, `transform`, `update`.
- Keep existing utility commands (`review-export`, `review-import`, `metrics-log-update`, `periods`, `restate`).
- Route deprecated `run` to `update` handler and print deprecation warning.

## Data/Artifact Contracts

### Staged dataset schema (parquet)

Use canonical transaction fields produced post-ingest/pre-enrichment (must include):

- booking/date/description/amount/currency
- source metadata (`source_file`, parser, bank/account label)
- category placeholders as currently modeled (unchanged values permitted)

### Ingest summary

Store ingest-stage counters/diagnostics without transform metrics:

- selected/discovered/skipped counters
- parse failures/warnings
- state/snapshot paths
- incremental mode metadata

### Transform summary

Continue current `run_summary.json` contract for metrics log compatibility.

## Implementation Steps

1. Introduce staging IO module and typed result dataclass.
2. Split existing mixed pipeline flow into `run_ingest` and `run_transform`.
3. Add `run_update` orchestration and keep `run_workflow` compatibility shim.
4. Extend `Settings` with staged path env/default.
5. Refactor CLI command tree and handlers.
6. Add deprecation warning path for `run`.
7. Update `perf_check.py` to benchmark through updated orchestration.
8. Update docs/README command examples and expected artifacts.

## Test Plan

1. Unit: staging read/write roundtrip + schema validation errors.
2. Integration: `ingest` writes staged artifact and does not enrich/persist final outputs.
3. Integration: `transform` reads staged artifact and writes final artifacts.
4. Integration: `update` chains both successfully.
5. CLI: legacy `run` executes `update` path and prints deprecation warning.
6. Regression: `metrics-log-update` still parses `run_summary.json` unchanged.
7. Regression: existing incremental state/period-lock semantics remain intact under `ingest`.

## Acceptance Criteria

- Commands available: `ingest`, `transform`, `update`.
- `ingest` and `transform` stage boundaries are strict and non-overlapping.
- `update` default executes both stages.
- Legacy `run` remains operational as deprecating alias.
- Quality gates pass:
  - `uv run ruff check .`
  - `uv run ruff format .`
  - `uv run ty check src/finance_tooling tests`
  - `uv run pytest`

## Assumptions

- Staged artifact is parquet by default for speed and schema stability.
- Existing parser/model logic remains unchanged; this is an API/orchestration refactor.
- One-release deprecation window for `run`.

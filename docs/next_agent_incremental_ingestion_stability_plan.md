# Incremental Ingestion Stability Plan (Next Agent)

## Objective
Implement a long-term, low-friction monthly ingestion workflow that processes only new/changed statements by default while preserving historical stability and auditability.

## Why This Change
Current behavior scans the full statement corpus every run. Upsert is idempotent for exact transaction IDs, but there is no first-class stateful incremental mode, no explicit closed-period protection, and no controlled restatement workflow.

## Scope

### In scope
- Stateful incremental selection (`new`, `changed`, `new-or-changed`, `all`)
- Source-level replace-on-reingest semantics
- Period open/closed controls
- Explicit restatement command + logging
- Run/global metric scope split
- Snapshot + guardrail safety controls

### Out of scope (later)
- Automatic post-ingest archival/move behavior
- Rename aliasing heuristics for moved files
- UI; CLI-first only

## Required CLI/API Changes

### Extend `python -m finance_tooling run`
Add flags:
- `--ingest-mode {new,changed,new-or-changed,all}` (default: `new-or-changed`)
- `--state-path <path>` (default: `<FINANCE_PROCESSED_PATH>/ingest_state.json`)
- `--replace-source-on-reingest {true,false}` (default: `true`)
- `--metrics-scope {both,run,global}` (default: `both`)
- `--allow-closed-period-ingest` (default: `false`)
- `--snapshot-before-run` (default: `true`)
- `--strict-guardrails` (default: `true`)

### New command: period controls
- `python -m finance_tooling periods set --month YYYY-MM --status {open,closed}`
- `python -m finance_tooling periods list`

### New command: restatement
- `python -m finance_tooling restate --from YYYY-MM --to YYYY-MM --reason "<text>" [--dry-run]`

### Config/env additions
Add env support in `config.py` for:
- `FINANCE_INGEST_MODE`
- `FINANCE_INGEST_STATE_PATH`
- `FINANCE_REPLACE_SOURCE_ON_REINGEST`
- `FINANCE_METRICS_SCOPE`
- `FINANCE_ALLOW_CLOSED_PERIOD_INGEST`
- `FINANCE_SNAPSHOT_BEFORE_RUN`
- `FINANCE_STRICT_GUARDRAILS`

## New Artifacts and Schemas

### `ingest_state.json`
Per canonical source file entry:
- `path`
- `size_bytes`
- `mtime_ns`
- `sha256`
- `first_seen_at`
- `last_ingested_at`
- `last_status` (`success`/`failed`)
- `last_error`
- `last_run_id`
- `bank_guess`
- `statement_month`

### `period_status.json`
- Map: `YYYY-MM -> open|closed`

### `restatement_log.jsonl`
Append-only entries:
- `timestamp`
- `from_month`
- `to_month`
- `reason`
- `run_id`
- `dry_run`
- `rows_before`
- `rows_after`
- `delta`

### `snapshots/`
Before-run snapshots of:
- master parquet
- ingest state
- period status
- effective rule/override references

## Pipeline Behavior (Decision Complete)
1. Discover PDFs as today.
2. Compute file signature and classify each file vs state: `new`, `changed`, `unchanged`.
3. Select processing set by `ingest_mode`.
4. Parse/classify/enrich selected files only.
5. Enforce period lock:
   - if file maps to closed month, skip unless explicitly allowed or restate flow.
6. Persist behavior:
   - `new`: append (idempotent)
   - `changed`: delete existing rows for `source_file` then insert fresh rows
   - `new-or-changed`: both
   - `all`: full scan with replace enabled per source
7. Update state only after successful persistence.
8. Emit summary with both metric scopes (run + global).

## Risk Mitigation Controls
- **Historical drift risk**: closed periods + explicit restatement only
- **Stale rows risk**: replace-by-source on changed reingest
- **Semantic ambiguity risk**: include `rule_set_version` / `override_set_version` and `run_id` in summaries
- **Operational risk**: snapshot-before-run + guardrail thresholds
- **Misleading KPI risk**: always expose run-scope and global-scope separately

## Guardrails (Fail in strict mode)
- Reconciliation pass ratio below configured floor
- Uncategorized ratio above configured ceiling
- Row delta anomalies beyond configured tolerance

## Testing Requirements
Add/extend tests to cover:
1. New-only ingestion skips known files
2. Changed-file detection and replace behavior
3. Unchanged files are not reparsed
4. State does not advance on persistence failure
5. Closed period blocking in normal run
6. Restatement bypass with logging and dry-run support
7. Summary includes run/global scopes and control metadata
8. CLI/env precedence and defaults
9. Snapshot creation when enabled
10. Guardrail fail/warn behavior

## Suggested Implementation Order
1. Add config/CLI surfaces + typed settings fields.
2. Implement ingest state store and file classification.
3. Implement source-level replace persistence path.
4. Add dual-scope summary payload fields.
5. Add period status model + command handlers.
6. Add restatement command + logging.
7. Add snapshot utility and guardrails.
8. Update docs and tests; run full quality gates.

## Quality Gates (must pass)
- `uv run ruff check .`
- `uv run ruff format .`
- `uv run ty check src/finance_tooling tests`
- `uv run pytest`

## Defaults Chosen
- Monthly operation default: `new-or-changed`
- Rule policy: forward-only by default
- Reingest policy: replace-by-source for changed files
- Guardrails: strict mode enabled by default

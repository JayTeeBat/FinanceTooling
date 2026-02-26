# AGENTS.md

## Mission

This repository exists to build reliable, Python-based tooling for monitoring
personal finances. The immediate focus is accurate bank statement ingestion and
normalization. The long-term goal is a maintainable pipeline for analysis,
categorization, and reporting.

## Parser Performance Snapshot

### HSBC parser (latest full-corpus run: 2026-02-25)

- HSBC statement reconciliation failures: `20` (latest known count).
- Largest residual outlier: `2017-08` with `|diff|=754.70`.
- Statements missing parsed period windows: `1`.
- Recent trajectory:
  - Prior runs were `69/71` (PDF-only processed run) and `30/71`.
  - Current run is `20/71` failed/checkable for HSBC validations.
  - Overall statement reconciliation is `22/193` failed/checkable.
- Immediate hardening targets: high-diff months (`2017-08`, `2016-12`) and
  residual mid-diff months (`2019-05`, `2019-06`, `2019-07`).

## Engineering Standards

- Prefer simple, testable modules over monolithic scripts.
- Keep I/O boundaries explicit and isolate parsing/business logic.
- Type annotate all new public functions.
- Enforce quality gates before merges:
  - `uv run ruff check .`
  - `uv run ruff format .`
  - `uv run ty check src/finance_tooling tests`
  - `uv run pytest`
- Use `pre-commit` for local guardrails:
  - `uv run pre-commit install`
  - `uv run pre-commit run --all-files`

## Tooling Baseline

- Package/dependency manager: `uv`
- Lint/format: `ruff` (check + format)
- Type analysis: `ty`
- Test runner: `pytest`
- Commit hooks: `pre-commit`

## Repo Workflow Guidelines

- Branch naming:
  - `feature/<topic>` for features
  - `fix/<topic>` for bug fixes
  - `refactor/<topic>` for refactors
  - `chore/<topic>` for maintenance/tooling
- No work happens directly on `main`; always use the standard work branch ->
  PR -> merge process.
- Keep pull requests focused and small enough to review quickly.
- Do not rewrite history on shared branches.
- Do not remove or rewrite legacy scripts unless a migration plan is included.

### Standard Workflow

1. Do not work on `main`; implement changes on a dedicated
   `feature/<topic>`, `fix/<topic>`, or `refactor/<topic>` branch.
2. Before proposing merge, ensure work is user-validated and all mandatory
   quality gates pass:
   - `uv run ruff check .`
   - `uv run ruff format .`
   - `uv run ty check src/finance_tooling tests`
   - `uv run pytest`
3. Once validated and green, commit on the working branch, push to `origin`,
   and open a PR targeting `main` (do not merge directly from local state).

## Legacy and Migration Policy

- Legacy script logic has been migrated into typed package modules under
  `src/finance_tooling/`.
- New work should go into package modules under `src/finance_tooling/`.
- Parsing behavior should be locked with tests when migrating additional bank
  formats or edge cases.
- Strict lint/type gates apply to package modules and tests.

## Session Hand-Off Protocol

When ending a session, update `## Hand-Off Log` with one new entry containing:

- Date (ISO): `YYYY-MM-DD`
- Agent/session identifier (if available)
- Branch name
- Summary of changes made
- Quality checks run and outcomes
- Known issues / TODOs
- Recommended next action

Retention rule: keep only the latest 3 entries in `## Hand-Off Log`. When
adding a new entry, remove older entries beyond the newest three.

Use this template:

```text
### YYYY-MM-DD - <agent/session-id>
- Branch: <branch-name>
- Completed:
  - <change 1>
  - <change 2>
- Checks:
  - <command>: <pass/fail/not run>
- Open items:
  - <item 1>
- Next action:
  - <single highest priority next step>
```

## Next Agent Recommendations

Prioritized recommendations from latest repo assessment:

1. Decompose workflow orchestration in `src/finance_tooling/pipeline.py`
- Split into focused units (`ingest`, `hsbc_merge`, `enrichment`, `reporting`) while preserving behavior.
- Benefit: lower maintenance risk, simpler reasoning, smaller test surfaces.

2. Tighten typed boundaries for report payloads
- Replace broad `dict[str, object]` payload construction/casts with typed dataclasses or `TypedDict` for summary and completeness outputs.
- Benefit: safer refactors and clearer internal APIs.

3. Preserve monetary precision through storage/reporting paths
- Reduce `Decimal -> float` conversions where not strictly required; keep decimal-safe representation until final presentation.
- Benefit: better reconciliation accuracy and less rounding drift.

4. Replace broad exception handling with targeted error categories
- Narrow `except Exception` blocks in workflow/FX paths and emit structured warning context.
- Benefit: improved observability and faster debugging of real failures.

5. Improve parser/importer extensibility model
- Move from static registry tuple toward explicit plugin registration/discovery pattern.
- Benefit: easier onboarding of additional bank formats with cleaner boundaries.

6. Keep quality gates mandatory
- Continue enforcing:
  - `uv run ruff check .`
  - `uv run ruff format .`
  - `uv run ty check src/finance_tooling tests`
  - `uv run pytest`
- Benefit: protects reliability during refactors of parser and pipeline internals.

## Hand-Off Log

### 2026-02-26 - codex
- Branch: `feature/pipeline-decomposition`
- Completed:
  - Changed default ingest text cache location to live beside raw statements
    under the same parent directory:
    `<FINANCE_STATEMENTS_PATH>/../cache/ingest_text_cache.parquet`.
  - Kept explicit override support via `FINANCE_INGEST_TEXT_CACHE_PATH`.
  - Updated README documentation to reflect encrypted-vault-aligned default
    cache placement.
  - Updated config tests for the new default cache path behavior.
- Checks:
  - `uv run ruff check src/finance_tooling/config.py tests/test_config.py README.md`: pass
  - `uv run pytest tests/test_config.py`: pass
- Open items:
  - Existing hand-off entries still reference the prior `<processed>` default
    path for cache location.
- Next action:
  - Align historical performance notes/examples to the new sibling-of-raw cache
    default wherever needed.

### 2026-02-26 - codex
- Branch: `feature/pipeline-decomposition`
- Completed:
  - Added persistent ingest text cache module
    (`src/finance_tooling/workflow/ingest_cache.py`) with parquet-backed
    load/upsert and keying by `(resolved_path, mtime_ns, file_size)`.
  - Added cache settings:
    `FINANCE_INGEST_TEXT_CACHE_ENABLED` (default `false`) and
    `FINANCE_INGEST_TEXT_CACHE_PATH` (default
    `<processed>/ingest_text_cache.parquet`).
  - Integrated cache hit/miss/write flow into ingestion prep and propagated
    cache diagnostics into `run_summary.json` and `performance_summary.json`.
  - Added/updated tests for cache behavior and config coverage in
    `tests/test_ingest.py`, `tests/test_config.py`,
    `tests/test_pipeline.py`, and `tests/test_perf_check.py`.
  - Validated cache behavior on full corpus in isolated path:
    `/tmp/finance_tooling_processed_perf_cache_20260226-224820`
    (run 2: ingest `2.709s`, cache hits `199`).
- Checks:
  - `uv run ruff check src/finance_tooling tests`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest tests/test_config.py tests/test_ingest.py tests/test_pipeline.py tests/test_perf_check.py`: pass
  - `FINANCE_PROCESSED_PATH=/tmp/finance_tooling_processed_perf_cache_20260226-224820 FINANCE_FX_AUTO_FETCH=false FINANCE_INGEST_WORKERS=4 FINANCE_INGEST_TEXT_CACHE_ENABLED=true FINANCE_HSBC_CSV_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw uv run python -m finance_tooling.perf_check`: pass
- Open items:
  - Cache currently has no pruning/retention policy for very long-lived runs.
  - Ingest parser/bank timing aggregates still exclude extraction-time
    attribution.
- Next action:
  - Add cache pruning policy (for example, max-age or max-rows) and extend
    ingest timing diagnostics to separate extraction vs parser time.

### 2026-02-26 - codex
- Branch: `feature/pipeline-decomposition`
- Completed:
  - Added opt-in ingestion worker config (`FINANCE_INGEST_WORKERS`) and
    parallelized ingest preparation in `src/finance_tooling/workflow/ingest.py`
    while preserving default single-process behavior.
  - Added ingest timing aggregates by parser and bank to workflow contracts and
    summary artifacts (`run_summary.json`, `performance_summary.json`).
  - Reduced repeated HSBC full-text flattening by introducing shared flattened
    parsing helpers in ingest stage.
  - Added ingest-focused tests in `tests/test_ingest.py` and expanded config
    and pipeline/perf coverage for new settings and summary fields.
  - Ran an isolated full-corpus perf check with workers:
    `/tmp/finance_tooling_processed_perf_workers4_20260226-223247`.
- Checks:
  - `uv run ruff check src/finance_tooling tests`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest tests/test_config.py tests/test_ingest.py tests/test_pipeline.py tests/test_perf_check.py`: pass
  - `FINANCE_PROCESSED_PATH=/tmp/finance_tooling_processed_perf_workers4_20260226-223247 FINANCE_FX_AUTO_FETCH=false FINANCE_INGEST_WORKERS=4 FINANCE_HSBC_CSV_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw uv run python -m finance_tooling.perf_check`: pass
- Open items:
  - Ingest timing aggregates currently cover parser parse time, not extraction
    time per parser/bank.
  - Font descriptor warnings from PDF extraction remain noisy in full-corpus
    runs.
- Next action:
  - Add extraction-time attribution in ingest diagnostics and evaluate optional
    warning suppression for known pdfplumber FontBBox noise.

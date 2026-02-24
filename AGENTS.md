# AGENTS.md

## Mission

This repository exists to build reliable, Python-based tooling for monitoring
personal finances. The immediate focus is accurate bank statement ingestion and
normalization. The long-term goal is a maintainable pipeline for analysis,
categorization, and reporting.

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
  - `chore/<topic>` for maintenance/tooling
- Keep pull requests focused and small enough to review quickly.
- Do not rewrite history on shared branches.
- Do not remove or rewrite legacy scripts unless a migration plan is included.

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

## Hand-Off Log

### 2026-02-24 - codex
- Branch: `fix/parser-hardening`
- Completed:
  - Removed legacy parser routing API (`can_handle`) and standardized selection
    on confidence scoring (`match_score`) with deterministic threshold/tie
    behavior.
  - Added parser routing diagnostics (`ParserSelection` /
    `ParserScoreItem`) and integrated per-file selection diagnostics plus
    low-confidence counts into workflow warnings and `run_summary.json`.
  - Harmonized parser row normalization flow across bank parsers and improved
    Revolut sign inference with hint-priority default-debit behavior.
  - Added/updated tests for parser scoring, routing diagnostics, sign inference,
    and pipeline diagnostics integration.
  - Ran full ingestion pipeline against real corpus and reviewed resulting
    completeness/reconciliation diagnostics.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `uv run python -m finance_tooling`: pass
- Open items:
  - Reconciliation quality remains poor in real run: `83` failed / `85`
    checkable statements (pass ratio `0.024`), concentrated in HSBC and Revolut.
  - Statement coverage gaps remain (`16` statement PDFs with zero parsed rows):
    mostly HSBC (`14`) plus two Boursobank files.
  - One low-confidence parser route detected:
    `Boursobank Marion Releve-compte-30-09-2022.pdf` selected as Revolut
    (score `2`, threshold `2`).
- Next action:
  - Implement fixture-driven HSBC parser hardening for the identified missing/
    failing years first, then re-run full pipeline and verify reconciliation
    deltas.

### 2026-02-23 - codex
- Branch: `fix/lbp-fx-dated-rates`
- Completed:
  - Audited end-to-end ingestion completeness against source PDFs under
    `/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw`.
  - Verified parser reconciliation fix for LaBanquePostale statements and
    confirmed zero LBP totals mismatches in current run.
  - Isolated remaining gap as completeness/coverage (not reconciliation):
    many PDFs still produce zero parsed rows.
- Checks:
  - `uv run python -m finance_tooling`: pass
  - `uv run pytest`: pass
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
- Open items:
  - Parsed coverage is incomplete:
    `transactions_master.parquet` currently spans only 2018-2024 while source
    PDFs exist for 2016-2026.
  - 134 of 187 PDFs currently have zero parsed transactions.
  - Most missing coverage appears in Boursobank/Revolut and earlier HSBC years.
- Next action:
  - Implement automated completeness reporting in workflow output with
    machine-readable pass/warn/fail thresholds and explicit missing-file lists.
  - Minimum spec for next agent:
    - Add `src/finance_tooling/completeness.py` with:
      - source PDF count
      - unique parsed source file count
      - file coverage ratio
      - counts by year (source vs parsed)
      - counts by bank guess (source) and by bank (parsed)
      - missing source files list + grouped summaries
      - status: `pass` / `warn` / `fail`
      - reasons and thresholds in payload
    - Write `<input>/completeness_report.json` each run.
    - Add report path + key coverage stats to `run_summary.json` and CLI output.
    - Add tests in `tests/test_completeness.py` and pipeline integration tests.

### 2026-02-23 - codex
- Branch: `chore/bootstrap-python-tooling`
- Completed:
  - Implemented historical FX module with ECB SDW polling, local parquet cache,
    and previous-business-day fallback by transaction booking date.
  - Updated workflow/config/models/store to persist dated FX metadata per
    transaction (`fx_rate_to_eur`, `fx_rate_date`, `fx_source`) and compute EUR
    amounts from dated rates for new rows.
  - Added FX-focused tests for ECB CSV parsing, fallback resolution, and cache
    hydration flow; updated README env documentation for FX cache settings.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Add fixture-backed tests against real statement samples for each bank parser.
  - Add OCR fallback for scanned/image-only PDF statements.
- Next action:
  - Run full historical ingestion and inspect warnings for missing FX ranges or
    parser edge cases.

### 2026-02-23 - codex
- Branch: `chore/bootstrap-python-tooling`
- Completed:
  - Implemented parser plugin architecture with dedicated parsers for
    LaBanquePostale, HSBC, Boursobank, and Revolut plus generic fallback.
  - Migrated useful logic from legacy LaBanquePostale importer into typed
    parser modules and removed legacy scripts (`src/LBP_API.py`,
    `src/import_statements.py`).
  - Added canonical parquet store with idempotent upsert, exports, FX-aware
    metrics, and dashboard generation from parquet as source of truth.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Improve parser coverage for scanned/image-only PDFs (OCR fallback).
  - Add fixture PDFs per bank format for richer regression coverage.
- Next action:
  - Add OCR-backed extraction fallback and bank fixture-based golden tests.

### 2026-02-23 - codex
- Branch: `chore/bootstrap-python-tooling`
- Completed:
  - Upgraded `.pre-commit-config.yaml` to include official `ruff-pre-commit`
    hooks and standard hygiene hooks.
  - Implemented an end-to-end workflow under `src/finance_tooling/` for env-based
    folder scanning, PDF text extraction, transaction parsing, heuristic
    classification, metrics aggregation, and HTML dashboard rendering.
  - Replaced scaffold CLI with workflow execution via env settings and added tests
    for parsing, classification, and metrics.
- Checks:
  - `uv run pre-commit run --all-files`: pass
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Add bank-specific parsers (per bank format) and OCR fallback for scanned PDFs.
  - Add currency-aware cross-currency reporting (FX normalization strategy).
- Next action:
  - Introduce parser plugins per bank statement format with fixture PDFs and
    golden tests.

### 2026-02-22 - codex
- Branch: `chore/bootstrap-python-tooling`
- Completed:
  - Added Python project scaffold via `pyproject.toml` with `uv`, `ruff`, `ty`,
    `pytest`, and `pre-commit` dev tooling.
  - Added `.pre-commit-config.yaml` with local hooks for `ruff` and `ty`.
  - Added package skeleton under `src/finance_tooling/` and a smoke test in
    `tests/test_healthcheck.py`.
  - Updated `README.md` with setup and quality-gate commands.
  - Preserved existing legacy scripts untouched.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Migrate legacy scripts into typed package modules with tests.
  - Add domain model for transactions and statement metadata.
- Next action:
  - Run `uv sync --all-groups` and execute all quality gates, then fix findings.

### 2026-02-23 - codex
- Branch: `fix/completeness-reporting`
- Completed:
  - Added `src/finance_tooling/completeness.py` to compute machine-readable post-parse completeness metrics: source PDF count, parsed unique source file count, coverage ratio, counts by year, source bank-guess counts, parsed bank counts, missing-file list, grouped missing summaries, and thresholded status/reasons.
  - Integrated completeness reporting into workflow output by writing `<input>/completeness_report.json` each run and by adding completeness path/status/coverage/missing-file stats into `run_summary.json`, CLI output, and `WorkflowResult`.
  - Added tests in `tests/test_completeness.py` and `tests/test_pipeline.py` to validate completeness logic and pipeline integration/wiring.
- Checks:
  - `uv run ruff format .`: pass
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Current bank/year source inference in completeness reporting is filename/path heuristic-based and may need refinement per real statement naming conventions.
- Next action:
  - Run a full ingestion against the real statement corpus and tune completeness status thresholds/heuristics based on observed false positives.

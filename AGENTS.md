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

## Hand-Off Log

### 2026-02-25 - codex
- Branch: `fix/parser-hardening-hsbc`
- Completed:
  - Implemented HSBC period-window remapping for CSV transactions using parsed
    PDF statement periods (`start -> end`) before adaptive source selection.
  - Added statement-period parsing from HSBC PDF text and integrated period
    metadata into month selection diagnostics.
  - Added remap diagnostics/counters in `run_summary.json` for applied periods,
    reassigned CSV rows, and unassigned CSV rows.
  - Added tests for statement-period parsing and CSV boundary-day reassignment.
  - Updated README to document period-window remapping behavior.
- Checks:
  - `uv run pytest tests/test_pipeline.py tests/test_hsbc_csv_import.py`: pass
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `FINANCE_STATEMENTS_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_PROCESSED_PATH=/tmp/ft-hsbc-remap FINANCE_HSBC_CSV_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_FX_AUTO_FETCH=false uv run python -m finance_tooling`: pass
- Open items:
  - HSBC failures remain at `30` checkable statements; largest residual outlier
    is still 2019-03 (`|diff|=3903.76`), indicating a specific parser/sign
    issue beyond period alignment.
  - Five HSBC statements still lack parsed period windows (`statement_period_*`
    absent in diagnostics), limiting remap precision for those months.
- Next action:
  - Add fixture-driven parser hardening for the remaining high-diff months
    (especially 2019-03 and 2021-04) and improve period parsing coverage for
    the missing-window HSBC layouts.

### 2026-02-25 - codex
- Branch: `fix/parser-hardening-hsbc`
- Completed:
  - Implemented adaptive HSBC month-level source selection in pipeline:
    for overlap months with both CSV and PDF rows, choose the source with
    lower PDF-balance reconciliation absolute difference.
  - Added HSBC adaptive diagnostics and metrics in `run_summary.json`,
    including policy marker, adaptive switch count, selected CSV/PDF month
    counts, and per-month selection diagnostics.
  - Extended HSBC reconciliation warning payload to include candidate absolute
    differences for CSV and PDF sums.
  - Updated pipeline tests to assert adaptive selection behavior (including
    overlap switch to PDF when PDF reconciles better) and new summary fields.
  - Updated README HSBC merge policy to document adaptive overlap selection.
- Checks:
  - `uv run pytest tests/test_pipeline.py tests/test_hsbc_csv_import.py`: pass
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `FINANCE_STATEMENTS_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_PROCESSED_PATH=/tmp/ft-hsbc-adaptive FINANCE_HSBC_CSV_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_FX_AUTO_FETCH=false uv run python -m finance_tooling`: pass
- Open items:
  - HSBC reconciliation still has `59` failed / `85` checkable statements,
    with most failures still on HSBC-selected months.
  - HSBC balance-validation fail count remains high (`59`) despite much lower
    median absolute difference.
- Next action:
  - Add fixture-driven month-level guardrails for the top residual outliers
    (`|diff| > 1000`) and codify deterministic fallback rules for those
    specific layouts.

### 2026-02-25 - codex
- Branch: `fix/parser-hardening-hsbc`
- Completed:
  - Hardened HSBC CSV importer date parsing to support raw monthly export
    formats (`%d %b %Y`, `%d %B %Y`, and `%d/%m/%Y`), enabling ingestion from
    raw HSBC CSV files.
  - Replaced HSBC PDF/CSV overlap heuristics with statement-date source
    selection: CSV replaces PDF for matching months, PDF fallback is kept when
    CSV is missing, and CSV-only months are retained.
  - Added HSBC PDF-balance-driven validation recomputation so selected monthly
    data (CSV or PDF fallback) is reconciled against PDF opening/closing
    balances, with explicit warnings on reconciliation mismatches.
  - Added HSBC merge/validation counters to `run_summary.json` and updated
    README to document monthly CSV-first merge and PDF-balance validation
    behavior.
  - Updated HSBC CSV importer and pipeline tests for date parsing, monthly
    source selection, fallback handling, and PDF-balance validation warnings.
- Checks:
  - `uv run pytest tests/test_hsbc_csv_import.py tests/test_pipeline.py`: pass
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `FINANCE_STATEMENTS_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_PROCESSED_PATH=/tmp/ft-hsbc-post-impl FINANCE_HSBC_CSV_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_FX_AUTO_FETCH=false uv run python -m finance_tooling`: pass
- Open items:
  - HSBC reconciliation remains imperfect at `61` failed / `85` checkable
    statements on the real corpus.
  - HSBC median absolute reconciliation difference increased to `453.07`,
    indicating remaining month-specific parsing/sign issues.
- Next action:
  - Add fixture-driven month-level diagnostics for the largest remaining HSBC
    outliers and refine row/sign rules for those statement layouts.

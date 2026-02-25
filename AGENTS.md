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
- Branch: `fix/hsbc-parser-metrics`
- Completed:
  - Hardened HSBC period parsing to handle OCR spacing variants
    (`Januaryto`, `January2017`, optional start-year).
  - Added HSBC parser safeguards for running-balance-backed continuation
    dedupe and in-block running-balance sign override for ambiguous rows.
  - Added regression tests for period parsing variants, continuation dedupe,
    and running-balance sign override behavior.
  - Re-ran full corpus pipeline against processed path and refreshed current
    HSBC residual-failure snapshot metrics.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `FINANCE_STATEMENTS_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_PROCESSED_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed FINANCE_HSBC_CSV_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_FX_AUTO_FETCH=false uv run python -m finance_tooling`: pass
- Open items:
  - HSBC residual failures remain concentrated in `2017-08` (`|diff|=754.70`)
    and `2016-12` (`|diff|=547.29`), plus moderate outliers in `2019-05`
    through `2019-07`.
  - One HSBC statement month still has missing parsed period-window metadata.
- Next action:
  - Add fixture-driven parser hardening for remaining top outliers,
    prioritizing `2017-08` duplicate/continuation layout behavior.

### 2026-02-25 - codex
- Branch: `fix/hsbc-parser-metrics`
- Completed:
  - Created dedicated worktree at `/home/thomazo/dev/FinanceTooling-hsbc-parser`
    for HSBC parser work.
  - Added top-level HSBC parser performance snapshot metrics for quick
    agent/session orientation.
- Checks:
  - `git worktree list`: pass
- Open items:
  - Parser snapshot values are based on latest logged full-corpus run and
    should be refreshed after the next reconciliation run.
- Next action:
  - Re-run full HSBC corpus pipeline and update snapshot metrics with fresh
    counts/deltas.

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

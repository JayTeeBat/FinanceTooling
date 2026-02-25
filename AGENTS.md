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
  - Added `## Next Agent Recommendations` section before `## Hand-Off Log`.
  - Documented prioritized architecture and maintainability improvements for the next agent session.
- Checks:
  - `sed -n '1,280p' AGENTS.md`: pass
- Open items:
  - Recommendations are documented; implementation work is still pending in code modules.
- Next action:
  - Add fixture-driven parser hardening for the remaining high-diff months
    (especially 2019-03 and 2021-04) and improve period parsing coverage for
    the missing-window HSBC layouts.

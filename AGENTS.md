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
- Branch: `fix/hsbc-csv-import-main`
- Completed:
  - Added optional HSBC CSV source support via `FINANCE_HSBC_CSV_PATH` and CSV discovery for file/folder inputs.
  - Implemented typed HSBC CSV importer (`hsbc_csv`) that normalizes transactions into the canonical model and emits parse warnings for malformed input rows.
  - Integrated cross-source conflict handling in pipeline to prevent duplicate insertion between PDF and CSV extracts and to deterministically prefer CSV rows on clashes.
  - Added summary diagnostics for CSV ingestion and cross-source resolution (`hsbc_csv_files_scanned`, duplicate/clash drop counts).
  - Updated README and added tests for config wiring, CSV importer behavior, and PDF-vs-CSV duplicate/clash resolution.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - HSBC CSV conflict resolution currently uses a heuristic description similarity threshold; edge-case tuning may be needed against additional real-world samples.
  - Cross-source resolution currently prefers CSV for HSBC rows only; if additional bank CSV imports are added, policy should be generalized.
- Next action:
  - Run full real-corpus ingestion with `FINANCE_HSBC_CSV_PATH` enabled and review clash warnings to calibrate the similarity heuristic.

### 2026-02-25 - codex
- Branch: `FinanceTooling-parser-hardening-revolut`
- Completed:
  - Hardened `RevolutParser` to scope extraction to `Account transactions`
    sections, excluding `Reverted` and `Personal and Group Pockets` sections.
  - Switched Revolut sign inference to running-balance delta logic with fallback
    behavior, and added Revolut-specific date normalization for `Sept` tokens.
  - Added fixture-driven Revolut regression coverage under
    `tests/fixtures/revolut/` and `tests/test_revolut_fixtures.py` for balance
    delta signs, section boundaries, and missing-summary behavior.
  - Updated existing Revolut synthetic/parser tests to align with
    balance-driven sign expectations.
  - Re-ran full workflow on real corpus and confirmed reconciliation deltas:
    Revolut moved to `14` pass (checkable) with `median_abs_difference: 0.0`
    and no Revolut reconciliation warnings.
- Checks:
  - `uv run ruff format .`: pass
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `FINANCE_STATEMENTS_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_PROCESSED_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed uv run python -m finance_tooling`: pass
- Open items:
  - One low-confidence routing case remains where
    `Boursobank Marion Releve-compte-30-09-2022.pdf` is selected as `revolut`
    and recorded as uncheckable under Revolut status buckets.
- Next action:
  - Tighten parser scoring/routing tie-break behavior to prevent known
    Boursobank-vs-Revolut misclassification on low-confidence files.

### 2026-02-25 - codex
- Branch: `fix/parser-hardening`
- Completed:
  - Hardened HSBC non-transaction filtering with explicit legal/footer noise
    markers (FSCS/rate/price-list/cap language) to prevent amount-bearing
    informational lines from being parsed as transactions.
  - Added HSBC continuation-context guardrails so non-transaction context lines
    reset pending parsing state instead of seeding amount row parsing.
  - Added seven new HSBC fixture cases covering edge cases for:
    footer/rate amount noise (2019/2021 variants), reversal sign isolation,
    large BP transfer sign handling, high-value CR block parsing, and
    statement-tail context termination.
  - Ran targeted HSBC tests, full quality gates, and full ingestion pipeline.
- Checks:
  - `uv run pytest tests/test_hsbc_fixtures.py tests/test_parser.py -k hsbc`: pass
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `uv run python -m finance_tooling`: pass
- Open items:
  - HSBC severe reconciliation failures (`|diff| > 1000`) remain unchanged at
    `15` despite parser hardening and fixture expansion.
  - Overall reconciliation improved slightly (`81` failed / `85` checkable vs
    prior `83` failed / `85`), with HSBC status now `69` fail / `2` pass.
  - Largest remaining HSBC outliers include 2021-05 (`-20114.14`) and 2019-03
    (`-13040.64`), indicating additional row-classification/sign rules are
    still needed for specific high-value statement patterns.
- Next action:
  - Add fixture-driven HSBC rules for salary/transfer/reversal block semantics
    in 2017/2019/2021 outlier layouts, then rerun pipeline and target HSBC
    severe fail reduction below `10` in the next pass.

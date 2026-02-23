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

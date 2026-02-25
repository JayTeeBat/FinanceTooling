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
- Branch: `fix/parser-hardening-boursobank`
- Completed:
  - Marked non-statement PDFs in pipeline validation metadata (`statement_type`) using `classify_statement_type`, then excluded non-statement validations from reconciliation rollups.
  - Tightened Boursobank sign inference to strict column-first behavior (removed transfer keyword positive fallback), kept explicit refund overrides, and added skip-warning path for ambiguous amount positioning.
  - Added targeted regression coverage for COM exclusion and Boursobank transfer-sign edge cases (`VIRSEPA`/`VIRINST`) that previously drove large reconciliation deltas.
  - Re-ran full corpus benchmark and reduced Boursobank from `83` uncheckable to `79` pass / `2` fail with `0` COM files present in reconciliation info items.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `FINANCE_STATEMENTS_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_PROCESSED_PATH=/tmp/finance-boursobank-final-kg5xSH FINANCE_FX_AUTO_FETCH=false FINANCE_FX_CACHE_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed/fx_rates_history.parquet .venv/bin/python -m finance_tooling`: pass
- Open items:
  - Two Boursobank files still fail reconciliation with small `2.00` diffs (`2020-10` and `2020-11`), likely from minor OCR/rounding or one-row sign ambiguity in legacy layout.
  - HSBC remains the dominant unresolved reconciliation source (`69` fail / `2` pass) and now drives most remaining warning volume.
- Next action:
  - Add fixture-backed handling for the two residual 2020 Boursobank `2.00`-diff statements, then shift focus to HSBC outlier reduction.

### 2026-02-25 - codex
- Branch: `fix/parser-hardening-labanquepostale`
- Completed:
  - Investigated and fixed two LaBanquePostale 2025 reconciliation failures by hardening sign inference for `REMBOURSEMENT` credits and removing inline/continuation `Virement depuis La Banque Postale` hint noise from descriptions.
  - Added two targeted LBP regression tests covering remboursement credit sign handling and outgoing `VIREMENT INSTANTANE A` sign preservation when `virement depuis` text appears.
  - Renamed 12 LaBanquePostale 2025 CCP files in raw corpus to include `.pdf`, re-ran full pipeline, and validated that all 27 LBP CCP statements now reconcile as pass.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `FINANCE_STATEMENTS_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_PROCESSED_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed uv run python -m finance_tooling`: pass
- Open items:
  - Known low-confidence parser routing case remains for `Boursobank Marion Releve-compte-30-09-2022.pdf` selected as `revolut` at threshold.
- Next action:
  - Tighten parser routing tie-break logic to eliminate the remaining Boursobank-vs-Revolut low-confidence misclassification.

### 2026-02-25 - codex
- Branch: `fix/parser-hardening-labanquepostale`
- Completed:
  - Improved `LaBanquePostaleParser` to parse CCP statement opening/closing balances and emit checkable balance validations instead of always uncheckable.
  - Reworked LBP transaction extraction to line-based parsing with robust multiline continuation capture and description cleanup for OCR-prefixed artifacts.
  - Added fee-statement detection (`Relevé de frais`) in LBP parser to skip reconciliation records (`validation=None`) while still allowing parser routing.
  - Added regression tests for LBP balance validation pass, multiline continuation capture, fee-statement reconciliation exclusion, and completeness reconciliation counting without a validation record.
- Checks:
  - `uv run ruff check . --fix`: pass
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - LBP continuation filtering currently uses heuristic noise markers; if new statement layouts introduce additional headers/footers, marker tuning may be needed.
- Next action:
  - Re-run full real-corpus ingestion and review `completeness_report.json` to confirm LaBanquePostale CCP files move from uncheckable to pass while fee statements are excluded from reconciliation counts.

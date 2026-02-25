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
- Branch: `feature/automated-categorization`
- Completed:
  - Applied expanded categorization YAML rules and overrides (SEPA transfer
    patterns, TFL transport, telecom, council tax, memberships, childcare,
    and merchant-settlement handling for `MARS CHOCOLATE UK`).
  - Snapshotted nominal processed artifacts before rerun to
    `/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed_snapshots/2026-02-26-005537-categorization-pre`
    with checksum manifest.
  - Re-ran pipeline against nominal processed path with explicit YAML rule and
    override env vars.
  - Verified categorization improvement versus prior YAML benchmark:
    `categorized_count` `2989 -> 4213` (`+1224`) and
    `uncategorized_ratio` `0.7571 -> 0.6576` (`-0.0995`).
- Checks:
  - `FINANCE_STATEMENTS_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_PROCESSED_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed FINANCE_HSBC_CSV_PATH=/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw FINANCE_FX_AUTO_FETCH=false FINANCE_CATEGORY_RULES_PATH=/home/thomazo/dev/FinanceTooling/worktrees/automated-categorization/config/category_rules.yaml FINANCE_CATEGORY_OVERRIDES_PATH=/home/thomazo/dev/FinanceTooling/worktrees/automated-categorization/config/category_overrides.yaml uv run python -m finance_tooling`: pass
- Open items:
  - The pre-run nominal snapshot summary predates categorization metrics, so
    direct nominal pre/post category fields were unavailable.
- Next action:
  - Add a second-pass rule/override batch for new residual leaders (for
    example `virement de mars wrigley ...`, `exchanged to eur`, and `sky digital`).

### 2026-02-25 - codex
- Branch: `feature/automated-categorization`
- Completed:
  - Added YAML categorization config support (`.yaml`/`.yml`) while retaining
    JSON compatibility for rules and overrides.
  - Added schema aliases for human-friendly rule keys (`id`/`match`) mapped to
    classifier internals (`rule_id`/`match_type`).
  - Switched default categorization config paths to
    `<processed>/category_rules.yaml` and
    `<processed>/category_overrides.yaml`.
  - Added starter config templates under `config/`:
    `category_rules.yaml` and `category_overrides.yaml`.
  - Updated README examples to YAML and added tests for YAML rule/override
    parsing and schema alias behavior.
- Checks:
  - `uv sync --all-groups`: pass
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Override writeback workflow from reviewed/corrected exports is still not
    implemented.
- Next action:
  - Add a CLI command to upsert override entries from corrected category data.

### 2026-02-25 - codex
- Branch: `feature/automated-categorization`
- Completed:
  - Implemented rules-first automated categorization with configurable JSON
    rule and override stores, including robust description normalization and
    deterministic precedence (`override -> rule -> fallback`).
  - Extended normalized transaction schema and parquet columns with
    categorization metadata (`subcategory`, `category_confidence`,
    `category_source`, `category_rule_id`).
  - Integrated categorization diagnostics into `run_summary.json` including
    categorized/uncategorized counts and ratios, source breakdown, top
    uncategorized descriptions, and top matched rules.
  - Added settings/env support for
    `FINANCE_CATEGORY_RULES_PATH` and `FINANCE_CATEGORY_OVERRIDES_PATH`.
  - Added tests for override precedence and categorization diagnostics, and
    updated config/pipeline tests for new settings and summary fields.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Override persistence writeback workflow (capturing manual edits into
    `category_overrides.json`) is not yet implemented.
- Next action:
  - Add a small CLI utility to ingest corrected category exports and upsert
    override entries for future runs.

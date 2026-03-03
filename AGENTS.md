# AGENTS.md

## Mission

This repository exists to build reliable, Python-based tooling for monitoring
personal finances. The immediate focus is accurate bank statement ingestion and
normalization. The long-term goal is a maintainable pipeline for analysis,
categorization, and reporting.

## Current Workflow Focus

- Primary near-term objective: validate and scale the manual categorization
  review workflow across all 2026 statement months.
- Keep development focused on stable pipeline behavior, deterministic
  categorization outcomes, and low-friction review/import operations.
- Main workflow references:
  - `docs/categorization_review_workflow.md`
  - `docs/diagrams/categorization_review_hitl_flow.puml`
  - `docs/diagrams/categorization_review_import_guardrails.puml`
- Main troubleshooting checkpoints:
  - `run_summary.json`:
    `categorized_count`, `uncategorized_count`, `uncategorized_ratio`,
    `top_uncategorized_descriptions`, reconciliation counts.
  - `transactions_normalized.csv`:
    `category_source` distribution for targeted month windows.
  - review-import safety behavior:
    load-warning fail-safe, fallback-row filtering, backup creation.

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

## Metrics Log Protocol

- Maintain `docs/metrics_commit_log.csv` as a commit-to-commit, percentage-based
  trend log for parsing/categorization performance.
- Maintain `docs/metrics_commit_log_by_bank.csv` as a per-bank commit-to-commit
  percentage breakdown for categorization performance.
- After any commit that changes pipeline behavior or categorization data, update
  the metrics log using the latest `run_summary.json`:
  - `uv run python -m finance_tooling metrics-log-update --summary-path "$FINANCE_PROCESSED_PATH/run_summary.json" --log-path "docs/metrics_commit_log.csv" --log-path-by-bank "docs/metrics_commit_log_by_bank.csv"`
- If the log update is done after committing code, include it in a follow-up
  commit (or amend before push).
- Keep metrics high-level and stable across runs:
  - `parsing_success_pct`
  - `completeness_coverage_pct`
  - `reconciliation_pass_pct`
  - `categorized_pct`
  - `uncategorized_pct`
- Do not include source data paths or absolute filesystem paths in
  `docs/metrics_commit_log.csv`.

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

Prioritized recommendations for the next worker:

1. Completed: manual categorization review roundtrip (export -> review -> import)
- Implemented review-export/review-import command pair with default path
  resolution from `.env`/settings.
- Added import safety controls and guardrails:
  `--allow-load-warnings`, `--allow-non-fallback-import`, `--dry-run`,
  `--backup/--no-backup`, and `--backup-path`.
- Added documentation + diagrams for human-in-the-loop operations.

2. Next focus: categorize all 2026 statements to validate workflow end-to-end
- Run monthly or quarterly review cycles for Jan-Dec 2026 using:
  `review-export` -> manual review -> `review-import` -> `transform`.
- Track before/after month-scoped `uncategorized_count` and
  `uncategorized_ratio` from normalized outputs and `run_summary.json`.
- Keep override updates centralized in `config/category_overrides.yaml` and
  avoid ad-hoc local-only override files.
- Capture high-frequency residual fingerprints discovered during 2026 review
  and feed them into rule/override updates.

3. Apply second-pass residual rule/override batch for current uncategorized leaders
- Target the latest high-frequency residual fingerprints:
  - `visa rate`
  - `cr marschocolateuk cr marker`
  - `virement de mars wrigley confection ery france notprovided`
  - `exchanged to eur`
  - `ealing broadway`
  - `bp hmrc tfc`
  - `sncf`
  - `top up by`
  - `vis revolut revolut com`
  - `so curt park 29heronsforde`

4. Add run-to-run categorization delta reporting
- Compare current vs prior run counters (`categorized_count`,
  `uncategorized_count`, `uncategorized_ratio`) in a compact summary for faster
  iteration decisions.

5. Keep quality gates mandatory
- Continue enforcing:
  - `uv run ruff check .`
  - `uv run ruff format .`
  - `uv run ty check src/finance_tooling tests`
  - `uv run pytest`

Success target for the 2026 validation campaign:
- Process all 2026 months through the review workflow at least once and reduce
  month-scoped uncategorized ratios without worsening reconciliation metrics.


## Hand-Off Log

### 2026-03-03 - codex
- Branch: `chore/review-export-import-audit`
- Completed:
  - Refocused `AGENTS.md` away from stale HSBC-specific parser snapshot data and
    toward current high-level workflow development/troubleshooting guidance.
  - Updated `## Next Agent Recommendations` to mark review roundtrip work as
    completed and set 2026 statement categorization validation as the top active
    focus.
  - Kept hand-off retention compliant by preserving only the latest three
    entries.
- Checks:
  - `uv run ruff check .`: not run (docs-only update)
  - `uv run ty check src/finance_tooling tests`: not run (docs-only update)
  - `uv run pytest`: not run (docs-only update)
- Open items:
  - Convert 2026 categorization progress into periodic metrics-log updates once
    monthly/quarterly review cycles are executed.
- Next action:
  - Open PR for review-workflow hardening and AGENTS.md focus refresh.

### 2026-03-02 - codex
- Branch: `chore/review-export-import-audit`
- Completed:
  - Hardened categorization review import/export flow with safer defaults:
    `.env`-resolved default paths, fallback-row normalization, fallback-only
    import filtering by default, and clean CLI error handling for review
    subcommands.
  - Added review-import guardrails and controls:
    `--allow-load-warnings`, `--allow-non-fallback-import`, `--dry-run`,
    `--backup/--no-backup`, and `--backup-path`; import now aborts by default
    on override-load warnings.
  - Added backup and dry-run behavior in review import, plus detailed counters
    (`rows_skipped_non_fallback`, `rows_skipped_invalid`, backup metadata).
  - Expanded tests for review logic and CLI behavior, and added documentation
    with PlantUML sources and rendered SVG diagrams:
    `docs/categorization_review_workflow.md` and `docs/diagrams/*`.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Local `plantuml` binary is still optional; diagrams were rendered via
    containerized PlantUML for this change set.
- Next action:
  - Review/approve CLI safety defaults in real operations, then consider
    transaction-level override-key expansion as a separate feature.

### 2026-03-02 - codex
- Branch: `chore/cli-api-split`
- Completed:
  - Implemented CLI split commands `ingest`, `transform`, and `update`, with
    deprecated `run` alias routed to `update`.
  - Refactored orchestration into `run_ingest` / `run_transform` /
    `run_update`, added staged parquet IO module at
    `src/finance_tooling/workflow/staging.py`, and added ingest summary output.
  - Extended config with `FINANCE_STAGED_TRANSACTIONS_PATH` and updated tests
    for staging, pipeline split behavior, and CLI alias behavior.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Advanced planned flags (`--ingest-mode`, guardrails/snapshot controls,
    `--metrics-scope`) remain deferred and are not implemented in this branch.
- Next action:
  - Implement deferred advanced CLI/control-surface flags as a focused follow-up.

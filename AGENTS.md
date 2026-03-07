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
- For every work package that changes commands, workflow behavior, defaults, or
  user-facing setup/run steps, update `README.md` in the same package before
  opening a PR.

## Metrics Log Protocol

- Maintain `docs/metrics_commit_log.csv` as a commit-to-commit, percentage-based
  trend log for parsing/categorization performance.
- Maintain `docs/metrics_commit_log_by_bank.csv` as a per-bank commit-to-commit
  percentage breakdown for categorization performance.
- After any commit that changes pipeline behavior or categorization data, update
  the metrics log using the latest `run_summary.json`:
  - `uv run metrics-log-update --summary-path "$FINANCE_PROCESSED_PATH/run_summary.json" --log-path "docs/metrics_commit_log.csv" --log-path-by-bank "docs/metrics_commit_log_by_bank.csv"`
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

2. Completed: transaction-level overrides + project tags pipeline support
- Added config-backed transaction overrides:
  `config/transaction_overrides.yaml` (or
  `FINANCE_TRANSACTION_OVERRIDES_PATH`).
- Added config-backed project tagging rules/overrides:
  `config/project_overrides.yaml` (or `FINANCE_PROJECT_OVERRIDES_PATH`).
- Enrichment now applies precedence:
  category rule/override -> project rule/override -> transaction override.
- Transaction overrides can set `category`, `subcategory`, `project`,
  `project_tags` with `category_source`/`project_source=transaction_override`.

3. Next focus: categorize all 2026 statements to validate workflow end-to-end
- Run monthly or quarterly review cycles for Jan-Dec 2026 using:
  `review-export` -> manual review -> `review-import` -> `transform`.
- Track before/after month-scoped `uncategorized_count` and
  `uncategorized_ratio` from normalized outputs and `run_summary.json`.
- Keep override updates centralized in `config/category_overrides.yaml` and
  avoid ad-hoc local-only override files.
- Capture high-frequency residual fingerprints discovered during 2026 review
  and feed them into rule/override updates.

4. Apply second-pass residual rule/override batch for current uncategorized leaders
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

5. Add run-to-run categorization delta reporting
- Compare current vs prior run counters (`categorized_count`,
  `uncategorized_count`, `uncategorized_ratio`) in a compact summary for faster
  iteration decisions.

6. Keep quality gates mandatory
- Continue enforcing:
  - `uv run ruff check .`
  - `uv run ruff format .`
  - `uv run ty check src/finance_tooling tests`
  - `uv run pytest`

Success target for the 2026 validation campaign:
- Process all 2026 months through the review workflow at least once and reduce
  month-scoped uncategorized ratios without worsening reconciliation metrics.


## Hand-Off Log

### 2026-03-07 - codex
- Branch: `main`
- Completed:
  - Renamed legacy-named test files to align with the refactored module layout:
    `tests/test_workflow_stages.py`,
    `tests/test_review_workflow.py`, and
    `tests/test_command_entrypoints.py`.
  - Re-ran the full quality gates after the rename-only cleanup to confirm the
    test discovery and module move remain stable.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - None.
- Next action:
  - Package the command/module discoverability refactor and test cleanup in a
    single PR.

### 2026-03-07 - codex
- Branch: `main`
- Completed:
  - Refactored CLI entrypoints into command-named modules under
    `src/finance_tooling/commands/` for `ingest`, `transform`, `update`,
    `review_export`, `review_import`, and `metrics_log_update`.
  - Split workflow orchestration out of `src/finance_tooling/pipeline.py` into
    `src/finance_tooling/workflow/ingest_stage.py`,
    `src/finance_tooling/workflow/transform_stage.py`, and
    `src/finance_tooling/workflow/update_stage.py`.
  - Split review import/export logic out of
    `src/finance_tooling/categorization_review.py` into
    `src/finance_tooling/review_export.py`,
    `src/finance_tooling/review_import.py`, and
    `src/finance_tooling/review_common.py`.
  - Repointed console scripts in `pyproject.toml`, removed obsolete legacy
    entrypoint modules, updated tests, and added a README code map section.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Test filenames still reflect some legacy naming (`test_cli_aliases.py`,
    `test_pipeline.py`, `test_categorization_review.py`) even though the code
    under test has been moved.
- Next action:
  - Rename the remaining legacy-named test files to match the new command and
    stage module layout.

### 2026-03-06 - codex
- Branch: `fix/lbp-footer-carry-forward`
- Completed:
  - Stopped La Banque Postale footer/legal text from bleeding into transaction
    descriptions by introducing hard continuation boundaries in
    `src/finance_tooling/parsers/labanquepostale.py`.
  - Added manual category/subcategory carry-forward in
    `src/finance_tooling/workflow/category_carry_forward.py` so prior
    `override` and `transaction_override` labels survive parser description
    cleanup when transactions can be matched deterministically.
  - Updated persistence in `src/finance_tooling/store.py` to replace existing
    rows by incoming `source_file`, preventing stale prior IDs from lingering
    after parser-driven description changes.
  - Added summary diagnostics, README notes, regression tests, and reran the
    real `ingest` + `transform` workflow on production data.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `uv run ingest`: pass
  - `uv run transform`: pass
- Open items:
  - `manual_category_carry_forward_unmatched_count` is high because manual
    labels only exist for a minority of transactions; this is expected but
    worth monitoring as review coverage expands.
- Next action:
  - Review remaining duplicate staged transactions, especially longstanding
    Revolut duplicates, to decide whether they should be deduplicated earlier
    in ingest rather than at canonical persistence time.


- Open items:
  - `review-import` counters still report key-level updates even when no semantic
    value change occurs; this can remain confusing during manual review cycles.
- Next action:
  - Re-run `review-import` + `transform` on the latest edited review CSV and
    confirm last-month rows now flip from `fallback` to override-driven categories.

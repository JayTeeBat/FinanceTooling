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
    load-warning fail-safe, row-validation counters, backup creation.

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
  `--allow-load-warnings`, `--dry-run`, `--backup/--no-backup`, and
  `--backup-path`.
- Added documentation + diagrams for human-in-the-loop operations.

2. Completed: transaction-level overrides + project tags pipeline support
- Added config-backed transaction overrides:
  `config/transaction_overrides.yaml` (or
  `FINANCE_TRANSACTION_OVERRIDES_PATH`).
- Added config-backed project tagging rules/overrides:
  `config/project_overrides.yaml` (or `FINANCE_PROJECT_OVERRIDES_PATH`).
- Enrichment now applies precedence:
  category rule -> project rule/override -> transaction override.
- Transaction overrides can set `category`, `subcategory`, `project`,
  `project_tags` with `category_source`/`project_source=transaction_override`.

3. Next focus: categorize all 2026 statements to validate workflow end-to-end
- Run monthly or quarterly review cycles for Jan-Dec 2026 using:
  `review-export` -> manual review -> `review-import` -> `transform`.
- Track before/after month-scoped `uncategorized_count` and
  `uncategorized_ratio` from normalized outputs and `run_summary.json`.
- Keep reusable categorization logic centralized in `config/category_rules.yaml`
  and use `transaction_overrides.yaml` only for true transaction-level manual
  corrections.
- Capture high-frequency residual fingerprints discovered during 2026 review
  and feed them into rule updates.

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

### 2026-03-28 - codex
- Branch: `feature/noop-workflow-fast-path`
- Completed:
  - Added a true no-op fast path for `update`, `ingest`, and `transform` so unchanged raw files and unchanged staged/config/review inputs reuse existing outputs instead of re-running the pipeline.
  - Moved the no-op decision ahead of stage backups, so unchanged runs no longer create backup snapshots.
  - Added workflow-stage coverage for no-op ingest, no-op transform, and no-op update orchestration, and verified the end-to-end no-op update path on an isolated processed copy (~1.66s wall time with truthful `0 selected / 204 already committed` reporting).
- Checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/finance_tooling/workflow/ingest_stage.py src/finance_tooling/workflow/transform_stage.py src/finance_tooling/workflow/update_stage.py tests/test_workflow_stages.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ty check src/finance_tooling/workflow/ingest_stage.py src/finance_tooling/workflow/transform_stage.py src/finance_tooling/workflow/update_stage.py tests/test_workflow_stages.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_workflow_stages.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m finance_tooling.commands.metrics_log_update --summary-path "/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed/outputs/transform_run_summary.json" --log-path "docs/metrics_commit_log.csv" --log-path-by-bank "docs/metrics_commit_log_by_bank.csv"`: pass
- Open items:
  - Small targeted config/review changes still rerun the full transform stage when transform is required; only true no-op cases short-circuit today.
  - The no-op change detection still scans the raw corpus to build source inventory, so hashing/discovery remains a noticeable floor for large corpora.
- Next action:
  - Add targeted transform scopes so review-state-only and small override/config edits can run the minimal valid transform slice instead of the full transform pipeline.

### 2026-03-28 - codex
- Branch: `feature/progress-and-transform-performance`
- Completed:
  - Added stage-level `tqdm` progress bars for `ingest` and `transform`, while keeping the existing per-file ingest parsing progress bar intact.
  - Landed the transform hot-path performance pass: FX lookups now use a prebuilt currency/date index, source-file mtimes are memoized per unique file, transaction overrides use indexed candidate matching, and staged legacy identity backfill avoids unnecessary work for modern files.
  - Cleaned `pyproject.toml` so packaged script entrypoints match the current public CLI surface instead of publishing removed/internal commands.
- Checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/finance_tooling/fx.py src/finance_tooling/workflow/enrichment.py src/finance_tooling/transaction_overrides.py src/finance_tooling/workflow/staging.py src/finance_tooling/workflow/ingest_stage.py src/finance_tooling/workflow/transform_stage.py tests/test_fx.py tests/test_enrichment.py tests/test_staging.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ty check src/finance_tooling/fx.py src/finance_tooling/workflow/enrichment.py src/finance_tooling/transaction_overrides.py src/finance_tooling/workflow/staging.py src/finance_tooling/workflow/ingest_stage.py src/finance_tooling/workflow/transform_stage.py tests/test_fx.py tests/test_enrichment.py tests/test_staging.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_fx.py tests/test_enrichment.py tests/test_staging.py tests/test_workflow_stages.py`: pass
- Open items:
  - No-op incremental runs still rebuild outputs and backups even when no staged data or config changes require work.
  - `README.md` still mentions `uv run perf-check`; that utility remains internal and is no longer a packaged script entrypoint.
- Next action:
  - Implement a true no-op workflow fast path: skip ingest when no new files exist, skip transform when staged data and relevant config are unchanged, avoid unnecessary backups, and run only the minimal affected workflow slice for targeted changes such as small override updates.

### 2026-03-28 - codex
- Branch: `feature/api-surface-cleanup`
- Completed:
  - Removed one-off migration and planning commands from the public top-level CLI so the operator-facing API is limited to ingest/transform/update/review/workflow-status.
  - Deleted the category-override migration feature entirely, including its command wrapper, internal implementation, and direct tests.
  - Removed public README and workflow-doc references for `migrate-transaction-ids`, `migrate-category-overrides-to-rules`, `metrics-log-update`, and the `plan-*` commands while leaving the remaining internal maintenance modules available where intentionally retained.
- Checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_command_entrypoints.py tests/test_cli_dispatch.py tests/test_review_workflow.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/finance_tooling/__main__.py tests/test_command_entrypoints.py tests/test_cli_dispatch.py tests/test_review_workflow.py README.md docs/categorization_review_workflow.md`: pass
- Open items:
  - `metrics_log_update.py`, `migrate_transaction_ids.py`, and the `plan_*` command modules still exist as internal entrypoints/modules even though they are no longer part of the public top-level CLI.
- Next action:
  - Open and merge the API-surface cleanup PR, then decide whether the remaining internal maintenance/planning modules should stay as private utilities or move to a separate namespace/tool.

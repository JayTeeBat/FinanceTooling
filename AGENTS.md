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
- Branch: `feature/pipeline-output-layout`
- Completed:
  - Reconciled the ingest and transform output-layout work into a single flat processed contract with `outputs/` for user-facing transform artifacts and `state/` for pipeline state/monitoring artifacts.
  - Renamed default pipeline artifacts to stage-explicit names, including `ingest_staged_transactions.parquet`, `ingest_staged_batch_manifest.json`, `transform_transactions.parquet`, `transform_transactions.csv`, `transform_run_summary.json`, and `transform_source_registry.json`, while keeping legacy fallbacks where needed.
  - Updated `README.md`, review-export path resolution, reporting metadata, and metrics logs to match the new output layout and defaults.
- Checks:
  - `uv run ruff check tests/test_config.py tests/test_enrichment.py tests/test_ingest.py tests/test_perf_check.py tests/test_backup.py tests/test_cli_dispatch.py tests/test_workflow_stages.py tests/test_workflow_status.py src/finance_tooling/commands/common.py src/finance_tooling/perf_check.py src/finance_tooling/workflow_status.py`: pass
  - `uv run pytest -q tests/test_config.py tests/test_ingest.py tests/test_enrichment.py tests/test_workflow_status.py tests/test_perf_check.py tests/test_backup.py tests/test_cli_dispatch.py tests/test_workflow_stages.py tests/test_review_workflow.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ty check src/finance_tooling tests`: fail, but only on the pre-existing diagnostics in `tests/test_planning_dashboard.py`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run metrics-log-update --summary-path "/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed/run_summary.json" --log-path "docs/metrics_commit_log.csv" --log-path-by-bank "docs/metrics_commit_log_by_bank.csv"`: pass
- Open items:
  - `docs/categorization_review_workflow.md` and `docs/category_rules_review_workflow.md` still reference legacy processed-root filenames and should be updated in a follow-up docs pass.
  - Live processed artifacts in the vault still use the old root-level filenames until the updated pipeline is run against them.
- Next action:
  - Open and merge the pipeline-output-layout PR, then land the isolated transform performance improvements on top of the stabilized output contract.

### 2026-03-21 - codex
- Branch: `feature/reporting-dataframe-optimizations`
- Completed:
  - Vectorized dashboard transaction-row preparation so booking dates, category/project defaults, and transfer flags are normalized at the dataframe level before HTML rendering.
  - Reworked reporting/completeness to stay dataframe-native, avoiding full `Transaction` reconstruction for classification diagnostics, completeness coverage, legacy-ID collision export, and per-bank category metrics.
  - Added regression coverage for vectorized dashboard payload normalization and parity coverage for dataframe-based completeness reporting.
- Checks:
  - `uv run pytest tests/test_dashboard.py tests/test_completeness.py tests/test_workflow_stages.py tests/test_perf_check.py`: pass
  - `uv run ruff check src/finance_tooling/dashboard.py src/finance_tooling/completeness.py src/finance_tooling/workflow/reporting.py tests/test_dashboard.py tests/test_completeness.py`: pass
  - `uv run ty check src/finance_tooling tests`: fail, but only on pre-existing diagnostics in `tests/test_planning_dashboard.py`
- Open items:
  - No-op incremental `update`/`transform` runs still spend most of their remaining time on YAML loads, backups, CSV export, and dashboard refresh even when no files were selected.
- Next action:
  - Decide whether to implement a true no-op fast path for unchanged incremental runs, since that is now the biggest remaining end-user speed win.

### 2026-03-21 - codex
- Branch: `main`
- Completed:
  - Implemented Phase 1 incremental pipeline state with a committed `source_registry.json`, a self-describing `staged_batch_manifest.json`, and default incremental selection for `ingest` and `update`.
  - Made `transform` consume staged manifest metadata, regenerate reporting from the full merged canonical dataset after incremental runs, and update committed source state only after successful transforms.
  - Added guarded `--full-refresh` preflight/confirmation flows to `ingest` and `update`, expanded `workflow-status` with committed/drift/full-refresh-risk reporting, and documented the new default behavior in `README.md`.
- Checks:
  - `uv run ruff check src/finance_tooling/commands/common.py src/finance_tooling/commands/ingest.py src/finance_tooling/commands/update.py src/finance_tooling/commands/workflow_status.py src/finance_tooling/models.py src/finance_tooling/store.py src/finance_tooling/perf_check.py src/finance_tooling/workflow/incremental_state.py src/finance_tooling/workflow/ingest.py src/finance_tooling/workflow/ingest_stage.py src/finance_tooling/workflow/reporting.py src/finance_tooling/workflow/transform_stage.py src/finance_tooling/workflow/types.py src/finance_tooling/workflow/update_stage.py src/finance_tooling/workflow_status.py tests/test_cli_dispatch.py tests/test_workflow_stages.py tests/test_perf_check.py`: pass
  - `uv run pytest tests/test_cli_dispatch.py tests/test_command_entrypoints.py tests/test_workflow_status.py tests/test_workflow_stages.py tests/test_ingest.py tests/test_perf_check.py`: pass
  - `uv run ty check src/finance_tooling tests`: fail, but only on pre-existing diagnostics in `tests/test_planning_dashboard.py`
- Open items:
  - Phase 1 does not yet support targeted date-window reruns; modified/missing historical files and config drift are surfaced as stale conditions that still require a guarded full refresh.
- Next action:
  - Run `uv run workflow-status` and a real incremental `uv run update` on the live corpus, then validate that stale-state reporting and source-registry commits behave as expected before designing targeted reruns.

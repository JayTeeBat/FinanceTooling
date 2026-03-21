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

### 2026-03-21 - codex
- Branch: `main`
- Completed:
  - Added automatic stage-scoped pipeline backups for `ingest`, `transform`, and `update`, with timestamped run folders, backup manifests, and 10-run FIFO retention.
  - Expanded transform backups to snapshot the current master parquet plus category/project rule and override configs, while ingest snapshots the prior staged parquet only.
  - Surfaced backup run metadata in CLI output and stage summaries, and documented the automatic backup behavior in `README.md`.
- Checks:
  - `uv run pytest tests/test_backup.py tests/test_workflow_stages.py tests/test_cli_dispatch.py`: pass
  - `uv run ruff format src/finance_tooling/backup.py src/finance_tooling/models.py src/finance_tooling/workflow/types.py src/finance_tooling/workflow/ingest_stage.py src/finance_tooling/workflow/reporting.py src/finance_tooling/workflow/transform_stage.py src/finance_tooling/workflow/update_stage.py src/finance_tooling/commands/common.py tests/test_backup.py tests/test_workflow_stages.py tests/test_cli_dispatch.py`: pass
- Open items:
  - The automatic pipeline backup flow is stage-scoped, but non-pipeline commands such as `review-import` still use the older per-file backup helper and have not been unified onto run-folder manifests.
- Next action:
  - Run the broader lint/type/test gates and decide whether the remaining non-pipeline backup commands should migrate onto the same run-based backup subsystem.

### 2026-03-21 - codex
- Branch: `main`
- Completed:
  - Hardened raw source identity by introducing content-based `source_document_id`, duplicate raw-file detection/ignoring, and source-inventory persistence during ingest.
  - Added `workflow-status` plus `pipeline_state.json` to inspect raw, staged, and transformed pipeline state, including duplicate-source and staged-vs-transform drift warnings.
  - Extended transaction-id migration coverage so rebuilt corpora can remap old path-based manual-state IDs onto the new source-document-based identity scheme, and documented the new behavior in `README.md`.
- Checks:
  - `uv run pytest tests/test_store.py tests/test_staging.py tests/test_migrate_transaction_ids.py tests/test_source_inventory.py tests/test_workflow_status.py tests/test_perf_check.py tests/test_cli_dispatch.py tests/test_command_entrypoints.py tests/test_workflow_stages.py tests/test_ingest.py tests/test_review_state.py tests/test_transaction_overrides.py`: pass
  - `uv run ruff check src/finance_tooling/source_inventory.py src/finance_tooling/workflow_status.py src/finance_tooling/workflow/ingest.py src/finance_tooling/workflow/ingest_stage.py src/finance_tooling/workflow/staging.py src/finance_tooling/store.py src/finance_tooling/models.py src/finance_tooling/migrate_transaction_ids.py src/finance_tooling/commands/workflow_status.py src/finance_tooling/commands/common.py src/finance_tooling/commands/migrate_transaction_ids.py src/finance_tooling/__main__.py tests/test_store.py tests/test_staging.py tests/test_migrate_transaction_ids.py tests/test_source_inventory.py tests/test_workflow_status.py tests/test_perf_check.py tests/test_cli_dispatch.py tests/test_command_entrypoints.py tests/test_workflow_stages.py tests/test_ingest.py tests/test_review_state.py tests/test_transaction_overrides.py`: pass
- Open items:
  - The workflow-status healthcheck is intentionally read-only; it surfaces duplicate-path/raw-vs-processed drift but does not yet offer guided remediation steps or auto-repair.
- Next action:
  - Run the pipeline once on a real corpus, then validate `workflow-status` and `migrate-transaction-ids` against an actual processed dataset before broadening the hardening pass to stale-config and deletion drift detection.

### 2026-03-19 - codex
- Branch: `feature/planning-hypothesis-playground`
- Completed:
  - Added a shared backup helper and wired `transform` to snapshot `category_rules.yaml` into the sibling `backup/` folder before processing.
  - Updated `review-import` and `transform` backup handling so both `transaction_overrides.yaml` and `category_rules.yaml` retain only the latest 10 timestamped backups with deterministic FIFO pruning.
  - Added focused regression coverage for backup creation and retention behavior, and documented the new transform-time backup behavior in `README.md`.
- Checks:
  - `uv run pytest tests/test_review_workflow.py tests/test_workflow_stages.py tests/test_command_entrypoints.py tests/test_cli_dispatch.py`: pass
  - `uv run ruff check src/finance_tooling/backup.py src/finance_tooling/review_import.py src/finance_tooling/workflow/transform_stage.py tests/test_review_workflow.py tests/test_workflow_stages.py`: pass
- Open items:
  - `category_rules.yaml` backups now happen during `transform`, but there is still no equivalent automatic backup for other config artifacts such as `project_rules.yaml`.
- Next action:
  - Decide whether the same capped-backup policy should be extended to the other mutable config files used by the pipeline.

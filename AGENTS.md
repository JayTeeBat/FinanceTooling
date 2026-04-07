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
  - `docs/category_rules_review_workflow.md`
  - `docs/diagrams/categorization_review_hitl_flow.puml`
  - `docs/diagrams/categorization_review_import_guardrails.puml`
- Main troubleshooting checkpoints:
  - `outputs/transform_run_summary.json`:
    `categorized_count`, `uncategorized_count`, `uncategorized_ratio`,
    `top_uncategorized_descriptions`, reconciliation counts.
  - `outputs/transform_transactions.csv`:
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
- For taxonomy philosophy changes, bucket-boundary decisions, or important
  categorization edge-case rulings, update `docs/taxonomy_spec.md` in the same
  package so the design rationale stays current.
- Taxonomy-facing work should check `docs/taxonomy_spec.md`,
  `docs/taxonomy_guide.md`, and `docs/category_id_model.md` together before
  changing `config/category_rules.yaml` or taxonomy semantics.

## Metrics Log Protocol

- Maintain `docs/metrics_commit_log.csv` as a commit-to-commit, percentage-based
  trend log for parsing/categorization performance.
- Maintain `docs/metrics_commit_log_by_bank.csv` as a per-bank commit-to-commit
  percentage breakdown for categorization performance.
- After any commit that changes pipeline behavior or categorization data, update
  the metrics log using the latest `outputs/transform_run_summary.json`:
  - `uv run python -m finance_tooling.commands.metrics_log_update --summary-path "$FINANCE_PROCESSED_PATH/outputs/transform_run_summary.json" --log-path "docs/metrics_commit_log.csv" --log-path-by-bank "docs/metrics_commit_log_by_bank.csv"`
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

1. Current public workflow surface
- Operator-facing CLI remains:
  `ingest`, `transform`, `update`, `review-export`, `review-import`,
  `workflow-status`.
- Canonical transform outputs live under `processed/outputs/` with current names:
  `transform_transactions.csv`, `transform_transactions.parquet`,
  `transform_run_summary.json`, and `transform_dashboard.html`.
- Staged ingest state lives under `processed/state/`, especially
  `ingest_staged_transactions.parquet` and
  `ingest_staged_batch_manifest.json`.

2. Next focus: validate the 2026 categorization workflow end-to-end
- Run monthly or quarterly review cycles for Jan-Dec 2026 using:
  `review-export` -> manual review -> `review-import` -> `transform`.
- Track before/after month-scoped `uncategorized_count` and
  `uncategorized_ratio` from `outputs/transform_transactions.csv` and
  `outputs/transform_run_summary.json`.
- Keep reusable categorization logic centralized in `config/category_rules.yaml`
  and use `transaction_overrides.yaml` only for true transaction-level manual
  corrections.
- Capture high-frequency residual fingerprints discovered during 2026 review
  and feed them into rule updates.

3. Improve transform iteration speed for targeted review/config changes
- True no-op fast paths already exist for unchanged runs.
- Remaining gap: small review-state or config edits still require a full
  transform when any transform work is needed.
- Prefer targeted transform scopes or similarly minimal recomputation before
  introducing more workflow surface area.

4. Expand the planning/reporting surface only when it serves the core pipeline
- The repo now also includes planning/budgeting/reporting modules and a
  `planning/household_finance_360/` workspace.
- Keep additions to that surface intentional and secondary to the ingestion +
  categorization workflow unless the task explicitly targets planning features.

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

### 2026-04-07 - codex
- Branch: `codex/example-config-starters`
- Completed:
  - Reframed the repo `category_rules.yaml` and `transaction_overrides.yaml` copies as generic starter examples instead of personal production config, including a leaner sample taxonomy/rule set.
  - Updated the README language to make the starter-config intent explicit and added focused tests for generic example-rule classification plus deprecated category-id migration.
- Checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check tests/test_category_id_migrate_live.py tests/test_classify.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check tests/test_category_id_migrate_live.py tests/test_classify.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_category_id_migrate_live.py tests/test_classify.py`: pass
- Open items:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` still fails on the pre-existing `tests/test_cli_dispatch.py::test_review_import_runs_transform_by_default` fixture/setup mismatch outside this PR's scope.
- Next action:
  - Publish the starter-config cleanup as a draft PR and decide whether to fix the unrelated full-suite `review-import` test in a separate follow-up.

### 2026-04-05 - codex
- Branch: `main`
- Completed:
  - Split finance reporting from operational diagnostics so `transform_run_summary.json` now stays finance-focused while `workflow_pipeline_state.json` exposes parser, reconciliation, HSBC, and stale-state diagnostics.
  - Added a shared YoY cashflow aggregation layer and surfaced the resulting annual and YTD cashflow metrics in `transform_dashboard.html` and the finance summary payload.
  - Updated metrics/perf consumers, README output-contract docs, and focused tests to match the new boundary.
- Checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/finance_tooling/cashflow.py src/finance_tooling/dashboard.py src/finance_tooling/household_healthcheck.py src/finance_tooling/metrics_log.py src/finance_tooling/perf_check.py src/finance_tooling/workflow/reporting.py src/finance_tooling/workflow/transform_stage.py src/finance_tooling/workflow/types.py src/finance_tooling/workflow_status.py tests/test_dashboard.py tests/test_perf_check.py tests/test_workflow_stages.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_dashboard.py tests/test_metrics_log.py tests/test_perf_check.py tests/test_workflow_status.py tests/test_workflow_stages.py`: pass
- Open items:
  - `household_healthcheck.html` remains as a secondary compatibility dashboard and still overlaps somewhat with the primary finance dashboard.
- Next action:
  - Decide whether to keep `household_healthcheck.html` long-term or formally deprecate it after the finance dashboard settles.

### 2026-04-03 - codex
- Branch: `codex/fix-rule-drift-monitoring`
- Completed:
  - Narrowed full-refresh drift monitoring so only `category_rules.yaml` and `project_rules.yaml` count as stale-history config drift, while override files still participate in transform freshness.
  - Added compatibility logic so registries written under the old wider fingerprint scheme reconcile against the saved full-refresh config backup instead of falsely flagging override churn as rule drift.
- Checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/finance_tooling/workflow/incremental_state.py src/finance_tooling/workflow_status.py src/finance_tooling/workflow/ingest.py tests/test_workflow_status.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_workflow_status.py`: pass
- Open items:
  - Refreshing the persisted `workflow_pipeline_state.json` still depends on the processed mount being writable to `workflow-status`.
- Next action:
  - Publish the focused drift-monitoring fix as a draft PR and refresh the saved workflow-status snapshot once the processed mount is writable.

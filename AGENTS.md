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

### 2026-04-03 - codex
- Branch: `codex/clean-command-output`
- Completed:
  - Changed `review-import` so successful non-dry-run imports run `transform` by default, with `--no-run-transform` as the opt-out and `--dry-run` remaining preview-only.
  - Updated the README, categorization review workflow doc, and CLI coverage to match the new default behavior.
- Checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/finance_tooling/commands/review_import.py tests/test_cli_dispatch.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_cli_dispatch.py`: pass
- Open items:
  - The broader command-output cleanup on this branch is still waiting to be packaged into a focused PR.
- Next action:
  - Package the command-output cleanup, including the new `review-import` default, into a focused PR.

### 2026-04-03 - codex
- Branch: `main`
- Completed:
  - Tightened the public workflow contract around the CLI, making `update`, `review-export`, `review-import`, and `workflow-status` the clearly recommended user path while marking `ingest` and `transform` as advanced stage-level commands.
  - Aligned config comments, README/docs, and tests around the `processed/outputs/` vs `processed/state/` split, including documenting `transform_transactions.json` as compatibility-only and fixing the workflow-status snapshot path to `state/workflow_pipeline_state.json`.
- Checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/finance_tooling/config.py src/finance_tooling/__main__.py src/finance_tooling/commands/common.py src/finance_tooling/commands/ingest.py src/finance_tooling/commands/transform.py src/finance_tooling/commands/update.py src/finance_tooling/commands/workflow_status.py tests/test_config.py tests/test_cli_dispatch.py tests/test_workflow_status.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_config.py tests/test_cli_dispatch.py tests/test_workflow_status.py`: pass
- Open items:
  - The env-var surface is still broader than the minimal public contract; low-level per-file overrides and cache toggles remain supported but are intentionally de-emphasized rather than removed.
- Next action:
  - Decide whether to follow this contract pass with a smaller compatibility/deprecation pass for low-level env/path overrides and optional JSON export behavior.

### 2026-03-29 - codex
- Branch: `codex/fix-hypothesis-dashboard-calculations`
- Completed:
  - Corrected the planning hypothesis dashboard baseline math so retirement timing uses the planner's age-based horizon, house timing uses the exact target-date horizon, and education uses per-child target/return assumptions instead of flattening to one shared input.
  - Added a regression test that compares the dashboard baseline calculations against `build_planning_summary`, and regenerated `planning/household_finance_360/15_hypothesis_playground.html`.
- Checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/finance_tooling/planning_dashboard.py tests/test_planning_dashboard.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ty check src/finance_tooling/planning_dashboard.py tests/test_planning_dashboard.py`: pass
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_planning_dashboard.py tests/test_planning.py tests/test_planning_doe.py`: pass
- Open items:
  - The dashboard still has its own interactive browser-side projection layer for net-worth and housing visuals; if more planning logic moves into the canonical engine, keep the static page in sync.
- Next action:
  - Review the draft PR and decide whether the dashboard should keep per-child education controls or collapse them into a different UX with explicit approximation.

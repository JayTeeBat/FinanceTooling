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

## Hand-Off Log

### 2026-05-02 - codex
- Branch: `codex/stage-aligned-planning`
- Completed:
  - Removed the transfer and excluded toggle checkboxes from the planning dashboard and replaced them with compact volume notes below the cashflow and economic charts.
  - Added summary payload fields for transfer volume and excluded net volume so the dashboard can show those notes without extra UI controls.
  - Kept the pie chart balances and raw-sign KPI model intact while updating the contract tests to cover the new display behavior.
- Checks:
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run ruff format src/finance_tooling/workflow/planning_stage.py tests/test_planning_stage_contract.py`: pass
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run ruff check src/finance_tooling/workflow/planning_stage.py tests/test_planning_stage_contract.py`: pass
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run pytest -q tests/test_planning_stage_contract.py tests/test_planning_dashboard.py tests/test_budgeting.py`: pass
- Open items:
  - None.
- Next action:
  - Keep the PR wording aligned if the dashboard notes or balance labels need one more pass.

### 2026-05-02 - codex
- Branch: `codex/stage-aligned-planning`
- Completed:
  - Added `surface_volume_notes` to the planning dashboard payload so the transfer and excluded volume annotations now render from real data instead of falling back to zero.
  - Kept the compact chart notes under the cashflow and economic pies while preserving the removed toggle behavior.
  - Added a regression assertion that the dashboard HTML embeds the new payload key.
- Checks:
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run ruff format src/finance_tooling/workflow/planning_stage.py tests/test_planning_stage_contract.py`: pass
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run ruff check src/finance_tooling/workflow/planning_stage.py tests/test_planning_stage_contract.py`: pass
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run pytest -q tests/test_planning_stage_contract.py tests/test_planning_dashboard.py tests/test_budgeting.py`: pass
- Open items:
  - None.
- Next action:
  - Regenerate the planning artifact so the live HTML picks up the payload field.

### 2026-05-02 - codex
- Branch: `codex/stage-aligned-planning`
- Completed:
  - Changed the semantic defaults so any unresolved spend row now falls back to `variable_expense` instead of the generic `expense` role.
  - Updated the reporting and workflow normalization layers to keep the new default consistent across planning and transform outputs.
  - Added a planning regression check so the economic-role summary no longer retains an `expense` bucket in the dashboard payload.
- Checks:
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run ruff format src/finance_tooling/core/semantic_resolution.py src/finance_tooling/reporting/cashflow.py src/finance_tooling/workflow/reporting.py tests/test_cashflow.py tests/test_planning_stage_contract.py`: pass
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run ruff check src/finance_tooling/core/semantic_resolution.py src/finance_tooling/reporting/cashflow.py src/finance_tooling/workflow/reporting.py tests/test_cashflow.py tests/test_planning_stage_contract.py`: pass
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run pytest -q tests/test_cashflow.py tests/test_planning_stage_contract.py tests/test_planning_dashboard.py tests/test_budgeting.py`: pass
- Open items:
  - None.
- Next action:
  - Keep an eye on any legacy review/export views that still intentionally label rows as `expense`.

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
- Canonical outputs live under `processed/ingest/`, `processed/transform/`,
  and `processed/planning/` with the current workflow artifacts.
- Legacy read fallbacks for `processed/state/` and `processed/outputs/` remain
  supported temporarily but should be treated as compatibility paths only.
- Canonical transform outputs live under `processed/transform/` with current names:
  `transform_transactions.csv`, `transform_transactions.parquet`,
  `transform_run_summary.json`, and `transform_dashboard.html`.
- Staged ingest state lives under `processed/ingest/`, especially
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

### 2026-05-02 - codex
- Branch: `codex/stage-aligned-planning`
- Completed:
  - Migrated the public cashflow semantic to `cashflow_role`, kept `economic_role` transfer-free, and preserved spend-side `decision_role` classification for refund-like reversals.
  - Updated the live taxonomy corpus under `/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/config/` to match the new sequential semantic model.
  - Fixed dashboard warning logic so cashflow and internal-transfer diagnostics follow the new role model while still surfacing useful exclusions.
  - Updated the PR body to call out the `cashflow_type -> cashflow_role` rename and the live taxonomy migration explicitly.
- Checks:
  - `rtk uv run ruff check src/finance_tooling/reporting/dashboard.py src/finance_tooling/reporting/cashflow.py src/finance_tooling/core/semantic_resolution.py src/finance_tooling/categorization/classify.py src/finance_tooling/planning/budgeting.py src/finance_tooling/workflow/reporting.py tests/test_dashboard.py tests/test_cashflow.py tests/test_classify.py tests/test_budgeting.py tests/test_workflow_stages.py tests/test_planning_stage_contract.py tests/test_planning_dashboard.py tests/test_category_normalization.py`: pass
  - `rtk uv run ruff format src/finance_tooling/categorization/classify.py src/finance_tooling/core/models.py src/finance_tooling/core/semantic_resolution.py src/finance_tooling/core/semantics.py src/finance_tooling/core/store.py src/finance_tooling/planning/budgeting.py src/finance_tooling/reporting/cashflow.py src/finance_tooling/reporting/dashboard.py src/finance_tooling/workflow/planning_stage.py src/finance_tooling/workflow/reporting.py tests/test_budgeting.py tests/test_cashflow.py tests/test_category_normalization.py tests/test_classify.py tests/test_dashboard.py tests/test_planning_stage_contract.py tests/test_workflow_stages.py`: pass
  - `rtk uv run pytest -q tests/test_dashboard.py tests/test_cashflow.py tests/test_classify.py tests/test_budgeting.py tests/test_workflow_stages.py tests/test_planning_stage_contract.py tests/test_planning_dashboard.py tests/test_category_normalization.py`: pass
- Open items:
  - None.
- Next action:
  - Keep the PR focused on the semantic migration and merge once review is complete.

### 2026-05-02 - codex
- Branch: `codex/stage-aligned-planning`
- Completed:
  - Documented the transform layering contract so `cashflow_type`, `economic_role`, and `decision_role` are resolved sequentially.
  - Renamed the canonical decision-role exclusion bucket to `not_applicable` across transform, planning, taxonomy defaults, and planning dashboard rendering.
  - Added transfer-subtype planning bucket inference that no longer depends on `decision_role`, plus regression coverage for planning and dashboard output.
  - Reworked the planning dashboard UI so the charts render in precedence order, stay horizontally aligned on desktop, expose visibility toggles for transfer and not_applicable buckets, normalize bucket labels to lower-case plain text, and show cashflow/economic balances.
- Checks:
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run ruff check src/finance_tooling/workflow/planning_stage.py tests/test_planning_stage_contract.py`: pass
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run ty check src/finance_tooling tests`: pass
  - `env UV_CACHE_DIR=/tmp/uv-cache rtk uv run pytest -q tests/test_cashflow.py tests/test_budgeting.py tests/test_classify.py tests/test_planning_stage_contract.py tests/test_planning_dashboard.py`: pass
- Open items:
  - None.
- Next action:
  - Keep the PR aligned with any follow-up semantic renames or dashboard wording changes.

### 2026-05-02 - codex
- Branch: `codex/docs-canonical-layout`
- Completed:
  - Updated the public docs to present `processed/ingest/`, `processed/transform/`, and `processed/planning/` as the canonical layout.
  - Documented legacy read fallbacks for `processed/state/` and `processed/outputs/`, plus the new default `update -> planning` behavior with `--skip-planning`.
  - Added a same-day handoff entry for the doc-only workflow update.
- Checks:
  - Not run: documentation-only change.
- Open items:
  - None.
- Next action:
  - Merge the doc changes and keep the workflow docs aligned if CLI behavior lands next.

@RTK.md

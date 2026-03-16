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

### 2026-03-16 - codex
- Branch: `feature/household-finance-planning`
- Completed:
  - Added a `plan-savings-doe` CLI command and supporting planning logic to run scenario sweeps across retirement age, pension, retirement spending, kids targets, house project size, inflation, and expected returns.
  - Populated the planning baseline inputs with the household figures discussed, generated baseline sizing output, and produced ranked DOE scenario results in the planning workspace.
  - Updated planning docs to cover the DOE workflow and added focused regression tests for the new command and scenario-grid builder.
- Checks:
  - `uv run pytest tests/test_planning.py tests/test_planning_doe.py tests/test_plan_savings_cli.py tests/test_plan_savings_doe_cli.py tests/test_command_entrypoints.py tests/test_cli_dispatch.py`: pass
  - `uv run ruff check src/finance_tooling/planning.py src/finance_tooling/commands/plan_savings.py src/finance_tooling/commands/plan_savings_doe.py tests/test_planning.py tests/test_planning_doe.py tests/test_plan_savings_cli.py tests/test_plan_savings_doe_cli.py tests/test_command_entrypoints.py`: pass
  - `uv run ty check src/finance_tooling tests`: not run
- Open items:
  - The planning workspace still relies on CSV/JSON outputs rather than a dedicated planning dashboard or automatic shortlist generation.
- Next action:
  - Review the DOE results and narrow them to a small set of realistic household planning scenarios for decision-making.

### 2026-03-15 - codex
- Branch: `feature/household-finance-planning`
- Completed:
  - Added a separate `planning/household_finance_360/` workspace with starter templates for household profile, account inventory, monthly budget tracking, net worth snapshots, goal planning, investment policy, monitoring, and annual reviews.
  - Added a `plan-savings` CLI calculator plus planning input/output files so retirement, education, and house-project assumptions can be converted into required monthly savings by goal, including inflation-aware target sizing.
  - Documented a practical monthly / quarterly / annual workflow for 360-degree household financial planning and linked the new workspace from `README.md`.
- Checks:
  - `documentation/template review`: pass
  - `uv run pytest tests/test_planning.py tests/test_plan_savings_cli.py tests/test_command_entrypoints.py tests/test_cli_dispatch.py`: pass
  - `uv run ruff check src/finance_tooling/planning.py src/finance_tooling/commands/plan_savings.py tests/test_planning.py tests/test_plan_savings_cli.py tests/test_command_entrypoints.py`: pass
  - `uv run ty check src/finance_tooling tests`: not run
- Open items:
  - The planning calculator currently produces JSON output and console summaries, but it does not yet auto-update the scenario matrix or generate a dedicated planning dashboard.
- Next action:
  - Populate the planning inputs with your real household assumptions and run `uv run plan-savings` to establish a first baseline monthly savings target.

### 2026-03-11 - codex
- Branch: `fix/rule-pattern-normalization-review-column`
- Completed:
  - Normalized `contains` and `exact` category-rule patterns on load so rules written from human-readable review descriptions match the same normalized transaction text used by the classifier.
  - Renamed the review workbook helper column from `fingerprint` to `normalized_description` and updated the review docs/README wording accordingly.
  - Added focused regression tests for normalized rule-pattern loading and the updated review export column set.
- Checks:
  - `uv run pytest tests/test_classify.py tests/test_review_workflow.py`: pass
  - `uv run ruff check src/finance_tooling/classify.py src/finance_tooling/review_common.py tests/test_classify.py tests/test_review_workflow.py`: pass
- Open items:
  - Existing live rule/config files authored before this change will still work, but they can now be written directly from review descriptions without having to think about normalization details.
- Next action:
  - Merge the rule-pattern normalization PR so future review-driven rule authoring is less error-prone.

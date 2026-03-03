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

### 2026-03-03 - codex
- Branch: `chore/review-export-import-audit`
- Completed:
  - Implemented review CSV v2 semantics in
    `src/finance_tooling/categorization_review.py` with independent category and
    project handling columns: `override_level`, `project_tags`,
    `existing_project_tags`.
  - Added import routing so category edits can upsert either category overrides
    or transaction overrides, while project tags always upsert to
    transaction-level overrides.
  - Added/validated transaction-override upsert + write helpers in
    `src/finance_tooling/transaction_overrides.py` and wired CLI
    `review-import` defaults to both override paths (including
    `--transaction-overrides-path`) in `src/finance_tooling/__main__.py`.
  - Expanded tests for v2 review behavior and dual-store CLI import flows.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - End-to-end manual review run against full 2026 months is still pending on
    real statement data.
  - `plantuml` is not available in PATH; `.puml` sources were updated but SVG
    diagrams were not regenerated in this session.
- Next action:
  - Execute `review-export` -> manual edits -> `review-import` on the latest
    2026 corpus and validate resulting override files and categorized deltas.

### 2026-03-03 - codex
- Branch: `feature/offline-interactive-dashboard`
- Completed:
  - Implemented interactive self-contained dashboard rendering in
    `src/finance_tooling/dashboard.py` with client-side date/category/project
    filters, YoY spending view, and budget-vs-actual tables/charts.
  - Added project assignment and budget modules
    (`src/finance_tooling/projecting.py`, `src/finance_tooling/budgeting.py`)
    with YAML/JSON loading, validation, and deterministic assignment logic.
  - Extended settings/reporting contracts for project/budget config paths,
    added starter configs (`config/project_rules.yaml`,
    `config/budget_targets.yaml`), and added regression coverage for dashboard,
    projecting, budgeting, and config/main defaults.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Dashboard is read-only in v1; no in-browser editing/export flow for budgets
    or project assignments yet.
- Next action:
  - Run a full real-data `update` pipeline and validate dashboard UX/performance
    on production-sized outputs.

### 2026-03-03 - codex
- Branch: `chore/review-export-import-audit`
- Completed:
  - Added transaction-level override support with YAML/JSON loading and apply
    logic (`src/finance_tooling/transaction_overrides.py`) and default config
    template (`config/transaction_overrides.yaml`).
  - Added project-tag assignment support with rules + overrides
    (`src/finance_tooling/projecting.py`) and default config template
    (`config/project_overrides.yaml`).
  - Integrated project/tag + transaction override application into enrichment,
    added summary payload path fields, and persisted project fields in staged
    and canonical outputs.
  - Added tests for enrichment, projecting, and transaction overrides; updated
    config/pipeline/staging tests for new settings and project fields.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - New transaction/project override configs are implemented but not yet run on
    a full 2026 statement review pass.
- Next action:
  - Execute Jan-Feb 2026 categorization pass using new project tags and
    transaction overrides, then inspect `run_summary.json` deltas.

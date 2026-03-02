# AGENTS.md

## Mission

This repository exists to build reliable, Python-based tooling for monitoring
personal finances. The immediate focus is accurate bank statement ingestion and
normalization. The long-term goal is a maintainable pipeline for analysis,
categorization, and reporting.

## Parser Performance Snapshot

### HSBC parser (latest full-corpus run: 2026-02-25)

- HSBC statement reconciliation failures: `20` (latest known count).
- Largest residual outlier: `2017-08` with `|diff|=754.70`.
- Statements missing parsed period windows: `1`.
- Recent trajectory:
  - Prior runs were `69/71` (PDF-only processed run) and `30/71`.
  - Current run is `20/71` failed/checkable for HSBC validations.
  - Overall statement reconciliation is `22/193` failed/checkable.
- Immediate hardening targets: high-diff months (`2017-08`, `2016-12`) and
  residual mid-diff months (`2019-05`, `2019-06`, `2019-07`).
- Debug triage reference (2026-02-28):
  - `docs/hsbc_reconciliation_root_cause_triage_2026-02-28.md`
  - Includes failed-month root-cause buckets and occurrence counts from
    `processed_run_20260228-012931`.
  - `docs/hsbc_failed_statement_diagnostics_2026-02-28_fxfix.md`
  - Includes post-fix metric evolution (`/tmp/fxfix_20260228-022508`) and
    detailed divergence maps for remaining 2019-05/2019-06/2019-07 fails.

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

1. Implement manual categorization review roundtrip (export -> review -> import)
- Add a review export focused on fallback rows (`category_source == "fallback"`)
  from normalized outputs.
- Keep review columns explicit: `description`, `bank`, `account_label`,
  `category`, `subcategory`, `category_source`.
- Add import/upsert flow into `config/category_overrides.yaml`.
- Upsert key policy: normalized fingerprint + bank by default, with optional
  account-label scope.
- Conflict policy: update matching override; insert when no match.

2. Apply second-pass residual rule/override batch for current uncategorized leaders
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

3. Add run-to-run categorization delta reporting
- Compare current vs prior run counters (`categorized_count`,
  `uncategorized_count`, `uncategorized_ratio`) in a compact summary for faster
  iteration decisions.

4. Keep quality gates mandatory
- Continue enforcing:
  - `uv run ruff check .`
  - `uv run ruff format .`
  - `uv run ty check src/finance_tooling tests`
  - `uv run pytest`

Success target for the next categorization pass:
- Reduce `uncategorized_ratio` from `0.6617` by at least `0.05` absolute,
  without worsening reconciliation metrics.


## Hand-Off Log

### 2026-03-02 - codex
- Branch: `chore/review-export-import-audit`
- Completed:
  - Hardened categorization review import/export flow with safer defaults:
    `.env`-resolved default paths, fallback-row normalization, fallback-only
    import filtering by default, and clean CLI error handling for review
    subcommands.
  - Added review-import guardrails and controls:
    `--allow-load-warnings`, `--allow-non-fallback-import`, `--dry-run`,
    `--backup/--no-backup`, and `--backup-path`; import now aborts by default
    on override-load warnings.
  - Added backup and dry-run behavior in review import, plus detailed counters
    (`rows_skipped_non_fallback`, `rows_skipped_invalid`, backup metadata).
  - Expanded tests for review logic and CLI behavior, and added documentation
    with PlantUML sources and rendered SVG diagrams:
    `docs/categorization_review_workflow.md` and `docs/diagrams/*`.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Local `plantuml` binary is still optional; diagrams were rendered via
    containerized PlantUML for this change set.
- Next action:
  - Review/approve CLI safety defaults in real operations, then consider
    transaction-level override-key expansion as a separate feature.

### 2026-03-02 - codex
- Branch: `chore/cli-api-split`
- Completed:
  - Implemented CLI split commands `ingest`, `transform`, and `update`, with
    deprecated `run` alias routed to `update`.
  - Refactored orchestration into `run_ingest` / `run_transform` /
    `run_update`, added staged parquet IO module at
    `src/finance_tooling/workflow/staging.py`, and added ingest summary output.
  - Extended config with `FINANCE_STAGED_TRANSACTIONS_PATH` and updated tests
    for staging, pipeline split behavior, and CLI alias behavior.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Advanced planned flags (`--ingest-mode`, guardrails/snapshot controls,
    `--metrics-scope`) remain deferred and are not implemented in this branch.
- Next action:
  - Implement deferred advanced CLI/control-surface flags as a focused follow-up.

### 2026-03-02 - codex
- Branch: `fix/hsbc-pdf-failures-triage`
- Completed:
  - Removed HSBC CSV integration from runtime config and ingestion path
    (`FINANCE_HSBC_CSV_PATH` and CSV importer hook removed).
  - Simplified HSBC merge stage to PDF-only validation/diagnostics while
    preserving summary metric compatibility keys (CSV counters stay `0`).
  - Removed HSBC CSV importer module and CSV-specific tests; updated pipeline,
    perf-check, ingest, config, and docs for PDF-only operation.
  - Validated full corpus run in
    `/tmp/finance_pdf_only_phase2_20260302-222228` with
    `hsbc_selection_policy=pdf_only`, `hsbc_csv_files_scanned=0`, and remaining
    HSBC fail still limited to `2019-11-27` (`-0.03`).
- Checks:
  - `uv run ruff format .`: pass
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `FINANCE_STATEMENTS_PATH=... FINANCE_PROCESSED_PATH=/tmp/finance_pdf_only_phase2_20260302-222228 FINANCE_FX_AUTO_FETCH=false uv run python -m finance_tooling`: pass
- Open items:
  - Strict reconciliation tolerance (`0.01`) still leaves known HSBC residual:
    `2019-11-27` (`-0.03`).
- Next action:
  - Decide policy for near-zero residual handling (`keep strict 0.01` vs scoped
    tolerance exception) for the final HSBC edge case.

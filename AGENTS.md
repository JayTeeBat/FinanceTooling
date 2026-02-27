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

### 2026-02-26 - codex
- Branch: `feature/automated-categorization`
- Completed:
  - Executed iterative categorization waves with user-guided decisions using
    the new review/export import-ready override workflow.
  - Added targeted override batches for major residual fingerprints across
    HSBC, Revolut, Boursobank, and LaBanquePostale, including
    `virement pour -> Transfers/Bank Transfer`.
  - Used 2022 Excel workbook context where available to disambiguate
    categorization decisions (for example `DVLA-RF07HXX`, `LBEALING`).
  - Added explicit review marker comment for
    `virinstmrthomazojoummethom` in `config/category_overrides.yaml`.
- Checks:
  - `set -a; . /home/thomazo/dev/FinanceTooling/.env; set +a; FINANCE_CATEGORY_OVERRIDES_PATH=... FINANCE_CATEGORY_RULES_PATH=... uv run python -m finance_tooling run`: pass
- Open items:
  - Remaining recurring uncategorized leaders include cheque rows (`cheque n`,
    `cheque n cid 176`) and unresolved transfer/person patterns (`dd nest`,
    `virinsttheryfrederic`).
  - Run-to-run categorization delta reporting in summary output is still not
    implemented.
- Next action:
  - Continue residual fingerprint triage from current top-uncategorized list,
    prioritizing stable recurring merchants with clear taxonomy fit.

### 2026-02-26 - codex
- Branch: `feature/automated-categorization`
- Completed:
  - Implemented manual categorization review roundtrip CLI in
    `python -m finance_tooling` with `review-export` and `review-import`
    subcommands.
  - Added fallback-focused review export from normalized outputs with explicit
    review columns: `description`, `bank`, `account_label`, `category`,
    `subcategory`, `category_source`.
  - Added review import/upsert flow to override config with default key
    `fingerprint + bank` and optional `--include-account-label-scope`.
  - Added tests for fallback export and override upsert/update behavior, and
    documented roundtrip usage in `README.md`.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Second-pass residual rule/override batch for uncategorized leaders is still
    pending.
  - Run-to-run categorization delta reporting is not yet implemented.
- Next action:
  - Implement run-to-run categorization delta reporting in summary output.

### 2026-02-26 - codex
- Branch: `feature/automated-categorization`
- Completed:
  - Updated worktree `AGENTS.md` with a decision-complete next-worker plan for
    manual categorization review writeback and residual rule targeting.
  - Added explicit residual fingerprint priority list and measurable success
    target for the next categorization pass.
  - Added recommendation details for override upsert scope/conflict handling.
- Checks:
  - `manual AGENTS.md update only`: not run
- Open items:
  - Manual review export/import CLI for override upsert is still not
    implemented.
  - Residual second-pass rule batch has not been applied yet.
- Next action:
  - Implement CLI workflow to export fallback categorization candidates and
    import reviewed results into `config/category_overrides.yaml`.

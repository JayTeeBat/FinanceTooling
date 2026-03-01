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

### 2026-03-01 - codex
- Branch: `chore/review-import-defaults`
- Completed:
  - Created dedicated worktree `worktrees/chore-review-import-defaults` on new
    branch `chore/review-import-defaults` for manual categorization default-path
    wiring work.
  - Updated `review-import` CLI defaults in `src/finance_tooling/__main__.py`
    so `--review-path` can default from `FINANCE_REVIEW_IMPORT_PATH` and
    `--overrides-path` can default from `FINANCE_CATEGORY_OVERRIDES_PATH`
    (with fallback behavior when env is not set).
  - Added local `.env` defaults in the worktree for processed path, review file
    path, and overrides path targeting the Cryptomator processed directory.
  - Exported review file at
    `/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed/fallback_category_review.csv`
    (`6712` rows), so import can be run without explicit path flags in this
    worktree.
- Checks:
  - `python -m compileall src/finance_tooling/__main__.py`: pass
  - `uv run python -m finance_tooling review-import --help`: pass
- Open items:
  - `.env` is gitignored; default-path environment values are local-only unless
    documented elsewhere.
  - Full quality gates (`ruff`/`ty`/`pytest`) were not run in this worktree.
- Next action:
  - Run quality gates in this worktree, then commit the CLI change
    (`src/finance_tooling/__main__.py`) and AGENTS hand-off update.

### 2026-03-01 - codex
- Branch: `fix/hsbc-reconciliation-next`
- Completed:
  - Ran full workflow to nominal processed destination:
    `/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed`.
  - Updated metrics logs from nominal run summary via:
    `uv run python -m finance_tooling metrics-log-update --summary-path "/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed/run_summary.json" --log-path "docs/metrics_commit_log.csv" --log-path-by-bank "docs/metrics_commit_log_by_bank.csv"`.
  - Recorded refreshed reconciliation/categorization snapshots in
    `docs/metrics_commit_log.csv` and `docs/metrics_commit_log_by_bank.csv`.
- Checks:
  - `uv run python -m finance_tooling`: pass
  - `uv run python -m finance_tooling metrics-log-update ...`: pass
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Remaining HSBC fail in latest verification run remains
    `2019-11-27` (`-0.03`) and is documented as a source-PDF formatting
    artifact.
- Next action:
  - Decide whether to keep strict reconciliation tolerance (`0.01`) or accept
    this residual as operationally negligible.

### 2026-03-01 - codex
- Branch: `fix/hsbc-reconciliation-next`
- Completed:
  - Hardened HSBC FX cluster parsing for compact markers (`VisaRate`,
    `TransactionFee`) and broadened FX cluster detection to scan the full
    continuation cluster, not only the first continuation line.
  - Added parser regression coverage for compact FX lines that previously
    selected EUR nominal amounts instead of GBP `VisaRate` amounts.
  - Validated full-corpus impact in isolated run
    `/tmp/hsbc_recon_fixverify2_20260301-010651`: fixed `2016-12-29` and
    reduced HSBC fails from `4` to `1`.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest tests/test_parser.py -q`: pass
  - `uv run pytest`: pass
  - `uv run python -m finance_tooling.perf_check` (isolated temp output): pass
- Open items:
  - Remaining HSBC fail: `2019-11-27` with diff `-0.03`.
  - Decide whether reconciliation tolerance should remain strict at `0.01` or
    be relaxed for near-zero residuals.
- Next action:
  - Triage `2019-11-27` row-level residual and decide tolerance policy.

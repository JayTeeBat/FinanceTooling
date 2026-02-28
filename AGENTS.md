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

### 2026-02-28 - codex
- Branch: `fix/hsbc-table-boundary-state-machine`
- Completed:
  - Hardened HSBC column-based sign inference by classifying with token-center
    geometry (instead of token start) and preserving CR/DR marker precedence in
    near paid-out/paid-in boundary cases.
  - Added focused HSBC parser regressions for one-character left-boundary
    paid-in credits (with and without explicit CR marker), reproducing the two
    observed `10,000.00` sign-flip failures.
  - Ran full-corpus pipeline with HSBC CSV disabled in isolated output and
    improved reconciliation from `36/193` failed/checkable to `35/193`; the
    `2018-08-29` outlier (`|diff|=20000.00`) dropped out of HSBC fail files.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - HSBC high-diff outliers remain led by `2019-03` (`|diff|=13027.96`) and
    2021 months with large residual differences.
  - Investigate whether additional boundary-tolerance tuning is needed for
    column anchors where token-center still falls in paid-out range.
- Next action:
  - Triage `2019-03-29` with cached raw text + parsed rows to isolate remaining
    non-sign reconciliation defects.

### 2026-02-27 - codex
- Branch: `fix/hsbc-table-boundary-state-machine`
- Completed:
  - Implemented HSBC column-position sign inference from raw table spacing by
    detecting `Paidout`/`Paidin`/`Balance` anchors and resolving sign from token
    x-position when running-balance evidence is unavailable.
  - Preserved raw HSBC line context through block parsing and added
    `sign_from_column_position_count` diagnostics end-to-end in ingest/summary.
  - Verified the three first-page false negatives in `2016-12-29` are now
    parsed as credits and ran full-corpus validation in `/tmp`.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Remaining high-diff HSBC months include `2019-05`, `2019-06`, `2019-07`.
  - Add targeted regression fixtures for paid-in/paid-out split edge cases.
- Next action:
  - Add focused HSBC fixtures for column-position split cases and run a
    residual-diff triage pass on 2019 months.

### 2026-02-27 - codex
- Branch: `fix/hsbc-table-boundary-state-machine`
- Completed:
  - Reworked HSBC sign inference to explicit signed amounts with
    balance-first resolution, including cross-block running-balance context.
  - Disabled broad HSBC `SALARY` positive bias and replaced it with guarded
    fallback (`BP ... SALARY`) while keeping CR/DR marker precedence.
  - Added HSBC sign diagnostics (`hsbc_sign_*`) from parser through ingest and
    run summary, plus parser and workflow test updates.
  - Ran full-corpus validation in `/tmp`; compared to prior run, reconciliation
    fail counts held steady while major outlier `2017-08` improved from
    `|diff|=735.80` to `|diff|=107.08`.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - Remaining HSBC high-diff months include `2016-12`, `2019-05`, `2019-06`,
    `2019-07`.
  - Consider deeper paid-in/paid-out column-position inference from raw spacing
    to reduce reliance on fallback hints.
- Next action:
  - Add robust column-position sign inference using original line spacing and
    re-run full-corpus reconciliation comparison.

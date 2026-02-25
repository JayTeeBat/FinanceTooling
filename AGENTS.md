# AGENTS.md

## Mission

This repository exists to build reliable, Python-based tooling for monitoring
personal finances. The immediate focus is accurate bank statement ingestion and
normalization. The long-term goal is a maintainable pipeline for analysis,
categorization, and reporting.

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

### 2026-02-25 - codex
- Branch: `fix/hsbc-csv-import-main`
- Completed:
  - Added optional HSBC CSV source support via `FINANCE_HSBC_CSV_PATH` and CSV discovery for file/folder inputs.
  - Implemented typed HSBC CSV importer (`hsbc_csv`) that normalizes transactions into the canonical model and emits parse warnings for malformed input rows.
  - Integrated cross-source conflict handling in pipeline to prevent duplicate insertion between PDF and CSV extracts and to deterministically prefer CSV rows on clashes.
  - Added summary diagnostics for CSV ingestion and cross-source resolution (`hsbc_csv_files_scanned`, duplicate/clash drop counts).
  - Updated README and added tests for config wiring, CSV importer behavior, and PDF-vs-CSV duplicate/clash resolution.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
- Open items:
  - HSBC CSV conflict resolution currently uses a heuristic description similarity threshold; edge-case tuning may be needed against additional real-world samples.
  - Cross-source resolution currently prefers CSV for HSBC rows only; if additional bank CSV imports are added, policy should be generalized.
- Next action:
  - Run full real-corpus ingestion with `FINANCE_HSBC_CSV_PATH` enabled and review clash warnings to calibrate the similarity heuristic.

### 2026-02-25 - codex
- Branch: `fix/parser-hardening`
- Completed:
  - Hardened HSBC non-transaction filtering with explicit legal/footer noise
    markers (FSCS/rate/price-list/cap language) to prevent amount-bearing
    informational lines from being parsed as transactions.
  - Added HSBC continuation-context guardrails so non-transaction context lines
    reset pending parsing state instead of seeding amount row parsing.
  - Added seven new HSBC fixture cases covering edge cases for:
    footer/rate amount noise (2019/2021 variants), reversal sign isolation,
    large BP transfer sign handling, high-value CR block parsing, and
    statement-tail context termination.
  - Ran targeted HSBC tests, full quality gates, and full ingestion pipeline.
- Checks:
  - `uv run pytest tests/test_hsbc_fixtures.py tests/test_parser.py -k hsbc`: pass
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `uv run python -m finance_tooling`: pass
- Open items:
  - HSBC severe reconciliation failures (`|diff| > 1000`) remain unchanged at
    `15` despite parser hardening and fixture expansion.
  - Overall reconciliation improved slightly (`81` failed / `85` checkable vs
    prior `83` failed / `85`), with HSBC status now `69` fail / `2` pass.
  - Largest remaining HSBC outliers include 2021-05 (`-20114.14`) and 2019-03
    (`-13040.64`), indicating additional row-classification/sign rules are
    still needed for specific high-value statement patterns.
- Next action:
  - Add fixture-driven HSBC rules for salary/transfer/reversal block semantics
    in 2017/2019/2021 outlier layouts, then rerun pipeline and target HSBC
    severe fail reduction below `10` in the next pass.

### 2026-02-25 - codex
- Branch: `fix/parser-hardening`
- Completed:
  - Hardened HSBC continuation parsing to avoid sticky header-context
    carry-over and prevent amount-bearing footer/noise lines from being parsed
    as transactions.
  - Refined HSBC sign inference so CR/DR markers from fallback context no
    longer override prefixed continuation rows; added controlled inherited
    marker support for non-prefixed wrapped continuation lines.
  - Added HSBC parser regressions in `tests/test_parser.py` covering:
    CR-header marker bleed prevention, post-block amount-noise rejection, and
    wrapped CR marker inheritance behavior.
  - Ran full ingestion pipeline twice against real corpus and measured
    reconciliation deltas.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `uv run python -m finance_tooling`: pass
- Open items:
  - HSBC severe reconciliation failures (`|diff| > 1000`) improved but remain:
    `15` (down from `17`); total severe failures now `26` (down from `28`).
  - HSBC reconciliation remains broadly poor (`71` failed / `71` checkable for
    HSBC; overall run still `83` failed / `85` checkable), with largest
    remaining outliers including 2019-03 and 2021-05 statements.
  - One low-confidence parser route persists:
    `Boursobank Marion Releve-compte-30-09-2022.pdf` selected as Revolut.
- Next action:
  - Add fixture-driven HSBC handling for large outlier layouts (notably
    2019-03/2021-05) with line-pattern rules for wrapped reversal/transfer
    blocks, then rerun full pipeline and target HSBC severe fail count to zero.

### 2026-02-24 - codex
- Branch: `fix/parser-hardening`
- Completed:
  - Removed legacy parser routing API (`can_handle`) and standardized selection
    on confidence scoring (`match_score`) with deterministic threshold/tie
    behavior.
  - Added parser routing diagnostics (`ParserSelection` /
    `ParserScoreItem`) and integrated per-file selection diagnostics plus
    low-confidence counts into workflow warnings and `run_summary.json`.
  - Harmonized parser row normalization flow across bank parsers and improved
    Revolut sign inference with hint-priority default-debit behavior.
  - Added/updated tests for parser scoring, routing diagnostics, sign inference,
    and pipeline diagnostics integration.
  - Ran full ingestion pipeline against real corpus and reviewed resulting
    completeness/reconciliation diagnostics.
- Checks:
  - `uv run ruff check .`: pass
  - `uv run ruff format --check .`: pass
  - `uv run ty check src/finance_tooling tests`: pass
  - `uv run pytest`: pass
  - `uv run python -m finance_tooling`: pass
- Open items:
  - Reconciliation quality remains poor in real run: `83` failed / `85`
    checkable statements (pass ratio `0.024`), concentrated in HSBC and Revolut.
  - Statement coverage gaps remain (`16` statement PDFs with zero parsed rows):
    mostly HSBC (`14`) plus two Boursobank files.
  - One low-confidence parser route detected:
    `Boursobank Marion Releve-compte-30-09-2022.pdf` selected as Revolut
    (score `2`, threshold `2`).
- Next action:
  - Implement fixture-driven HSBC parser hardening for the identified missing/
    failing years first, then re-run full pipeline and verify reconciliation
    deltas.

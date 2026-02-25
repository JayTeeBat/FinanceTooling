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

Prioritized recommendations from latest repo assessment:

1. Decompose workflow orchestration in `src/finance_tooling/pipeline.py`
- Split into focused units (`ingest`, `hsbc_merge`, `enrichment`, `reporting`) while preserving behavior.
- Benefit: lower maintenance risk, simpler reasoning, smaller test surfaces.

2. Tighten typed boundaries for report payloads
- Replace broad `dict[str, object]` payload construction/casts with typed dataclasses or `TypedDict` for summary and completeness outputs.
- Benefit: safer refactors and clearer internal APIs.

3. Preserve monetary precision through storage/reporting paths
- Reduce `Decimal -> float` conversions where not strictly required; keep decimal-safe representation until final presentation.
- Benefit: better reconciliation accuracy and less rounding drift.

4. Replace broad exception handling with targeted error categories
- Narrow `except Exception` blocks in workflow/FX paths and emit structured warning context.
- Benefit: improved observability and faster debugging of real failures.

5. Improve parser/importer extensibility model
- Move from static registry tuple toward explicit plugin registration/discovery pattern.
- Benefit: easier onboarding of additional bank formats with cleaner boundaries.

6. Keep quality gates mandatory
- Continue enforcing:
  - `uv run ruff check .`
  - `uv run ruff format .`
  - `uv run ty check src/finance_tooling tests`
  - `uv run pytest`
- Benefit: protects reliability during refactors of parser and pipeline internals.

## Hand-Off Log

### 2026-02-25 - codex
- Branch: `main`
- Completed:
  - Added `## Next Agent Recommendations` section before `## Hand-Off Log`.
  - Documented prioritized architecture and maintainability improvements for the next agent session.
- Checks:
  - `sed -n '1,280p' AGENTS.md`: pass
- Open items:
  - Recommendations are documented; implementation work is still pending in code modules.
- Next action:
  - Start with pipeline decomposition plan for `src/finance_tooling/pipeline.py`.

### 2026-02-25 - codex
- Branch: `main`
- Completed:
  - Removed local-only branches:
    `develop`, `fix/hsbc-csv-import`, and `parser-hardening-revolut`.
  - Preserved `fix/hsbc-parser-metrics` because it is currently checked out in
    linked worktree `/home/thomazo/dev/FinanceTooling-hsbc-parser`.
- Checks:
  - `git for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads`: pass
  - `git branch -D <local-only-branch>`: pass (except linked-worktree branch)
  - `git branch -vv`: pass
- Open items:
  - `fix/hsbc-parser-metrics` remains and can only be deleted after removing or
    switching that external worktree branch.
- Next action:
  - If desired, clean the linked worktree branch and then delete
    `fix/hsbc-parser-metrics`.

### 2026-02-25 - codex
- Branch: `main`
- Completed:
  - Fetched and pruned remote refs from `origin` to refresh available branch
    state.
  - Removed stale local branches after pruning where upstream was deleted:
    `fix/hsbc-csv-import-main` and `fix/parser-hardening`.
- Checks:
  - `git fetch --prune --all`: pass
  - `git branch -r`: pass
  - `git branch -vv`: pass
  - `git branch --merged origin/main`: pass
- Open items:
  - Remaining local branches without upstream tracking were preserved pending
    explicit retention/deletion choice.
- Next action:
  - Decide retention policy for remaining untracked local branches and delete
    those no longer needed.

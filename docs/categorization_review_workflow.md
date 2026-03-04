# Categorization Review Workflow

This document defines the human-in-the-loop flow for manual category review,
transaction-level overrides, and project tagging.

## Purpose

- Export fallback-classified rows with full transaction detail for review.
- Let an analyst edit category/subcategory and project tags independently.
- Re-import reviewed rows into persistent overrides safely.
- Re-run transform to apply new overrides and reduce fallback volume.

## Flow Overview

- Diagram source: `docs/diagrams/categorization_review_hitl_flow.puml`
- Rendered diagram: `docs/diagrams/categorization_review_hitl_flow.svg`
- Guardrails source: `docs/diagrams/categorization_review_import_guardrails.puml`
- Guardrails rendered: `docs/diagrams/categorization_review_import_guardrails.svg`

## Step-by-Step Commands

Assumes `.env` has at least:

- `FINANCE_STATEMENTS_PATH`
- `FINANCE_PROCESSED_PATH`

Optional:

- `FINANCE_CATEGORY_OVERRIDES_PATH`
- `FINANCE_TRANSACTION_OVERRIDES_PATH`

### 1. Export fallback review rows

```bash
uv run python -m finance_tooling review-export
```

Default input/output paths when flags are omitted:

- normalized input: `${FINANCE_PROCESSED_PATH}/transactions_normalized.csv`
- review output: `${FINANCE_PROCESSED_PATH}/fallback_category_review.csv`

Default export behavior is fallback-only. Optional filters:

- `--include-categorized`: include non-fallback rows in the review export.
- `--start-date YYYY-MM-DD`: inclusive lower `booking_date` bound.
- `--end-date YYYY-MM-DD`: inclusive upper `booking_date` bound.

Example scoped export:

```bash
uv run python -m finance_tooling review-export \
  --include-categorized \
  --start-date "2026-01-01" \
  --end-date "2026-01-31"
```

### 2. Analyst review

Edit `${FINANCE_PROCESSED_PATH}/fallback_category_review.csv`:

- Keep `description`, `bank`, `account_label` unchanged.
- Set `category` and optional `subcategory` when a category correction is needed.
- Keep `category_source` as `fallback` for standard import mode.
- Use extra transaction columns (for example `booking_date`, `amount_native`,
  `currency`, `source_file`) to disambiguate similar descriptions when needed.
- Use `override_level` for category behavior:
  - `category_override`: write into `category_overrides.yaml`
  - `transaction_override`: write into `transaction_overrides.yaml`
  - `skip`: do not import category change for that row
- `override_level` defaults to `transaction_override` when left blank.
- Use `project_tags` for manual project tagging on unique transactions.
  - `project_tags` is independent from category edits.
  - Leave blank to skip project tagging.
  - Requires `transaction_id`.
- `existing_project_tags` is informational; do not edit.

### 3. Dry-run import (recommended)

```bash
uv run python -m finance_tooling review-import --dry-run
```

Dry-run reports row and upsert counters without writing override files.

### 4. Apply import

```bash
uv run python -m finance_tooling review-import
```

Default path resolution:

- review input: `${FINANCE_PROCESSED_PATH}/fallback_category_review.csv`
- category overrides destination:
  - `--overrides-path` if provided
  - else `FINANCE_CATEGORY_OVERRIDES_PATH` from settings
  - else `${FINANCE_STATEMENTS_PATH}/../config/category_overrides.yaml`
  - else, when settings are unavailable but `--review-path` is provided:
    `${REVIEW_PATH_PARENT}/../config/category_overrides.yaml`
- transaction overrides destination:
  - `--transaction-overrides-path` if provided
  - else `FINANCE_TRANSACTION_OVERRIDES_PATH` from settings
  - else `${FINANCE_STATEMENTS_PATH}/../config/transaction_overrides.yaml`
  - else, when settings are unavailable but `--review-path` is provided:
    `${REVIEW_PATH_PARENT}/../config/transaction_overrides.yaml`

Default safety behavior:

- abort on override-load warnings for either override file (unless
  `--allow-load-warnings`)
- skip rows not marked `category_source=fallback` (unless `--allow-non-fallback-import`)
- create timestamped backup before writing changed files (disable with
  `--no-backup`)

### 5. Re-run transform

```bash
uv run python -m finance_tooling transform
```

### 6. Optional: direct override editing outside CSV review

Use `${FINANCE_STATEMENTS_PATH}/../config/transaction_overrides.yaml` for direct
one-off edits or bulk edits outside the review CSV.

Use `${FINANCE_STATEMENTS_PATH}/../config/project_overrides.yaml` for reusable
project-tag automation:

- `rules`: reusable pattern-based tagging.
- `overrides`: fingerprint-scoped tagging (override-first).

Precedence during transform:

- Category fields: transaction override entries can force
  `category`/`subcategory` with source `transaction_override`.
- Project fields:
  `transaction_overrides` > `project_overrides.overrides` >
  `project_overrides.rules`.

## Import Guardrails

### Required columns

Review file must include:

- `description`
- `bank`
- `account_label`
- `category`
- `subcategory`
- `category_source`

### Row filtering

- Non-fallback rows are skipped by default.
- In legacy rows (without `override_level`), missing `description` or
  `category` are skipped as invalid.
- In v2 rows (with `override_level`):
  - category import is skipped when `category=Uncategorized` and subcategory is
    empty.
  - `override_level` must be one of:
    `skip`, `category_override`, `transaction_override`.
  - blank `override_level` defaults to `transaction_override`.
- `project_tags` import requires `transaction_id`.
- If multiple rows map to the same override key (`fingerprint`, `bank`,
  `account_label`), import keeps the last row (last-row wins).

### Operational switches

- `--allow-load-warnings`: proceed even if existing override file fails parsing.
- `--allow-non-fallback-import`: import rows where `category_source != fallback`.
- `--dry-run`: preview only, no writes.
- `--backup/--no-backup`: enable/disable pre-write backup.
- `--backup-path`: custom backup destination.
- `--transaction-overrides-path`: optional explicit transaction-override target.

## Rendering Diagrams

Run:

```bash
scripts/render_docs_diagrams.sh
```

The script expects `plantuml` in `PATH` and renders all `docs/diagrams/*.puml`
to SVG.

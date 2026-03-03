# Categorization Review Workflow

This document defines the human-in-the-loop flow for manual category review and
override upserts.

## Purpose

- Export fallback-classified rows with full transaction detail for review.
- Let an analyst set categories/subcategories manually.
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

### 1. Export fallback review rows

```bash
uv run python -m finance_tooling review-export
```

Default input/output paths when flags are omitted:

- normalized input: `${FINANCE_PROCESSED_PATH}/transactions_normalized.csv`
- review output: `${FINANCE_PROCESSED_PATH}/fallback_category_review.csv`

### 2. Analyst review

Edit `${FINANCE_PROCESSED_PATH}/fallback_category_review.csv`:

- Keep `description`, `bank`, `account_label` unchanged.
- Set `category` and optional `subcategory`.
- Keep `category_source` as `fallback` for standard import mode.
- Use extra transaction columns (for example `booking_date`, `amount_native`,
  `currency`, `source_file`) to disambiguate similar descriptions when needed.

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
- overrides destination:
  - `--overrides-path` if provided
  - else `FINANCE_CATEGORY_OVERRIDES_PATH` from settings
  - else `config/category_overrides.yaml`

Default safety behavior:

- abort on override-load warnings (unless `--allow-load-warnings`)
- skip rows not marked `category_source=fallback` (unless `--allow-non-fallback-import`)
- create timestamped backup before writing (disable with `--no-backup`)

### 5. Re-run transform

```bash
uv run python -m finance_tooling transform
```

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
- Rows missing `description` or `category` are skipped as invalid.
- If multiple rows map to the same override key (`fingerprint`, `bank`,
  `account_label`), import keeps the last row (last-row wins).

### Operational switches

- `--allow-load-warnings`: proceed even if existing override file fails parsing.
- `--allow-non-fallback-import`: import rows where `category_source != fallback`.
- `--dry-run`: preview only, no writes.
- `--backup/--no-backup`: enable/disable pre-write backup.
- `--backup-path`: custom backup destination.

## Rendering Diagrams

Run:

```bash
scripts/render_docs_diagrams.sh
```

The script expects `plantuml` in `PATH` and renders all `docs/diagrams/*.puml`
to SVG.

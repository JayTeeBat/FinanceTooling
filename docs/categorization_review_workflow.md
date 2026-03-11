# Categorization Review Workflow

This document defines the human-in-the-loop flow for manual category review,
transaction-level overrides, and project tagging.

Transaction identity is keyed by the canonical `transaction_id`, which now
includes a parser-assigned `source_record_index`. That fixes false-positive
deduplication for repeated same-day same-amount rows within the same statement.
The row index is persisted in staged/canonical outputs for auditability, but it
is intentionally not surfaced in the review workbook.

## Purpose

- Export uncategorized rows with full transaction detail for review in an Excel
  workbook.
- Let an analyst edit category/subcategory and project tags independently.
- Persist review progress (`reviewed`, `review_comment`) across review sessions.
- Re-import reviewed rows into persistent transaction overrides safely.
- Re-run transform to apply new overrides and reduce uncategorized volume.

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

- `FINANCE_TRANSACTION_OVERRIDES_PATH`
- `FINANCE_REVIEW_STATE_PATH`
- `FINANCE_REVIEW_EXPORT_DARK_SAFE`

### 1. Export uncategorized review rows

```bash
uv run review-export
```

Default input/output paths when flags are omitted:

- normalized input: `${FINANCE_PROCESSED_PATH}/transactions_normalized.csv`
- review output: `${FINANCE_PROCESSED_PATH}/transactions_review.xlsx`

Default export behavior is uncategorized-only. Optional filters:

- `--include-categorized`: include categorized rows in the review export.
- `--start-date YYYY-MM-DD`: inclusive lower `booking_date` bound.
- `--end-date YYYY-MM-DD`: inclusive upper `booking_date` bound.
- `--contains TEXT`: case-insensitive match across description/normalized description/bank/account.
- `--bank BANK`: exact bank filter.
- `--account-label LABEL`: exact account-label filter.
- `--only-unreviewed`: export only rows whose persisted review marker is false.
- `--dark-safe` / `--no-dark-safe`: force explicit light-on-dark workbook
  styling for dark-mode readability. Default comes from
  `FINANCE_REVIEW_EXPORT_DARK_SAFE` and falls back to enabled.

Example scoped export:

```bash
uv run review-export \
  --include-categorized \
  --start-date "2026-01-01" \
  --end-date "2026-01-31"
```

### 2. Analyst review

Edit `${FINANCE_PROCESSED_PATH}/transactions_review.xlsx`:

- Keep `description`, `bank`, `account_label` unchanged.
- Set `category` and optional `subcategory` when a category correction is needed.
- Use `normalized_description` as a read-only normalized search/grouping helper.
- Use extra transaction columns (for example `booking_date`, `amount_native`,
  `currency`, `source_file`) to disambiguate similar descriptions when needed.
- Use `reviewed` to mark a transaction as reviewed.
- Use `review_comment` for freeform reviewer notes.
- Category/subcategory edits always write into `transaction_overrides.yaml`.
- Use `project_tags` for manual project tagging on unique transactions.
  - `project_tags` is independent from category edits.
  - Leave blank to skip project tagging.
  - Requires `transaction_id`.
- `existing_project_tags` is informational; do not edit.
- `reviewed` is persisted separately and also projected into
  `transactions_normalized.csv` after `transform`.
- `review_comment` is review metadata only; it is not used as `project` data and
  is not written into canonical normalized outputs.

### 3. Dry-run import (recommended)

```bash
uv run review-import --dry-run
```

Dry-run reports row and upsert counters without writing override files.

### 4. Apply import

```bash
uv run review-import
```

Default path resolution:

- review input:
  - `${FINANCE_PROCESSED_PATH}/transactions_review.xlsx` if present
  - else `${FINANCE_PROCESSED_PATH}/transactions_review.csv`
- transaction overrides destination:
  - `--transaction-overrides-path` if provided
  - else `FINANCE_TRANSACTION_OVERRIDES_PATH` from settings
  - else `${FINANCE_STATEMENTS_PATH}/../config/transaction_overrides.yaml`
  - else, when settings are unavailable but `--review-path` is provided:
    `${REVIEW_PATH_PARENT}/../config/transaction_overrides.yaml`
- review state path:
  - `FINANCE_REVIEW_STATE_PATH` if configured
  - else `${FINANCE_PROCESSED_PATH}/review_state.parquet`

Default safety behavior:

- abort on transaction-override load warnings (unless `--allow-load-warnings`)
- create timestamped backup before writing changed files (disable with
  `--no-backup`)

### 5. Re-run transform

```bash
uv run transform
```

Or apply import and rebuild outputs in one step:

```bash
uv run review-import --run-transform
```

### 6. Optional: direct editing outside workbook review

Use `${FINANCE_STATEMENTS_PATH}/../config/transaction_overrides.yaml` for direct
one-off edits or bulk edits outside the review workbook.

Use `${FINANCE_STATEMENTS_PATH}/../config/category_rules.yaml` for reusable
categorization logic. Legacy fingerprint-level category overrides should be
migrated into exact-match rules with:

```bash
uv run migrate-category-overrides-to-rules
```

If you are upgrading from a corpus generated before `source_record_index` was
part of transaction identity:

```bash
uv run ingest
uv run migrate-transaction-ids
```

Then do the first post-migration `transform` against a clean
`transactions_master.parquet` backup/rename so manual carry-forward does not
reuse old collapsed identities.

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

- `transaction_id`
- `booking_date`
- `description`
- `amount_native`
- `currency`
- `bank`
- `account_label`
- `category`
- `subcategory`

### Row filtering

- Category import requires `transaction_id`.
- `category=Uncategorized` is treated as no manual category correction.
- `subcategory` without `category` is invalid.
- `project_tags` import requires `transaction_id`.
- `reviewed` / `review_comment` persistence requires `transaction_id`.
- If multiple rows map to the same `transaction_id`, import keeps the last row
  (last-row wins).

### Operational switches

- `--allow-load-warnings`: proceed even if existing override file fails parsing.
- `--dry-run`: preview only, no writes.
- `--backup/--no-backup`: enable/disable pre-write backup.
- `--backup-path`: custom backup destination.
- `--transaction-overrides-path`: optional explicit transaction-override target.
- `--run-transform`: import and immediately run `transform`.

## Rendering Diagrams

Run:

```bash
scripts/render_docs_diagrams.sh
```

The script expects `plantuml` in `PATH` and renders all `docs/diagrams/*.puml`
to SVG.

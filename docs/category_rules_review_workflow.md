# Category Rules Review Workflow (HITL)

This workflow defines a deterministic, month-scoped human-in-the-loop process
for proposing, validating, and safely applying category rule changes during the
2026 campaign.

## Scope and Goal

- Scope: `${FINANCE_STATEMENTS_PATH}/../config/category_rules.yaml` rule
  changes only (create/amend/delete).
- Goal: improve categorization coverage without degrading reconciliation metrics
  or introducing broad unintended recategorization.
- Principle: run comparisons in isolated directories, then merge only validated
  rule edits.

## End-to-End Cycle

Phases are mandatory and executed in order:

1. baseline
2. rule change authoring
3. impact preview
4. decisioning
5. apply
6. verify
7. rollback (if needed)

## 1) Baseline (Isolated)

Use a month-scoped isolated run so production outputs remain unchanged.

```bash
MONTH_START="2026-05-01"
MONTH_END="2026-05-31"
STAMP="$(date +%Y%m%d-%H%M%S)"
RUN_ROOT="${FINANCE_PROCESSED_PATH}/rule_review_2026-05_${STAMP}"
BASE_DIR="${RUN_ROOT}/baseline"
CAND_DIR="${RUN_ROOT}/candidate"

mkdir -p "${BASE_DIR}" "${CAND_DIR}"

# Snapshot current rules before editing.
cp "${FINANCE_STATEMENTS_PATH}/../config/category_rules.yaml" \
  "${RUN_ROOT}/category_rules.baseline.yaml"

# One deterministic ingest pass reused by both transforms.
FINANCE_PROCESSED_PATH="${BASE_DIR}" \
uv run ingest

cp "${BASE_DIR}/state/ingest_staged_transactions.parquet" \
  "${CAND_DIR}/state/ingest_staged_transactions.parquet"
```

Baseline transform:

```bash
FINANCE_PROCESSED_PATH="${BASE_DIR}" \
FINANCE_STAGED_TRANSACTIONS_PATH="${BASE_DIR}/state/ingest_staged_transactions.parquet" \
FINANCE_CATEGORY_RULES_PATH="${RUN_ROOT}/category_rules.baseline.yaml" \
uv run transform
```

## 2) Rule Change Authoring

Edit `${FINANCE_STATEMENTS_PATH}/../config/category_rules.yaml` and classify
the change type for each edit:

- create: add new rule
- amend: modify existing rule match/target
- delete: remove a rule

Acceptance checks by change type:

- create:
  - new targeted fingerprints move from `uncategorized` to intended category.
  - no unexpected cross-bank/account spillover.
- amend:
  - only intended rows move from old category to new category.
  - rule narrowing/widening is intentional and documented in PR notes.
- delete:
  - impacted rows are intentionally handled (new rule, transaction override, or uncategorized).
  - no silent drop in categorization quality for the month window.

## 3) Impact Preview

Run candidate transform against the same staged data.

```bash
FINANCE_PROCESSED_PATH="${CAND_DIR}" \
FINANCE_STAGED_TRANSACTIONS_PATH="${CAND_DIR}/state/ingest_staged_transactions.parquet" \
FINANCE_CATEGORY_RULES_PATH="${FINANCE_STATEMENTS_PATH}/../config/category_rules.yaml" \
uv run transform
```

Export comparable month-scoped review files (include categorized rows).

```bash
uv run review-export \
  --normalized-path "${BASE_DIR}/outputs/transform_transactions.csv" \
  --output-path "${RUN_ROOT}/baseline_review.xlsx" \
  --include-categorized \
  --start-date "${MONTH_START}" \
  --end-date "${MONTH_END}"

uv run review-export \
  --normalized-path "${CAND_DIR}/outputs/transform_transactions.csv" \
  --output-path "${RUN_ROOT}/candidate_review.xlsx" \
  --include-categorized \
  --start-date "${MONTH_START}" \
  --end-date "${MONTH_END}"
```

Optional full rerun command for sanity:

```bash
FINANCE_PROCESSED_PATH="${CAND_DIR}" uv run update
```

## 4) Decisioning (Impacted Previously Rule-Categorized Rows)

For rows that were previously categorized by rules and changed due to
create/amend/delete edits, choose one explicit action:

- keep as new-rule category
  - action: accept candidate rule result, no override added.
  - check: row is correctly categorized in candidate output.
- recategorize via transaction override
  - action: edit `category` / `subcategory` in the review workbook for exact
    transaction control, then import.
  - check: only intended transaction IDs are forced.
- intentionally uncategorized and track
  - action: leave uncategorized intentionally, track in month residuals.
  - check: appears in review export and is captured in
    `top_uncategorized_descriptions`.

## 5) Apply

After decisioning approval:

1. Keep approved changes in `${FINANCE_STATEMENTS_PATH}/../config/category_rules.yaml`.
2. Import approved transaction-level review edits if needed.

```bash
uv run review-import \
  --review-path "${RUN_ROOT}/candidate_review.xlsx"
```

3. Re-run canonical pipeline:

```bash
uv run transform
```

Or full refresh:

```bash
uv run update
```

## 6) Verify

Minimum verification points:

- `outputs/transform_run_summary.json`:
  - `categorized_count`
  - `uncategorized_count`
  - `uncategorized_ratio`
  - reconciliation counters
  - `top_uncategorized_descriptions`
- `outputs/transform_transactions.csv`:
  - expected `category_source` distribution for `MONTH_START..MONTH_END`.
  - spot-check changed fingerprints/transactions.

## 7) Rollback

Rollback if reconciliation regresses or categorization drift is not acceptable.

```bash
# Restore baseline rules snapshot
cp "${RUN_ROOT}/category_rules.baseline.yaml" \
  "${FINANCE_STATEMENTS_PATH}/../config/category_rules.yaml"

# Recompute outputs after rollback
uv run transform
```

If override imports were applied and must be reverted, restore from the
auto-created backup files produced by `review-import`.

## Merge Gates Checklist

- [ ] Change type tagged for every edit: create/amend/delete.
- [ ] Impact preview completed on isolated baseline vs candidate outputs.
- [ ] All impacted previously rule-categorized rows explicitly dispositioned.
- [ ] `uv run ruff check .` passes.
- [ ] `uv run ruff format .` applied.
- [ ] `uv run ty check src/finance_tooling tests` passes.
- [ ] `uv run pytest` passes.

## Post-Merge Monitoring Checklist (2026 Monthly Campaign)

- [ ] Re-run `update` for the same month and confirm deterministic outputs.
- [ ] Compare month-scoped `uncategorized_count` and `uncategorized_ratio`
      versus pre-merge baseline.
- [ ] Confirm reconciliation metrics are unchanged or improved.
- [ ] Review `top_uncategorized_descriptions`; add next-batch candidates to
      rule/override backlog.

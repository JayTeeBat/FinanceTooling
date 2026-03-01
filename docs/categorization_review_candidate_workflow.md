# Categorization Review Candidate Workflow

## Purpose

Define a robust human-in-the-loop workflow so reviewers can propose:

- transaction-level overrides
- category-level overrides
- new categorization rules

with strict validation and controlled apply behavior.

This document is intended as implementation guidance for the next agent.

## Goals

- Keep manual review practical for daily use.
- Prevent broad or unsafe rule changes from being applied silently.
- Preserve deterministic, auditable config updates.
- Maintain backward compatibility for existing override files.

## Non-Goals

- Replacing existing classification logic precedence.
- Adding interactive UI; this design targets CLI + review files.

## High-Level Workflow

1. Export review candidates from fallback-classified rows.
2. Human edits review file and chooses `action_type` per row.
3. Run `review-validate` to run hard checks + impact simulation.
4. Run `review-apply` to persist accepted changes.

Rules are never applied implicitly from normal `run` execution.

## Action Types

Each review row chooses one of:

- `transaction_override`
- `category_override`
- `new_rule`

## Review File Schema

### Core Columns

- `action_type`
- `description`
- `bank`
- `account_label`
- `category`
- `subcategory`
- `category_source`
- `transaction_id`

### Rule Columns (required only for `new_rule`)

- `rule_id`
- `priority`
- `match_type` (`contains|exact|regex`)
- `patterns`
- `expense_only`
- `income_only`
- `banks`
- `account_labels`
- `rule_enabled`

CSV compatibility note:

- `patterns`, `banks`, and `account_labels` should be encoded as JSON-like list
  strings for parsing stability.

## Required Fields by Action Type

### `transaction_override`

- required: `transaction_id`, `category`
- optional: `subcategory`
- ignored: rule columns

### `category_override`

- required: `description`, `bank`, `category`
- optional: `account_label`, `subcategory`
- key policy:
  - default: fingerprint(`description`) + `bank`
  - optional scoped mode: fingerprint + `bank` + `account_label`

### `new_rule`

- required: `rule_id`, `priority`, `match_type`, `patterns`, `category`
- optional: `subcategory`, `banks`, `account_labels`, `expense_only`, `income_only`
- constraints:
  - `expense_only` and `income_only` cannot both be true
  - regex patterns must compile

## Config Storage Shape

Use the existing override config file with two top-level lists:

- `overrides` (existing category-level entries)
- `transaction_overrides` (new exact transaction-level entries)

Rules continue to be stored in `category_rules.yaml` (or `.json`).

## Classification Precedence

1. transaction override (exact `transaction_id`)
2. category override (fingerprint + scope)
3. rule match
4. fallback

## Commands

## `review-validate`

Purpose:

- parse review rows
- run hard validation
- detect conflicts
- simulate candidate rule impact on normalized data
- write diagnostics report

Expected options:

- `--review-path`
- `--normalized-path`
- `--rules-path`
- `--overrides-path`
- `--include-account-label-scope`
- `--diagnostics-path`
- `--max-new-match-ratio` (default `0.02`)

## `review-apply`

Purpose:

- verify diagnostics are fresh and successful
- apply overrides/rules atomically

Expected options:

- `--review-path`
- `--rules-path`
- `--overrides-path`
- `--diagnostics-path`
- `--approve-rules` (mandatory if `new_rule` rows exist)
- `--force-max-new-match-ratio` (exception path only)

## Validation Stages

### Stage 1: Schema Validation (hard fail)

- required-by-action field checks
- enum checks (`action_type`, `match_type`)
- type parsing checks
- duplicate `rule_id` within candidate payload

### Stage 2: Conflict Validation (hard fail)

- `rule_id` collisions with existing rules
- duplicate semantic rules (same scope + matching semantics + target category)
- duplicate transaction override keys

### Stage 3: Safety Heuristics (warn/fail by policy)

- very generic patterns
- overly broad unscoped rules
- low-support rules

### Stage 4: Backtest Simulation (mandatory for rules)

Compute at minimum:

- `matched_count_new`
- `matched_ratio_new`
- `category_flips_count`
- `uncategorized_delta`
- per-bank impact
- top sampled affected descriptions

Gate:

- block when `matched_ratio_new > 0.02` unless force flag is provided at apply.

## Diagnostics Contract

`review-validate` should write structured JSON including:

- `status` (`pass|fail`)
- `errors`
- `warnings`
- per-rule impact metrics
- counts by action type
- input/config digests (for stale-check protection)

`review-apply` must refuse to apply if digests no longer match current files.

## Apply Semantics

- Transaction overrides: upsert by `transaction_id`.
- Category overrides: upsert by configured key policy.
- Rules: insert/update deterministically, sorted by priority then `rule_id`.
- Emit summary counts:
  - rows read/skipped
  - transaction overrides inserted/updated
  - category overrides inserted/updated
  - rules inserted/updated/rejected

## Failure Policy

- Hard-fail on validation errors.
- Hard-fail on rule apply when `--approve-rules` is missing.
- Hard-fail on stale diagnostics.
- No silent skips: skipped rows must be counted and explained in diagnostics.

## Compatibility and Migration

- Existing override files without `transaction_overrides` remain valid.
- Existing override-only `review-import` can remain for backward compatibility.
- Rule creation path must go through `review-validate` + `review-apply`.

## Suggested Test Matrix

- schema validation by action type
- transaction override precedence over category override and rules
- rule impact gating at 2%
- stale diagnostics detection
- `--approve-rules` enforcement
- backward compatibility for legacy override files

## Default Policy Values

- blast radius threshold: `2%`
- rule apply approval: explicit `--approve-rules` required
- category override scope default: fingerprint + bank
- account-label scoping: explicit opt-in

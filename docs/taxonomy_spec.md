# Taxonomy Specification

This document captures the repository's evolving taxonomy philosophy.

Its job is to make future taxonomy changes more consistent and robust by
recording:

- the design requirements for the taxonomy itself
- the reasoning behind major bucket boundaries
- the edge cases most likely to cause drift
- the review checklist for future taxonomy edits

This document is guidance, not the executable taxonomy registry. The
machine-readable source remains [`config/category_rules.yaml`](/home/thomazo/dev/FinanceTooling/config/category_rules.yaml).
When the implementation and this spec differ, the difference should be called
out explicitly and resolved intentionally.

For related docs:

- [`docs/taxonomy_guide.md`](/home/thomazo/dev/FinanceTooling/docs/taxonomy_guide.md)
  is the quick operator guide for choosing a bucket.
- [`docs/category_id_model.md`](/home/thomazo/dev/FinanceTooling/docs/category_id_model.md)
  explains the technical durable-ID architecture and lifecycle.

## Core Requirements

The taxonomy should be:

- purpose-first
- mutually exclusive enough to avoid common overlap
- complete enough that most real transactions have a natural home
- stable enough to support durable `category_id`
- simple enough to stay usable in review workflows
- compatible with `cashflow_type` and `economic_role`

The taxonomy should not primarily encode:

- merchant identity
- payment channel
- booking platform
- billing cadence
- operational review state

Those can be classification evidence, but they are not category meaning.

## Semantic Model

### Durable categorization

- `category_id` is the durable semantic bucket.
- `reporting_category_id` is the active reporting target after deprecation
  mapping.
- display labels are derived from taxonomy, not the other way around.

### Cash semantics

- `cashflow_type` answers what happened to household cash.
- `economic_role` answers whether the flow is true income, fixed expense,
  variable expense, legacy expense, transfer, or excluded.

Current intended model:

- `cashflow_type = transfer` for owned-account movement
- `cashflow_type = exclude` for explicitly excluded flows
- otherwise `cashflow_type` follows transaction sign
  - positive => `in`
  - negative => `out`

- `economic_role = transfer` when `cashflow_type = transfer`
- `economic_role = exclude` when `cashflow_type = exclude`
- `economic_role = income` only for true income categories
- `economic_role = fixed_expense` for recurring structural commitments such as
  rent, utilities, telecom, insurance, recurring taxes, and subscription-style
  bills
- `economic_role = variable_expense` for ordinary discretionary, usage-based,
  or ambiguous expenses
- `economic_role = expense` remains valid as a legacy/unknown expense-side
  compatibility value
- `decision_role = not_applicable` is the explicit display bucket for income,
  transfer, and excluded flows after cashflow and economic-role filtering has
  already removed them from the spend-side analysis

This distinction is important because some positive inflows are not true
income.

Important constraint:

- ordinary `in` / `out` should not be treated as durable taxonomy properties
- they are transaction-direction properties
- taxonomy should only encode semantics that are inherently categorical, such
  as:
  - true income meaning
  - transfer meaning
  - exclusion meaning

In other words:

- `transfer` and `exclude` can be category semantics
- ordinary `in` and `out` should usually be derived from sign and account
  boundary, not hardcoded into purpose buckets

## Design Principles

### 1. Purpose beats mechanism

Classify by what the money was economically for.

Examples:

- `Amazon` is not a category
- `Booking.com` is not a category
- `subscription` is not a category by itself
- `refund` is not a purpose bucket by itself when the original purpose is known

### 2. Avoid overlap by giving each family one job

Examples:

- `travel.*` should be trip-specific lodging or long-distance movement
- `transport.*` should be ordinary local movement
- `insurance.*` should be premiums and policy payments, not direct care
- `health.*` should be direct care and wellbeing spend
- transfer buckets should be minimal and not split hairs without analytical value

### 2b. Do not encode direction in purpose buckets

Purpose buckets should describe what the transaction was for, not whether the
signed cash movement happened to be inbound or outbound.

Examples:

- `groceries.*` is a purpose family
  - purchase => `cashflow_type = out`
  - refund => `cashflow_type = in`
- `shopping.apparel` is a purpose bucket
  - purchase => `cashflow_type = out`
  - return refund => `cashflow_type = in`

The category meaning stays stable; the sign-driven cash marker changes.

### 3. `Uncategorized` is not taxonomy

`Uncategorized` is an operational state meaning "no durable taxonomy assignment
yet". It should never be treated as a real family.

### 4. `other_*` is a pressure valve, not a destination

Use `other_*` only when:

- the transaction clearly belongs in the family
- none of the existing leaves are a good fit
- creating a new leaf is not yet justified

High `other_*` usage is a signal that taxonomy refinement may be needed.

## Boundary Decisions

### `groceries` vs `shopping`

Rule:

- `groceries.*` for food and household consumables meant for home use
- `shopping.*` for non-consumable or durable goods

Why:

- this keeps day-to-day consumables separate from general goods
- it avoids "supermarket" becoming a merchant bucket instead of a purpose bucket

Examples:

- supermarket ingredients => `groceries.food_at_home`
- detergents / paper goods => `groceries.household_consumables`
- headphones => `shopping.electronics`
- clothes => `shopping.apparel`

Anti-examples:

- do not classify a grocery refund into a generic refund bucket when the
  original purpose is clearly groceries

### `dining` vs `groceries`

Rule:

- `dining.*` for ready-to-eat meals
- `groceries.*` for ingredients and staples

Examples:

- restaurant => `dining.dining_out`
- takeaway => `dining.takeaway_delivery`
- home cooking ingredients => `groceries.food_at_home`

### `travel` vs `transport`

Rule:

- `transport.*` for local or routine movement
- `travel.*` for trip-specific lodging and long-distance movement

Examples:

- metro ticket => `transport.public_transport`
- airport taxi => `transport.taxi_ride_hailing`
- flight => `travel.long_distance_transport`
- hotel => `travel.accommodation`

Anti-examples:

- destination dining is still `dining.*`
- destination shopping is still `shopping.*`

### `health` vs `insurance`

Rule:

- `health.*` for direct care, medicine, dental/optical, and wellbeing spend
- `insurance.*` for premiums and policy payments

Examples:

- doctor => `health.medical_care`
- pharmacy => `health.pharmacy`
- health insurance premium => `insurance.health`

### `financial` vs `transfers`

Rule:

- `transfers.*` for movement between owned stores of value
- `financial.*` for fees, debt servicing, pension contributions, and external
  financial obligations

Examples:

- moving money to owned brokerage cash => `transfers.investment_transfer`
- broker fee => `financial.investment_fees`
- bank fee => `financial.bank_fees`

Live-taxonomy preference:

- do not distinguish `bank transfer` from `wallet transfer` unless they support
  materially different analysis
- keep one practical transfer bucket instead of multiple near-identical owned
  money-movement buckets
- preferred label: `account transfer`

### `excluded.shared_expense_settlement`

Rule:

- use only for balancing flows between people after the underlying expense is
  or should be categorized separately

Examples:

- friend pays you back for their share of dinner after the dinner was already
  categorized => `excluded.shared_expense_settlement`

Anti-examples:

- the original restaurant charge is `dining.dining_out`
- the original rent payment is `housing.rent`

### `cash_withdrawal` and `cash_deposit`

Target live-taxonomy preference:

- treat cash as its own expense bucket rather than a neutral transfer bucket
- this reflects the practical reality that cash often becomes untraceable in
  the household workflow

So:

- cash withdrawal should generally be treated as expense-side cash leakage
- cash should have its own dedicated category family/bucket instead of being
  hidden inside transfers

## Refund Policy

### Decision

Refunds should **not** be a primary taxonomy family in the target taxonomy
when the original purpose of the spend is known.

Instead:

- keep the transaction in the original purpose bucket
- let `cashflow_type` capture the positive/negative movement
- let `economic_role` preserve the fact that the flow is still expense-side,
  not true income

Why:

- a dedicated refund family disconnects the refund from the original spending
  domain
- that can inflate purpose-level spending and make category netting less useful
- the same problem appears with reimbursements and chargebacks when the original
  purpose is known

### Examples

Known purpose:

- grocery refund
  - category bucket: `groceries.*`
  - `cashflow_type = in`
  - `economic_role = variable_expense`

- health insurance reimbursement for a medical expense
  - category bucket: `health.*` when the reimbursed purpose is direct care
  - `cashflow_type = in`
  - `economic_role = variable_expense`

- merchant return refund for clothing
  - category bucket: `shopping.apparel`
  - `cashflow_type = in`
  - `economic_role = variable_expense`

- chargeback for a known travel booking
  - category bucket: `travel.*`
  - `cashflow_type = in`
  - `economic_role = variable_expense`

Unknown purpose:

- when the original domain truly cannot be known, a temporary refund-like
  fallback may still be operationally useful
- if this remains needed in the executable taxonomy, it should be treated as a
  fallback compatibility mechanism, not the target philosophy

This is also why refunds should not usually become their own primary family:

- the purpose bucket remains stable
- `cashflow_type` changes with sign
- `economic_role` remains expense-side, preferably preserving fixed/variable
  behavior from the purpose bucket when known
- category-level netting remains meaningful

## Carefully Chosen Edge Cases

### Subscriptions

Recurring billing does not decide category.

Examples:

- streaming => leisure / digital-entertainment type bucket
- therapy or meditation app => `health.wellbeing`
- general cloud storage => `leisure.personal_digital_services`
- work SaaS paid personally but outside household economics => likely
  `excluded.business`

Live-taxonomy preference:

- avoid vague buckets like `leisure.personal_digital_services`
- categorize subscriptions by their real purpose instead
- use a rule-level `economic_role: fixed_expense` override for recurring
  subscriptions such as Spotify, Audible, Disney/Netflix-style media, Amazon
  Prime/digital media, or Google One-style cloud services
- keep ordinary Amazon marketplace purchases in a shopping/marketplace purpose
  bucket with `economic_role: variable_expense`
- if a digital-service bucket is ever kept, it should have very narrow scope

### Pension contribution vs owned investment funding

- external pension contribution => `financial.retirement_contribution`
- movement into your own brokerage or investment cash account =>
  `transfers.investment_transfer`

### Government fees vs taxes vs fines

- local/property/council style taxes => `taxes.local_tax`
- penalties/fines => `taxes.penalties_fines`
- administrative government fees => `taxes.government_fees`

### Insurance reimbursement vs insurance premium

- premium/payment => `insurance.*`
- reimbursement should usually land in the reimbursed purpose bucket if known,
  not remain under insurance by default

## Live Taxonomy Preferences To Adopt

These are current design preferences for the next taxonomy refinement pass.

### Transfers

- collapse near-identical owned-money movement buckets
- do not maintain separate `bank transfer` and `wallet transfer` buckets unless
  the distinction proves analytically valuable
- keep one practical transfer bucket for ordinary owned-account movement

### Cash

- cash should be treated as its own expense-side category, not a neutral
  transfer
- rationale: in this workflow, cash is effectively lost traceability rather
  than a meaningful internal movement state

### Excluded group

- add a `non-profit` bucket under `excluded.*`

### Housing

- explicitly keep `home improvements` as a housing bucket

### Groceries

- remove `specialty food`
- keep groceries simple and practical

### Shopping

- keep `shopping.clothing` rather than `shopping.apparel`
- keep `shopping.marketplace` if it remains genuinely useful in analysis
- prefer stable, user-meaningful semantics over abstract taxonomy purity

### Transport

- replace abstract `vehicle_ownership` wording with a simple `car` bucket
- fold fuel into the `car` bucket rather than splitting it out
- keep a dedicated `bike` bucket
- avoid vague labels like `micromobility` unless they are truly needed

### Family

- remove vague leaves like `family.dependents`
- every family bucket should have a concrete, understandable meaning

### Leisure

- avoid vague leaves like `leisure.personal_digital_services`
- if a digital subscription belongs somewhere, route it by actual purpose

### Financial

- avoid abstract labels like `financial.debt_service` unless there is a very
  clear real-world use case for them

## Known Divergences From Current Implementation

These are intentional mismatches between the target philosophy and current
config/runtime behavior.

### Refunds

Current implementation still includes `refunds.*` as primary taxonomy leaves.

Target philosophy:

- refunds should generally stay in the original purpose bucket when that
  purpose is known
- dedicated refund buckets should be treated as compatibility/fallback, not the
  long-term target design

### Taxonomy-level `cashflow_type`

Current executable taxonomy still stores `cashflow_type` values on many bucket
definitions.

Target philosophy:

- taxonomy may encode category semantics such as `transfer`, `exclude`, and
  true-income meaning
- ordinary `in` / `out` should not be modeled as durable bucket properties for
  purpose categories
- normal positive/negative direction should instead come from transaction sign
  and account-boundary logic

This divergence should be revisited in a follow-up taxonomy refinement pass.

### Live taxonomy shape

Current implementation still contains several bucket names and splits that are
now considered too abstract or not useful enough for the preferred live
taxonomy direction.

Examples:

- separate transfer bucket variants
- transfer-side cash treatment
- `shopping.apparel` instead of `shopping.clothing`
- abstract transport/financial leaves such as `vehicle_ownership` or
  `debt_service`

These should be revised in the next taxonomy rollout rather than preserved just
because they exist today.

### Deprecated taxonomy in config

Current implementation keeps deprecated taxonomy entries in the executable
config to support reporting continuity and migration safety.

Policy:

- keep deprecated IDs while rollout is still in motion
- stop emitting deprecated IDs in active rules and review/import flows
- once the refined taxonomy stabilizes, run an explicit cleanup migration to
  rewrite deprecated IDs in canonical data and overrides
- only then remove no-longer-needed deprecated entries from config

So deprecated taxonomy should be treated as temporary migration scaffolding,
not as a permanent second taxonomy.

## Taxonomy Change Checklist

Any future taxonomy change should answer:

1. What economic purpose does the new bucket represent?
2. Why is it not already covered by an existing bucket?
3. Does it overlap with any existing family or leaf?
4. Is this really taxonomy, or just merchant/classification evidence?
5. How does it affect `cashflow_type` and `economic_role`?
6. Does it require a deprecated `category_id` path?
7. Will it harm historical comparability or make reporting less intuitive?

If a proposal fails those questions, it should probably be a rule change,
heuristic, or secondary attribute instead of a new taxonomy bucket.

# Taxonomy Guide

This guide explains how to pick a durable `category_id` bucket.

For the deeper taxonomy philosophy, edge-case reasoning, and future-change
checklist, see
[`docs/taxonomy_spec.md`](/home/thomazo/dev/FinanceTooling/docs/taxonomy_spec.md).

## Principles

- Classify by purpose first.
- Merchant, platform, booking channel, and payment cadence are evidence, not
  category meaning.
- `Uncategorized` is an operational state, not a taxonomy family.
- Use `other_*` leaves only as a last resort.

## Quick Decision Flow

1. Is this outside personal reporting?
   - Use `excluded.*`.
2. Is this movement between household-owned accounts or stores of value?
   - Use `transfers.*`.
3. Is this true income?
   - Use `income.*`.
4. Is this a refund or reimbursement?
   - If the original purpose is known, keep the original purpose bucket and let
     sign plus `economic_role` express the refund semantics.
   - Use refund-like fallback buckets only when the original purpose truly
     cannot be recovered.
5. Otherwise, classify by the purpose of the spend.

## Semantic Layers

### `cashflow_type`

`cashflow_type` describes household cash movement:

- `transfer` for owned-account movement
- `exclude` for explicitly excluded flows
- otherwise sign-based
  - positive => `in`
  - negative => `out`

### `economic_role`

`economic_role` describes economic meaning:

- `income` for true income categories
- `expense` for ordinary spend and refunds
- `transfer` / `exclude` when final `cashflow_type` is `transfer` / `exclude`

Important example:

- a health insurance reimbursement for direct care should normally stay in a
  `health.*` bucket
  - `cashflow_type = in`
  - `economic_role = expense`

## Boundary Rules

### `groceries` vs `shopping`

- `groceries.*`
  - consumable food and household consumables for home use
- `shopping.*`
  - non-consumable goods and durable products

Examples:
- supermarket food => `groceries.food_at_home`
- detergent / paper goods => `groceries.household_consumables`
- headphones => `shopping.electronics`
- clothing => `shopping.apparel`

### `dining` vs `groceries`

- `dining.*`
  - ready-to-eat meals, cafes, restaurants, bars, takeaway
- `groceries.*`
  - ingredients and staples for home consumption

Examples:
- restaurant bill => `dining.dining_out`
- takeaway order => `dining.takeaway_delivery`
- ingredients from supermarket => `groceries.food_at_home`

### `travel` vs `transport`

- `transport.*`
  - local day-to-day movement
- `travel.*`
  - trip-specific lodging and long-distance movement
- destination spend uses its real purpose bucket

Ancillary rule:
- baggage and seat fees attach to `travel.long_distance_transport`
- hotel add-ons attach to `travel.accommodation`
- use `travel.other_travel` only when the spend is clearly trip-specific and no
  narrower travel leaf is known

Examples:
- metro ticket in your city => `transport.public_transport`
- flight ticket => `travel.long_distance_transport`
- hotel => `travel.accommodation`
- taxi during a trip => `transport.taxi_ride_hailing`

### `health` vs `insurance`

- `health.*`
  - direct care, medicine, dental/optical, wellbeing spend
- `insurance.*`
  - premium and policy payments only

Examples:
- doctor visit => `health.medical_care`
- pharmacy purchase => `health.pharmacy`
- health insurance premium => `insurance.health`
- travel insurance premium => `insurance.travel`

### `health.wellbeing` vs `leisure.personal_digital_services`

- `health.wellbeing`
  - primary purpose is health, fitness, therapy, or meditation
- `leisure.personal_digital_services`
  - primary purpose is media, gaming, general consumer software, cloud/media
    storage, or generic personal app subscriptions

Examples:
- meditation subscription => `health.wellbeing`
- therapy app => `health.wellbeing`
- streaming subscription => `leisure.personal_digital_services`
- cloud storage => `leisure.personal_digital_services`

### `financial` vs `transfers`

- `transfers.*`
  - own-account movement with no external obligation or fee
- `financial.*`
  - lender, pension, broker fee, servicing, or other external financial
    obligation

Examples:
- moving money to your own brokerage cash account => `transfers.investment_transfer`
- broker platform fee => `financial.investment_fees`
- pension contribution to external provider => `financial.retirement_contribution`
- bank account fee => `financial.bank_fees`

### `excluded.shared_expense_settlement`

Use only for balancing flows between people after the underlying expense is or
should be categorized separately.

Examples:
- friend pays you back for their share of dinner after the dinner was already
  categorized => `excluded.shared_expense_settlement`

Anti-examples:
- the original restaurant transaction is not a settlement; it is
  `dining.dining_out`
- the original rent payment is not a settlement; it is `housing.rent`

### `cash_withdrawal` and `cash_deposit`

These are movement only:

- ATM withdrawal => `transfers.cash_withdrawal`
- cash deposit => `transfers.cash_deposit`

If later cash spending is observed, categorize that later spend by purpose.

## Special Families

### `income.*`

True income only:
- salary
- interest
- benefits
- business income
- investment income

### Refunds and reimbursements

Target policy:
- keep refunds in the original purpose bucket whenever the purpose is known
- do not create a standalone refund bucket by default when that would break net
  spend reporting by purpose

Examples:
- grocery refund => `groceries.*`
- health reimbursement for care => `health.*`
- clothing return refund => `shopping.apparel`

Note:
- current executable taxonomy may still contain `refunds.*` for compatibility;
  see [`docs/taxonomy_spec.md`](/home/thomazo/dev/FinanceTooling/docs/taxonomy_spec.md)
  for the target philosophy and known divergence

### `excluded.*`

Use sparingly and intentionally:
- `excluded.non_personal`
- `excluded.pass_through`
- `excluded.business`
- `excluded.shared_expense_settlement`

## Governance

- Keep `other_*` leaves rare and monitor their rate over time.
- If a new category is repeatedly needed, add a proper leaf instead of relying
  on `other_*`.
- If a merchant/platform seems to “deserve” its own bucket, first ask whether it
  is really evidence for a purpose bucket instead.

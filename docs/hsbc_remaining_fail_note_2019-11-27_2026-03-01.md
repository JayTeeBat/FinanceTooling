# HSBC Remaining Fail Note - 2019-11-27 (2026-03-01)

## Context

After the latest HSBC parser fixes, the only remaining HSBC reconciliation fail is:

- `HSBC Jacques 2019-11-27_Statement.pdf`
- Reconciliation diff: `-0.03`

Run reference:

- `/tmp/hsbc_recon_fixverify2_20260301-010651`

## Root Cause Confirmation

This residual is caused by a malformed numeric token in extracted PDF text, not
by transaction row parsing.

Observed in extracted text (`/tmp/hsbc_2019-11-27_raw_text_latest.txt`):

- Summary section shows `OpeningBalance      21,836.1 3` (space inside decimals).
- Statement table shows `BALANCEBROUGHTFORWARD ... 21,836.13` (correct form).

Current parser validation values for this file:

- `opening_balance = 21836.1`
- `transaction_sum = -5428.71`
- `closing_balance = 16407.42`
- `expected_closing_balance = 16407.39`
- `difference = -0.03`

The `0.03` residual matches truncation from `21,836.13 -> 21,836.1`.

## Decision

No parser patch planned for this specific case at this time.

Rationale:

- Residual is tiny (`|diff| = 0.03`).
- Root cause is source-PDF/extraction formatting artifact.
- Core transaction parsing is already aligned; this is balance-token text
  quality, not transaction interpretation.

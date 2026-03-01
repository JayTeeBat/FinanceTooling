# HSBC Failed Statement Diagnostics (FX Fix Validation) - 2026-02-28

## Scope

This note captures the latest HSBC reconciliation diagnostics after implementing
FX amount-token hardening in `HsbcParser` (Visa Rate GBP selection in FX
clusters).

Compared runs:

- Baseline without HSBC CSV merge:
  - `/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/processed_run_20260228-012931`
- Prior CSV-enabled debug run (pre-fix):
  - `/tmp/plan_debug_20260228-015004`
- Current CSV-enabled FX-fix run:
  - `/tmp/fxfix_20260228-022508`

## High-Level Metric Evolution

- Global reconciliation fail count:
  - `35` (baseline no CSV) -> `14` (prior CSV-enabled) -> `11` (FX-fix run)
- Global reconciliation pass ratio:
  - `0.8187` -> `0.9275` -> `0.9430`
- HSBC reconciliation fail count:
  - `33` -> `12` -> `9`

Largest historical outlier:

- `2019-03-29`: `-13027.96` (baseline no CSV) -> `2.6` (CSV-enabled runs)

Current top HSBC residuals in FX-fix run:

1. `2019-05-27`: `+500.0`
2. `2019-06-27`: `+500.0`
3. `2019-07-27`: `+495.02`
4. `2021-12-27`: `+55.0`

## Fail-Set Change vs Prior CSV-Enabled Run

Resolved months (no longer failing):

- `2018-05-29` (`5.6` -> pass)
- `2019-02-28` (`46.99` -> pass)
- `2021-07-27` (`50.0` -> pass)

Regressed months still failing:

- `2019-05-27`: `410.5` -> `500.0`
- `2019-07-27`: `339.81` -> `495.02`
- `2021-12-27`: `49.6` -> `55.0`

No new failing HSBC months were introduced.

## Deep-Dive: 2019-05 / 2019-06 / 2019-07

### 2019-05-27

- PDF rows / CSV rows: `67 / 67`
- PDF sum / CSV sum: `2057.86 / 2057.86` (delta `0.00`)
- `date+amount` unmatched rows: `0 / 0`
- Reconciliation diff using PDF: `+500.00`
- Reconciliation diff using CSV: `+500.00`
- First divergence date: `none`

Interpretation:

- Parser-vs-CSV transaction set is effectively identical.
- Residual is not a transaction token/sign mismatch.
- Likely source is statement opening/closing balance context extraction or
  statement-period alignment effect external to row parsing.

### 2019-06-27

- PDF rows / CSV rows: `79 / 75`
- PDF sum / CSV sum: `-1189.80 / -1931.41` (delta `+741.61`)
- Reconciliation diff using PDF: `+500.00`
- Reconciliation diff using CSV: `-241.61`
- First divergence date: `2019-06-27`
  - day delta `+741.61`
  - running delta `+741.61`

`date+amount` unmatched rows (PDF-only, all on `2019-06-27`):

- `+613.37`
- `+220.00`
- `-90.81`
- `-0.95`

Interpretation:

- Entire month divergence starts at statement-end date `2019-06-27`.
- Four extra parsed rows totaling `+741.61` fully explain PDF-vs-CSV delta.

### 2019-07-27

- PDF rows / CSV rows: `81 / 84`
- PDF sum / CSV sum: `4816.52 / 5564.11` (delta `-747.59`)
- Reconciliation diff using PDF: `+495.02`
- Reconciliation diff using CSV: `+1242.61`
- First divergence date: `2019-06-27`
  - day delta `-741.61`
  - running delta `-741.61`

`date+amount` unmatched:

- PDF-only:
  - `2019-07-23`: `-50.00`
  - `2019-07-15`: `-1.00`
- CSV-only:
  - `2019-06-27`: `+613.37`, `+220.00`, `-90.81`, `-0.95`
  - `2019-07-23`: `-45.02`

Interpretation:

- Mirror signature of 2019-06 boundary drift (same four `2019-06-27` rows),
  plus small additional row-value mismatch near `2019-07-23`.

## Probable Root Causes Remaining

1. Month-boundary ownership/remap issue around statement date `2019-06-27`.
- Same four rows appear as divergence core across consecutive months.

2. Residual balance-context issue in `2019-05-27`.
- Transactions align exactly PDF vs CSV but both produce `+500` residual.

3. Small row-value mismatch cases.
- Example `2019-07-23`: `-50.00` vs `-45.02`.

## Suggested Next Debug Actions

1. Instrument month assignment for overlap dates (`statement_end` boundary),
   specifically around `2019-06-27`.
2. Audit opening/closing balance extraction and per-statement validation payload
   for `2019-05-27` since row-level data aligns.
3. Add focused fixture for the `-50.00` vs `-45.02` pattern to lock expected
   amount-selection behavior.


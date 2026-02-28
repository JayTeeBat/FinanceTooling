# HSBC Reconciliation Root Cause Triage (2026-02-28)

## Scope

- Data source for failed set:
  - `processed_run_20260228-012931/completeness_report.json`
- Parsed rows compared:
  - `processed_run_20260228-012931/transactions_normalized.csv`
  - HSBC rows with `parser == "hsbc"` for reconciliation-failed HSBC statements
- Reference source:
  - Raw monthly HSBC CSV exports under:
    `/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw`

Total HSBC failed months triaged: `33`.

## Root Cause Counts

- `ROW_SET_GAP_OR_OTHER`: `16`
- `SMALL_MIXED_RESIDUAL`: `12`
- `FX_SIGN_PAIR_OR_MARKER`: `2`
- `FX_AMOUNT_TOKEN_SELECTION`: `2`
- `MISSING_CSV_REFERENCE`: `1`

## Most Important Findings

1. High-confidence FX amount token selection issue exists in major outliers.
- `2019-03-29` (`diff=-13027.96`) is dominated by FX token mismatch:
  - Ref-ID mismatches: `9`
  - Ref-ID delta sum: `-13011.68`
  - Example mismatches:
    - `0087787994`: PDF `-4160.0` vs CSV `-48.25`
    - `0081718057`: PDF `-3600.0` vs CSV `-41.99`
    - `0001069021`: PDF `-1800.0` vs CSV `-20.96`
- Raw text confirms lines with foreign amounts (`RUB 3,600.00`) plus `Visa Rate` GBP lines; parser appears to pick the wrong numeric amount in some cases.

2. Secondary FX sign/marker issues are present but less frequent.
- `2022-01-27` (`diff=-98.0`):
  - `0079854553`: PDF `-49.0` vs CSV `+40.84`
  - `0079854552`: PDF `-49.0` vs CSV `-40.97`
  - Suggests both sign handling and FX amount-source selection in reversal-style pairs.

3. Many remaining failed months look like row-set and mixed residual issues.
- Large set of months have non-trivial unmatched row counts between parsed PDF and raw CSV.
- These likely include inclusion/exclusion differences, continuation handling drift, and remaining non-sterling parsing edge cases.

4. One month lacks CSV reference.
- `2016-12-29` has no matching raw monthly CSV file for direct comparison.

## Month-by-Month Triage

| Month | Diff | Root Cause |
|---|---:|---|
| 2019-03-29 | -13027.96 | `FX_AMOUNT_TOKEN_SELECTION` |
| 2021-04-27 | -1007.31 | `FX_AMOUNT_TOKEN_SELECTION` |
| 2018-12-29 | -789.61 | `ROW_SET_GAP_OR_OTHER` |
| 2019-06-27 | 500.00 | `SMALL_MIXED_RESIDUAL` |
| 2019-05-27 | 410.50 | `SMALL_MIXED_RESIDUAL` |
| 2019-01-29 | -373.98 | `FX_SIGN_PAIR_OR_MARKER` |
| 2019-07-27 | 339.81 | `ROW_SET_GAP_OR_OTHER` |
| 2018-11-29 | -289.55 | `ROW_SET_GAP_OR_OTHER` |
| 2018-10-29 | -259.64 | `ROW_SET_GAP_OR_OTHER` |
| 2021-11-27 | -178.74 | `ROW_SET_GAP_OR_OTHER` |
| 2019-08-27 | -156.27 | `ROW_SET_GAP_OR_OTHER` |
| 2022-01-27 | -98.00 | `FX_SIGN_PAIR_OR_MARKER` |
| 2019-02-28 | -87.35 | `ROW_SET_GAP_OR_OTHER` |
| 2021-07-27 | -85.52 | `ROW_SET_GAP_OR_OTHER` |
| 2021-06-27 | -77.22 | `ROW_SET_GAP_OR_OTHER` |
| 2016-12-29 | -73.33 | `MISSING_CSV_REFERENCE` |
| 2020-08-27 | -61.73 | `ROW_SET_GAP_OR_OTHER` |
| 2018-06-29 | 60.00 | `ROW_SET_GAP_OR_OTHER` |
| 2018-05-29 | -51.80 | `ROW_SET_GAP_OR_OTHER` |
| 2021-12-27 | 49.60 | `SMALL_MIXED_RESIDUAL` |
| 2021-01-27 | -49.00 | `SMALL_MIXED_RESIDUAL` |
| 2021-03-27 | -45.70 | `ROW_SET_GAP_OR_OTHER` |
| 2017-04-29 | -45.05 | `SMALL_MIXED_RESIDUAL` |
| 2021-09-27 | -40.65 | `SMALL_MIXED_RESIDUAL` |
| 2018-09-29 | -40.00 | `ROW_SET_GAP_OR_OTHER` |
| 2021-05-27 | 30.85 | `ROW_SET_GAP_OR_OTHER` |
| 2021-08-27 | -21.99 | `SMALL_MIXED_RESIDUAL` |
| 2018-04-29 | -21.95 | `ROW_SET_GAP_OR_OTHER` |
| 2018-07-29 | -18.80 | `SMALL_MIXED_RESIDUAL` |
| 2017-03-29 | -10.10 | `SMALL_MIXED_RESIDUAL` |
| 2016-05-28 | -10.00 | `SMALL_MIXED_RESIDUAL` |
| 2017-12-29 | -8.80 | `SMALL_MIXED_RESIDUAL` |
| 2019-11-27 | -0.03 | `SMALL_MIXED_RESIDUAL` |

## Recommended Debug Priority

1. `FX_AMOUNT_TOKEN_SELECTION` months first:
- `2019-03-29`
- `2021-04-27`

2. `FX_SIGN_PAIR_OR_MARKER` months second:
- `2022-01-27`
- `2019-01-29`

3. Then row-set-heavy months:
- `2018-12-29`, `2019-07-27`, `2018-11-29`, `2018-10-29`, `2021-11-27`


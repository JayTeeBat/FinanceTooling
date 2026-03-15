# Sizing Guide

This is the best place to "play with numbers" for your household plan:

- `09_planning_inputs.yaml` for the current baseline assumptions
- `10_scenario_matrix.csv` for side-by-side scenario comparisons
- `uv run plan-savings` for the actual monthly-savings calculation

## How to use it

## 1. Fill the baseline

Start with `09_planning_inputs.yaml`.

This file should hold your current best estimate for:

- inflation
- stock / portfolio yield assumptions by goal
- retirement ages
- expected state pension
- target annual spending in retirement
- children education targets
- house project cost and date
- current assets already allocated to each goal

## 2. Derive the retirement capital target

Use this simple structure:

- retirement spending target
- minus expected state pension
- equals annual spending gap to be funded from assets

Then estimate the capital needed:

- capital target = annual spending gap / withdrawal rate

The calculator now applies `inflation_pct` to future targets when the input is
marked as being in today's euros.

Example:

- desired annual retirement spending: `60,000 EUR`
- expected combined pension: `30,000 EUR`
- annual gap: `30,000 EUR`
- if withdrawal rate = `3.5%`
- required capital = about `857,000 EUR`

This is the most important number for retirement sizing.

## 3. Size monthly savings for each goal

For each goal, estimate:

- current amount already set aside
- target amount
- target date
- expected annual return

For the planner:

- inflation moves the future nominal target
- stock yield / expected return changes how much the portfolio compounds on the
  way there
- retirement age changes the years available to compound
- kids fund size directly changes the target to hit

Then solve for the monthly contribution needed.

Use separate lines of thought:

- retirement
- child 1 education
- child 2 education
- child 3 education
- house expansion

Do not merge them into one target number, or you will lose visibility.

## 4. Compare scenarios

Use `10_scenario_matrix.csv` to compare tradeoffs such as:

- retire at `60` vs `62` vs `64`
- state pension pessimistic vs base vs optimistic
- house project at `100k` vs `130k`
- education target at `20k` vs `40k` per child

The most useful output is:

- total required monthly saving
- split between retirement / education / house
- whether that total fits your actual monthly surplus

## 5. Practical planning rule

Your sequence should be:

1. Set the baseline assumptions in `09_planning_inputs.yaml`.
2. Calculate the goal-specific required monthly savings.
3. Copy a few candidate cases into `10_scenario_matrix.csv`.
4. Choose the scenario that is both sufficient and realistically affordable.

## 6. What to test first in your situation

I would model these scenarios first:

- Base case:
  retirement at `62 / 62`, moderate pension assumption, house project at
  `110k`
- Conservative case:
  retirement at `60 / 60`, lower pension assumption, house project at `130k`
- Flexible case:
  retirement at `64 / 64`, same spending target, house project at `110k`

## 7. The key output

The key question is not "what should we invest in?"

It is:

"How much must we save each month for each goal, and is that compatible with
our real life cashflow?"

That answer should come from these two files before you fine-tune account or
investment choices.

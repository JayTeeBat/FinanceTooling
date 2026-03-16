"""Self-contained planning hypothesis dashboard rendering."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finance_tooling.planning import load_planning_inputs


def _serialize_payload(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return serialized.replace("</", "<\\/")


def _build_payload(inputs: dict[str, Any]) -> dict[str, object]:
    household = inputs["household"]
    adults = household["adults"]
    children = household["children"]
    income = inputs["income"]
    liquidity = inputs["liquidity"]
    retirement = inputs["retirement"]
    education = inputs["education"]
    house_project = inputs["house_project"]
    net_worth = inputs["net_worth"]
    mortgage = inputs.get("mortgage", {})
    assumptions = inputs["assumptions"]

    current_house_target_years = 5.0
    target_date = house_project.get("target_date")
    if target_date:
        try:
            year = int(str(target_date)[:4])
            current_year = datetime.now(UTC).year
            current_house_target_years = max(0.0, year - current_year)
        except ValueError:
            current_house_target_years = 5.0

    return {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "title": "Household Finance Hypothesis Playground",
        },
        "baseline": {
            "adult_1_date_of_birth": str(adults.get("adult_1_date_of_birth", "")),
            "adult_1_age": adults["adult_1_current_age"],
            "adult_2_date_of_birth": str(adults.get("adult_2_date_of_birth", "")),
            "adult_2_age": adults["adult_2_current_age"],
            "child_ages": [
                children["child_1_current_age"],
                children["child_2_current_age"],
                children["child_3_current_age"],
            ],
            "estimated_net_household_income_eur": income["estimated_net_household_income_eur"],
            "essential_monthly_spend_eur": liquidity["essential_monthly_spend_eur"],
            "emergency_fund_target_months": liquidity["emergency_fund_target_months"],
            "retirement_age": retirement["target_retirement_age_adult_1"],
            "retirement_age_adult_1": retirement["target_retirement_age_adult_1"],
            "retirement_age_adult_2": retirement["target_retirement_age_adult_2"],
            "combined_pension_before_tax_eur": retirement["expected_annual_state_pension_eur"],
            "pension_adult_1_before_tax_eur": retirement.get(
                "expected_annual_state_pension_adult_1_eur",
                retirement["expected_annual_state_pension_eur"] / 2,
            ),
            "pension_adult_2_before_tax_eur": retirement.get(
                "expected_annual_state_pension_adult_2_eur",
                retirement["expected_annual_state_pension_eur"] / 2,
            ),
            "retirement_spending_before_tax_eur": retirement[
                "target_annual_spending_in_retirement_eur"
            ],
            "withdrawal_rate_pct": retirement["safe_withdrawal_rate_pct"],
            "current_retirement_assets_eur": retirement["current_retirement_assets_eur"],
            "kids_target_fund_per_child_eur": education["child_1_target_fund_eur"],
            "current_child_funds_eur": [
                education["child_1_current_fund_eur"],
                education["child_2_current_fund_eur"],
                education["child_3_current_fund_eur"],
            ],
            "house_project_cost_eur": house_project["target_cost_eur"],
            "house_contingency_pct": house_project["contingency_pct"],
            "house_target_years": current_house_target_years,
            "current_house_reserved_eur": house_project["current_reserved_amount_eur"],
            "inflation_pct": assumptions["inflation_pct"],
            "growth_return_pct": retirement["expected_nominal_return_pct"],
            "house_return_pct": house_project["expected_return_pct"],
            "current_total_net_worth_eur": net_worth.get(
                "current_total_net_worth_eur",
                (
                    net_worth["current_total_financial_assets_eur"]
                    + net_worth["current_home_equity_eur"]
                ),
            ),
            "current_investable_net_worth_eur": net_worth.get(
                "current_investable_net_worth_eur",
                net_worth["current_total_financial_assets_eur"],
            ),
            "current_home_value_eur": net_worth.get(
                "current_home_value_eur",
                net_worth["current_home_equity_eur"] + net_worth["current_mortgage_balance_eur"],
            ),
            "current_total_financial_assets_eur": net_worth["current_total_financial_assets_eur"],
            "current_mortgage_balance_eur": net_worth["current_mortgage_balance_eur"],
            "mortgage_annual_rate_pct": mortgage.get("annual_rate_pct", 0.0),
            "mortgage_monthly_payment_eur": mortgage.get("monthly_payment_eur", 0.0),
            "mortgage_years_remaining": mortgage.get("years_remaining", 0.0),
        },
    }


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Household Finance Hypothesis Playground</title>
  <style>
    :root {
      --sand: #f5efe3;
      --paper: #fffaf2;
      --ink: #1f1a15;
      --muted: #6d6256;
      --line: #d7cab7;
      --accent: #8b5e34;
      --accent-deep: #5f3f22;
      --sage: #6c8a6b;
      --rose: #ad5a4f;
      --shadow: 0 18px 38px rgba(61, 43, 28, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(139, 94, 52, 0.14), transparent 32%),
        radial-gradient(circle at bottom right, rgba(108, 138, 107, 0.16), transparent 28%),
        linear-gradient(180deg, var(--sand), var(--paper));
      min-height: 100vh;
    }
    .shell {
      max-width: 1360px;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      gap: 18px;
    }
    .hero, .panel, .card {
      background: rgba(255, 250, 242, 0.92);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }
    .hero {
      padding: 24px;
      display: grid;
      gap: 10px;
    }
    h1 {
      margin: 0;
      font-family: "IBM Plex Serif", Georgia, serif;
      font-size: clamp(30px, 4vw, 42px);
      letter-spacing: -0.02em;
    }
    .hero p, .muted {
      margin: 0;
      color: var(--muted);
    }
    .meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 13px;
      color: var(--muted);
    }
    .pill {
      padding: 7px 12px;
      border-radius: 999px;
      background: rgba(139, 94, 52, 0.08);
      border: 1px solid var(--line);
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }
    .panel {
      padding: 18px;
      display: grid;
      gap: 16px;
      position: sticky;
      top: 16px;
    }
    .panel h2, .card h2 {
      margin: 0;
      font-size: 20px;
      color: var(--accent-deep);
    }
    .input-grid {
      display: grid;
      gap: 12px;
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .field label {
      font-size: 13px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .field input {
      width: 100%;
      padding: 11px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.9);
      font: inherit;
      color: var(--ink);
    }
    .range-line {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
    }
    .range-line output {
      min-width: 90px;
      text-align: right;
      color: var(--accent-deep);
      font-weight: 700;
    }
    .cards {
      display: grid;
      gap: 18px;
    }
    .kpis {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }
    .kpi {
      padding: 16px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.84);
      display: grid;
      gap: 6px;
    }
    .kpi .label {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      font-weight: 700;
    }
    .kpi .value {
      font-size: 28px;
      font-weight: 800;
      color: var(--accent-deep);
    }
    .kpi .sub {
      font-size: 13px;
      color: var(--muted);
    }
    .card {
      padding: 18px;
      display: grid;
      gap: 14px;
    }
    .split-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 12px;
    }
    .split {
      border-radius: 14px;
      padding: 14px;
      color: #fff;
      display: grid;
      gap: 4px;
    }
    .split.ret { background: linear-gradient(140deg, #815635, #5f3f22); }
    .split.edu { background: linear-gradient(140deg, #688567, #4d6b4c); }
    .split.house { background: linear-gradient(140deg, #ba6c57, #965043); }
    .split .big {
      font-size: 26px;
      font-weight: 800;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .right { text-align: right; }
    .callout {
      border-left: 4px solid var(--accent);
      padding: 12px 14px;
      background: rgba(139, 94, 52, 0.08);
      border-radius: 12px;
      color: var(--muted);
    }
    .afford {
      font-weight: 800;
    }
    .afford.good { color: var(--sage); }
    .afford.warn { color: #b77b20; }
    .afford.bad { color: var(--rose); }
    @media (max-width: 980px) {
      .layout { grid-template-columns: 1fr; }
      .panel { position: static; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>Household Finance Hypothesis Playground</h1>
      <p>
        Adjust retirement age, pension, spending, house budget, inflation, and
        return assumptions to see required monthly savings update instantly.
      </p>
      <div class="meta-row">
        <span class="pill" id="generated-at"></span>
        <span class="pill" id="income-pill"></span>
        <span class="pill" id="assets-pill"></span>
        <span class="pill" id="mortgage-pill"></span>
      </div>
    </section>

    <div class="layout">
      <aside class="panel">
        <h2>Hypotheses</h2>
        <div class="input-grid">
          <div class="field">
            <label for="adult-1-dob">Adult 1 date of birth</label>
            <input id="adult-1-dob" type="date" />
          </div>
          <div class="field">
            <label for="adult-2-dob">Adult 2 date of birth</label>
            <input id="adult-2-dob" type="date" />
          </div>
          <div class="field">
            <label for="retirement-age-adult-1">Adult 1 retirement age</label>
            <div class="range-line">
              <input id="retirement-age-adult-1" type="range" min="60" max="70" step="1" />
              <output id="retirement-age-adult-1-output"></output>
            </div>
          </div>
          <div class="field">
            <label for="retirement-age-adult-2">Adult 2 retirement age</label>
            <div class="range-line">
              <input id="retirement-age-adult-2" type="range" min="60" max="70" step="1" />
              <output id="retirement-age-adult-2-output"></output>
            </div>
          </div>
          <div class="field">
            <label for="pension-adult-1">Adult 1 pension before taxes (EUR/year)</label>
            <input id="pension-adult-1" type="number" min="0" step="2500" />
          </div>
          <div class="field">
            <label for="pension-adult-2">Adult 2 pension before taxes (EUR/year)</label>
            <input id="pension-adult-2" type="number" min="0" step="2500" />
          </div>
          <div class="field">
            <label for="retirement-spending">Retirement spending before taxes (EUR/year)</label>
            <input id="retirement-spending" type="number" min="0" step="5000" />
          </div>
          <div class="field">
            <label for="withdrawal-rate">Withdrawal rate (%)</label>
            <input id="withdrawal-rate" type="number" min="1" max="6" step="0.1" />
          </div>
          <div class="field">
            <label for="current-investable-net-worth">Current investable net worth (EUR)</label>
            <input id="current-investable-net-worth" type="number" min="0" step="5000" />
          </div>
          <div class="field">
            <label for="current-total-net-worth">Current total net worth (EUR)</label>
            <input id="current-total-net-worth" type="number" step="5000" />
          </div>
          <div class="field">
            <label for="current-home-value">Current home value (EUR)</label>
            <input id="current-home-value" type="number" min="0" step="5000" />
          </div>
          <div class="field">
            <label for="mortgage-balance">Current mortgage balance (EUR)</label>
            <input id="mortgage-balance" type="number" min="0" step="5000" />
          </div>
          <div class="field">
            <label for="mortgage-rate">Mortgage rate incl. insurance (%)</label>
            <input id="mortgage-rate" type="number" min="0" max="15" step="0.1" />
          </div>
          <div class="field">
            <label for="mortgage-payment">Mortgage monthly payment (EUR)</label>
            <input id="mortgage-payment" type="number" min="0" step="50" />
          </div>
          <div class="field">
            <label for="mortgage-years">Mortgage years remaining</label>
            <input id="mortgage-years" type="number" min="0" max="40" step="0.5" />
          </div>
          <div class="field">
            <label for="home-growth">Home value growth (%)</label>
            <div class="range-line">
              <input id="home-growth" type="range" min="-1" max="6" step="0.1" />
              <output id="home-growth-output"></output>
            </div>
          </div>
          <div class="field">
            <label for="kids-fund">Kids fund target per child (EUR)</label>
            <input id="kids-fund" type="number" min="0" step="1000" />
          </div>
          <div class="field">
            <label for="house-cost">House project cost (EUR)</label>
            <input id="house-cost" type="number" min="0" step="5000" />
          </div>
          <div class="field">
            <label for="house-years">House project timeline (years)</label>
            <input id="house-years" type="number" min="0" max="15" step="0.5" />
          </div>
          <div class="field">
            <label for="inflation">Inflation (%)</label>
            <div class="range-line">
              <input id="inflation" type="range" min="0" max="5" step="0.1" />
              <output id="inflation-output"></output>
            </div>
          </div>
          <div class="field">
            <label for="growth-return">Growth return (%)</label>
            <div class="range-line">
              <input id="growth-return" type="range" min="0" max="10" step="0.1" />
              <output id="growth-return-output"></output>
            </div>
          </div>
          <div class="field">
            <label for="house-return">House reserve return (%)</label>
            <div class="range-line">
              <input id="house-return" type="range" min="0" max="5" step="0.1" />
              <output id="house-return-output"></output>
            </div>
          </div>
        </div>
      </aside>

      <main class="cards">
        <section class="card">
          <h2>Headline</h2>
          <div class="kpis">
            <div class="kpi">
              <div class="label">Total Monthly Savings Needed</div>
              <div class="value" id="total-monthly"></div>
              <div class="sub" id="monthly-vs-income"></div>
            </div>
            <div class="kpi">
              <div class="label">Annual Savings Need</div>
              <div class="value" id="annual-savings"></div>
              <div class="sub" id="surplus-gap"></div>
            </div>
            <div class="kpi">
              <div class="label">Emergency Fund Target</div>
              <div class="value" id="emergency-target"></div>
              <div class="sub">Based on essential spending and reserve months</div>
            </div>
            <div class="kpi">
              <div class="label">Retirement Capital Target</div>
              <div class="value" id="retirement-capital"></div>
              <div class="sub" id="retirement-gap"></div>
            </div>
            <div class="kpi">
              <div class="label">Projected Net Worth At Retirement</div>
              <div class="value" id="retirement-net-worth"></div>
              <div class="sub" id="retirement-net-worth-detail"></div>
            </div>
            <div class="kpi">
              <div class="label">Projected Home Equity At Retirement</div>
              <div class="value" id="retirement-home-equity"></div>
              <div class="sub" id="retirement-home-equity-detail"></div>
            </div>
          </div>
          <div class="callout">
            <span class="afford" id="affordability"></span>
            <span id="affordability-note"></span>
          </div>
        </section>

        <section class="card">
          <h2>Goal Split</h2>
          <div class="split-grid">
            <div class="split ret">
              <div>Retirement</div>
              <div class="big" id="retirement-monthly"></div>
              <div id="retirement-detail"></div>
            </div>
            <div class="split edu">
              <div>Education</div>
              <div class="big" id="education-monthly"></div>
              <div id="education-detail"></div>
            </div>
            <div class="split house">
              <div>House Project</div>
              <div class="big" id="house-monthly"></div>
              <div id="house-detail"></div>
            </div>
          </div>
        </section>

        <section class="card">
          <h2>Retirement Milestones</h2>
          <table>
            <thead>
              <tr>
                <th>Spouse</th>
                <th>DoB</th>
                <th>Retirement age</th>
                <th>Retirement year</th>
                <th class="right">Pension / year</th>
              </tr>
            </thead>
            <tbody id="retirement-table"></tbody>
          </table>
        </section>

        <section class="card">
          <h2>Housing Projection</h2>
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                <th class="right">Today</th>
                <th class="right">At retirement</th>
              </tr>
            </thead>
            <tbody id="housing-table"></tbody>
          </table>
        </section>

        <section class="card">
          <h2>Education by Child</h2>
          <table>
            <thead>
              <tr>
                <th>Child</th>
                <th>Years to age 18</th>
                <th class="right">Future target</th>
                <th class="right">Monthly saving</th>
              </tr>
            </thead>
            <tbody id="education-table"></tbody>
          </table>
        </section>

        <section class="card">
          <h2>Context</h2>
          <p class="muted">
            This page uses the same compounding logic as the planning CLI.
            Retirement need is based on the annual gap between retirement
            spending and pension, converted into a capital target using the
            withdrawal rate. Education and house goals grow targets with
            inflation and discount monthly saving needs with the selected
            return assumptions.
          </p>
        </section>
      </main>
    </div>
  </div>

  <script id="planning-dashboard-data" type="application/json">__PAYLOAD_JSON__</script>
  <script>
    const payload = JSON.parse(document.getElementById("planning-dashboard-data").textContent);
    const baseline = payload.baseline;

    const ids = {
      adult1Dob: document.getElementById("adult-1-dob"),
      adult2Dob: document.getElementById("adult-2-dob"),
      retirementAgeAdult1: document.getElementById("retirement-age-adult-1"),
      retirementAgeAdult1Output: document.getElementById("retirement-age-adult-1-output"),
      retirementAgeAdult2: document.getElementById("retirement-age-adult-2"),
      retirementAgeAdult2Output: document.getElementById("retirement-age-adult-2-output"),
      pensionAdult1: document.getElementById("pension-adult-1"),
      pensionAdult2: document.getElementById("pension-adult-2"),
      retirementSpending: document.getElementById("retirement-spending"),
      withdrawalRate: document.getElementById("withdrawal-rate"),
      currentInvestableNetWorth: document.getElementById("current-investable-net-worth"),
      currentTotalNetWorth: document.getElementById("current-total-net-worth"),
      currentHomeValue: document.getElementById("current-home-value"),
      mortgageBalance: document.getElementById("mortgage-balance"),
      mortgageRate: document.getElementById("mortgage-rate"),
      mortgagePayment: document.getElementById("mortgage-payment"),
      mortgageYears: document.getElementById("mortgage-years"),
      homeGrowth: document.getElementById("home-growth"),
      homeGrowthOutput: document.getElementById("home-growth-output"),
      kidsFund: document.getElementById("kids-fund"),
      houseCost: document.getElementById("house-cost"),
      houseYears: document.getElementById("house-years"),
      inflation: document.getElementById("inflation"),
      inflationOutput: document.getElementById("inflation-output"),
      growthReturn: document.getElementById("growth-return"),
      growthReturnOutput: document.getElementById("growth-return-output"),
      houseReturn: document.getElementById("house-return"),
      houseReturnOutput: document.getElementById("house-return-output"),
    };

    function fmtCurrency(value) {
      return new Intl.NumberFormat("en-IE", {
        style: "currency",
        currency: "EUR",
        maximumFractionDigits: 0,
      }).format(value);
    }

    function fmtNumber(value, digits = 1) {
      return Number(value).toFixed(digits);
    }

    function monthlyRate(annualPct) {
      return Math.pow(1 + annualPct / 100, 1 / 12) - 1;
    }

    function inflate(amount, years, inflationPct) {
      return amount * Math.pow(1 + inflationPct / 100, Math.max(0, years));
    }

    function yearsFromDob(dobText, retirementAge) {
      const dob = new Date(dobText);
      if (Number.isNaN(dob.getTime())) {
        return 0;
      }
      const retirementDate = new Date(dob);
      retirementDate.setFullYear(retirementDate.getFullYear() + retirementAge);
      const now = new Date();
      return Math.max(0, (retirementDate - now) / (365.25 * 24 * 60 * 60 * 1000));
    }

    function retirementYearFromDob(dobText, retirementAge) {
      const dob = new Date(dobText);
      if (Number.isNaN(dob.getTime())) {
        return "n/a";
      }
      return String(dob.getFullYear() + retirementAge);
    }

    function futureValueOfPortfolio(currentAmount, monthlyContribution, years, annualReturnPct) {
      if (years <= 0) {
        return currentAmount;
      }
      const months = Math.max(1, Math.round(years * 12));
      const rate = monthlyRate(annualReturnPct);
      const futureCurrent = currentAmount * Math.pow(1 + rate, months);
      if (Math.abs(rate) < 1e-12) {
        return futureCurrent + monthlyContribution * months;
      }
      const annuity = (Math.pow(1 + rate, months) - 1) / rate;
      return futureCurrent + monthlyContribution * annuity;
    }

    function projectMortgageBalance(balance, annualRatePct, monthlyPayment, years) {
      let remaining = Math.max(0, balance);
      const months = Math.max(0, Math.round(years * 12));
      const monthlyRateValue = annualRatePct / 100 / 12;
      for (let i = 0; i < months && remaining > 0; i += 1) {
        remaining = remaining * (1 + monthlyRateValue) - monthlyPayment;
        if (remaining < 0) {
          remaining = 0;
        }
      }
      return remaining;
    }

    function requiredMonthlyContribution(
      targetAmount,
      currentAmount,
      yearsToGoal,
      expectedReturnPct
    ) {
      if (yearsToGoal <= 0) {
        return Math.max(0, targetAmount - currentAmount);
      }
      const months = Math.max(1, Math.round(yearsToGoal * 12));
      const rate = monthlyRate(expectedReturnPct);
      const futureCurrent = currentAmount * Math.pow(1 + rate, months);
      const remaining = targetAmount - futureCurrent;
      if (remaining <= 0) {
        return 0;
      }
      if (Math.abs(rate) < 1e-12) {
        return remaining / months;
      }
      const annuity = (Math.pow(1 + rate, months) - 1) / rate;
      return remaining / annuity;
    }

    function initInputs() {
      ids.adult1Dob.value = baseline.adult_1_date_of_birth;
      ids.adult2Dob.value = baseline.adult_2_date_of_birth;
      ids.retirementAgeAdult1.value = baseline.retirement_age_adult_1;
      ids.retirementAgeAdult2.value = baseline.retirement_age_adult_2;
      ids.pensionAdult1.value = baseline.pension_adult_1_before_tax_eur;
      ids.pensionAdult2.value = baseline.pension_adult_2_before_tax_eur;
      ids.retirementSpending.value = baseline.retirement_spending_before_tax_eur;
      ids.withdrawalRate.value = baseline.withdrawal_rate_pct;
      ids.currentInvestableNetWorth.value = baseline.current_investable_net_worth_eur;
      ids.currentTotalNetWorth.value = baseline.current_total_net_worth_eur;
      ids.currentHomeValue.value = baseline.current_home_value_eur;
      ids.mortgageBalance.value = baseline.current_mortgage_balance_eur;
      ids.mortgageRate.value = baseline.mortgage_annual_rate_pct;
      ids.mortgagePayment.value = baseline.mortgage_monthly_payment_eur;
      ids.mortgageYears.value = baseline.mortgage_years_remaining;
      ids.homeGrowth.value = baseline.inflation_pct;
      ids.kidsFund.value = baseline.kids_target_fund_per_child_eur;
      ids.houseCost.value = baseline.house_project_cost_eur;
      ids.houseYears.value = baseline.house_target_years;
      ids.inflation.value = baseline.inflation_pct;
      ids.growthReturn.value = baseline.growth_return_pct;
      ids.houseReturn.value = baseline.house_return_pct;
      document.getElementById("generated-at").textContent =
        "Generated " + payload.meta.generated_at;
      document.getElementById("income-pill").textContent =
        "Net income " +
        fmtCurrency(baseline.estimated_net_household_income_eur) +
        "/yr";
      document.getElementById("assets-pill").textContent =
        "Financial assets " +
        fmtCurrency(baseline.current_total_financial_assets_eur);
      document.getElementById("mortgage-pill").textContent =
        "Mortgage " + fmtCurrency(baseline.current_mortgage_balance_eur);
    }

    function render() {
      const adult1Dob = ids.adult1Dob.value;
      const adult2Dob = ids.adult2Dob.value;
      const retirementAgeAdult1 = Number(ids.retirementAgeAdult1.value);
      const retirementAgeAdult2 = Number(ids.retirementAgeAdult2.value);
      const pensionAdult1 = Number(ids.pensionAdult1.value);
      const pensionAdult2 = Number(ids.pensionAdult2.value);
      const pension = pensionAdult1 + pensionAdult2;
      const retirementSpending = Number(ids.retirementSpending.value);
      const withdrawalRate = Number(ids.withdrawalRate.value);
      const currentInvestableNetWorth = Number(ids.currentInvestableNetWorth.value);
      const currentTotalNetWorth = Number(ids.currentTotalNetWorth.value);
      const currentHomeValue = Number(ids.currentHomeValue.value);
      const currentMortgageBalance = Number(ids.mortgageBalance.value);
      const mortgageRate = Number(ids.mortgageRate.value);
      const mortgagePayment = Number(ids.mortgagePayment.value);
      const mortgageYears = Number(ids.mortgageYears.value);
      const homeGrowth = Number(ids.homeGrowth.value);
      const kidsFund = Number(ids.kidsFund.value);
      const houseCost = Number(ids.houseCost.value);
      const houseYears = Number(ids.houseYears.value);
      const inflation = Number(ids.inflation.value);
      const growthReturn = Number(ids.growthReturn.value);
      const houseReturn = Number(ids.houseReturn.value);

      ids.retirementAgeAdult1Output.textContent = retirementAgeAdult1 + " years";
      ids.retirementAgeAdult2Output.textContent = retirementAgeAdult2 + " years";
      ids.inflationOutput.textContent = fmtNumber(inflation) + "%";
      ids.growthReturnOutput.textContent = fmtNumber(growthReturn) + "%";
      ids.houseReturnOutput.textContent = fmtNumber(houseReturn) + "%";
      ids.homeGrowthOutput.textContent = fmtNumber(homeGrowth) + "%";

      const yearsToRetirementAdult1 = yearsFromDob(adult1Dob, retirementAgeAdult1);
      const yearsToRetirementAdult2 = yearsFromDob(adult2Dob, retirementAgeAdult2);
      const yearsToRetirement = Math.max(
        0,
        Math.min(yearsToRetirementAdult1, yearsToRetirementAdult2)
      );
      const retirementGapToday = Math.max(0, retirementSpending - pension);
      const retirementGapFuture = inflate(retirementGapToday, yearsToRetirement, inflation);
      const retirementCapital =
        withdrawalRate > 0 ? retirementGapFuture / (withdrawalRate / 100) : 0;
      const retirementMonthly = requiredMonthlyContribution(
        retirementCapital,
        baseline.current_retirement_assets_eur,
        yearsToRetirement,
        growthReturn
      );

      const educationRows = [];
      let educationMonthly = 0;
      baseline.child_ages.forEach((age, index) => {
        const yearsToGoal = Math.max(0, 18 - age);
        const futureTarget = inflate(kidsFund, yearsToGoal, inflation);
        const monthly = requiredMonthlyContribution(
          futureTarget,
          Number(baseline.current_child_funds_eur[index] || 0),
          yearsToGoal,
          growthReturn
        );
        educationMonthly += monthly;
        educationRows.push({
          label: "Child " + (index + 1),
          yearsToGoal,
          futureTarget,
          monthly,
        });
      });

      const houseTargetToday = houseCost * (1 + Number(baseline.house_contingency_pct) / 100);
      const houseTargetFuture = inflate(houseTargetToday, houseYears, inflation);
      const houseMonthly = requiredMonthlyContribution(
        houseTargetFuture,
        baseline.current_house_reserved_eur,
        houseYears,
        houseReturn
      );

      const totalMonthly = retirementMonthly + educationMonthly + houseMonthly;
      const annualSavings = totalMonthly * 12;
      const projectedNetWorthAtRetirement = futureValueOfPortfolio(
        currentInvestableNetWorth,
        totalMonthly,
        yearsToRetirement,
        growthReturn
      );
      const yearsForMortgageProjection = Math.min(yearsToRetirement, mortgageYears);
      const projectedMortgageBalance = projectMortgageBalance(
        currentMortgageBalance,
        mortgageRate,
        mortgagePayment,
        yearsForMortgageProjection
      );
      const projectedHomeValue = inflate(currentHomeValue, yearsToRetirement, homeGrowth);
      const projectedHomeEquity = projectedHomeValue - projectedMortgageBalance;
      const projectedTotalNetWorthAtRetirement =
        projectedNetWorthAtRetirement + projectedHomeEquity;
      const emergencyTarget =
        baseline.essential_monthly_spend_eur *
        baseline.emergency_fund_target_months;
      const availableAnnualCash =
        baseline.estimated_net_household_income_eur -
        baseline.essential_monthly_spend_eur * 12;
      const annualGap = annualSavings - availableAnnualCash;

      document.getElementById("total-monthly").textContent = fmtCurrency(totalMonthly);
      document.getElementById("monthly-vs-income").textContent =
        fmtNumber(
          (annualSavings / baseline.estimated_net_household_income_eur) * 100
        ) + "% of estimated net income";
      document.getElementById("annual-savings").textContent = fmtCurrency(annualSavings);
      document.getElementById("surplus-gap").textContent =
        annualGap > 0
          ? fmtCurrency(annualGap) + " above estimated annual surplus"
          : fmtCurrency(Math.abs(annualGap)) + " below estimated annual surplus";
      document.getElementById("emergency-target").textContent = fmtCurrency(emergencyTarget);
      document.getElementById("retirement-capital").textContent = fmtCurrency(retirementCapital);
      document.getElementById("retirement-gap").textContent =
        "Gap " + fmtCurrency(retirementGapFuture) + "/yr in future euros";
      document.getElementById("retirement-net-worth").textContent =
        fmtCurrency(projectedTotalNetWorthAtRetirement);
      document.getElementById("retirement-net-worth-detail").textContent =
        "Investable assets grow to " +
        fmtCurrency(projectedNetWorthAtRetirement) +
        "; current total net worth set to " +
        fmtCurrency(currentTotalNetWorth) +
        ".";
      document.getElementById("retirement-home-equity").textContent =
        fmtCurrency(projectedHomeEquity);
      document.getElementById("retirement-home-equity-detail").textContent =
        "From home value " +
        fmtCurrency(currentHomeValue) +
        " and mortgage " +
        fmtCurrency(currentMortgageBalance) +
        " today.";

      document.getElementById("retirement-monthly").textContent = fmtCurrency(retirementMonthly);
      document.getElementById("retirement-detail").textContent =
        fmtCurrency(retirementGapToday) +
        "/yr today gap, " +
        fmtNumber(yearsToRetirement, 1) +
        " years to retirement";
      document.getElementById("education-monthly").textContent = fmtCurrency(educationMonthly);
      document.getElementById("education-detail").textContent =
        fmtCurrency(kidsFund) + " target per child, inflation-adjusted";
      document.getElementById("house-monthly").textContent = fmtCurrency(houseMonthly);
      document.getElementById("house-detail").textContent =
        fmtCurrency(houseTargetFuture) +
        " future target over " +
        fmtNumber(houseYears, 1) +
        " years";

      const tbody = document.getElementById("education-table");
      tbody.innerHTML = "";
      educationRows.forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${row.label}</td>
          <td>${fmtNumber(row.yearsToGoal, 1)}</td>
          <td class="right">${fmtCurrency(row.futureTarget)}</td>
          <td class="right">${fmtCurrency(row.monthly)}</td>
        `;
        tbody.appendChild(tr);
      });

      const retirementTbody = document.getElementById("retirement-table");
      retirementTbody.innerHTML = "";
      [
        {
          label: "Adult 1",
          dob: adult1Dob || "n/a",
          retirementAge: retirementAgeAdult1,
          retirementYear: retirementYearFromDob(adult1Dob, retirementAgeAdult1),
          pension: pensionAdult1,
        },
        {
          label: "Adult 2",
          dob: adult2Dob || "n/a",
          retirementAge: retirementAgeAdult2,
          retirementYear: retirementYearFromDob(adult2Dob, retirementAgeAdult2),
          pension: pensionAdult2,
        },
      ].forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${row.label}</td>
          <td>${row.dob}</td>
          <td>${row.retirementAge}</td>
          <td>${row.retirementYear}</td>
          <td class="right">${fmtCurrency(row.pension)}</td>
        `;
        retirementTbody.appendChild(tr);
      });

      const housingTbody = document.getElementById("housing-table");
      housingTbody.innerHTML = "";
      [
        {
          label: "Home value",
          today: currentHomeValue,
          future: projectedHomeValue,
        },
        {
          label: "Mortgage balance",
          today: currentMortgageBalance,
          future: projectedMortgageBalance,
        },
        {
          label: "Home equity",
          today: currentHomeValue - currentMortgageBalance,
          future: projectedHomeEquity,
        },
      ].forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${row.label}</td>
          <td class="right">${fmtCurrency(row.today)}</td>
          <td class="right">${fmtCurrency(row.future)}</td>
        `;
        housingTbody.appendChild(tr);
      });

      const affordability = document.getElementById("affordability");
      const affordabilityNote = document.getElementById("affordability-note");
      const share = annualSavings / baseline.estimated_net_household_income_eur;
      affordability.className =
        "afford " +
        (share <= 0.2 ? "good" : share <= 0.35 ? "warn" : "bad");
      affordability.textContent =
        share <= 0.2
          ? "Comfortable band."
          : share <= 0.35
            ? "Stretch band."
            : "High-pressure band.";
      affordabilityNote.textContent =
        " This scenario implies " + fmtCurrency(totalMonthly) +
        "/month of saving against an estimated annual free cashflow of " +
        fmtCurrency(availableAnnualCash) +
        ", with current total net worth set to " +
        fmtCurrency(currentTotalNetWorth) + ".";
    }

    initInputs();
    Object.values(ids).forEach((element) => element.addEventListener("input", render));
    render();
  </script>
</body>
</html>
"""


def render_planning_hypothesis_html(inputs_path: Path, destination: Path) -> Path:
    """Render a self-contained HTML hypothesis playground from planning inputs."""
    inputs = load_planning_inputs(inputs_path)
    payload = _build_payload(inputs)
    html = _HTML_TEMPLATE.replace("__PAYLOAD_JSON__", _serialize_payload(payload))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination

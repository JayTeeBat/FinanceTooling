# ruff: noqa: E501
"""Self-contained interactive dashboard rendering for workflow outputs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.budgeting import BudgetConfig, budget_targets_to_rows, load_budget_config
from finance_tooling.projecting import (
    ProjectConfig,
    assign_projects_to_dataframe,
    load_project_config,
)


def _to_optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        if isinstance(value, float) and pd.isna(value):
            return None
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _normalize_booking_date(value: object) -> str | None:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, str) and value.strip():
        timestamp = pd.to_datetime(value.strip(), errors="coerce")
        if pd.isna(timestamp):
            return None
        return timestamp.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _to_str_or_default(value: object, *, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _to_str_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _build_transaction_rows(dataframe: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if dataframe.empty:
        return rows

    for raw_row in dataframe.to_dict(orient="records"):
        booking_date = _normalize_booking_date(raw_row.get("booking_date"))
        if booking_date is None:
            continue
        rows.append(
            {
                "booking_date": booking_date,
                "category": _to_str_or_default(
                    _to_str_or_none(raw_row.get("category")), default="Uncategorized"
                ),
                "project": _to_str_or_default(
                    _to_str_or_none(raw_row.get("project")), default="Unassigned"
                ),
                "amount_eur": _to_optional_float(raw_row.get("amount_eur")),
            }
        )

    rows.sort(key=lambda row: str(row["booking_date"]))
    return rows


def _load_projecting(path: Path | None) -> tuple[ProjectConfig, list[str]]:
    if path is None:
        return ProjectConfig(fallback_project="Unassigned", rules=(), overrides=()), []
    return load_project_config(path)


def _load_budgets(path: Path | None) -> tuple[BudgetConfig, list[str]]:
    if path is None:
        return BudgetConfig(currency="EUR", targets=()), []
    return load_budget_config(path)


def _build_dashboard_payload(
    dataframe: pd.DataFrame,
    *,
    base_currency: str,
    files_scanned: int,
    files_failed: int,
    new_rows: int,
    project_rules_path: Path | None,
    budget_targets_path: Path | None,
) -> dict[str, object]:
    project_config, project_warnings = _load_projecting(project_rules_path)
    budget_config, budget_warnings = _load_budgets(budget_targets_path)
    projected = assign_projects_to_dataframe(dataframe, config=project_config)

    payload: dict[str, object] = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "base_currency": base_currency,
            "files_scanned": files_scanned,
            "files_failed": files_failed,
            "new_rows": new_rows,
            "total_rows": len(projected),
            "default_window": "last_12_months",
        },
        "transactions": _build_transaction_rows(projected),
        "budget_targets": budget_targets_to_rows(budget_config),
        "warnings": [*project_warnings, *budget_warnings],
    }
    return payload


def _serialize_payload(payload: dict[str, object]) -> str:
    # Prevent accidental </script> termination in embedded JSON.
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return serialized.replace("</", "<\\/")


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Finance Dashboard</title>
  <style>
    :root {
      --bg-start: #f2f6ff;
      --bg-end: #f9fbff;
      --surface: #ffffff;
      --surface-2: #f5f8ff;
      --text: #162032;
      --muted: #5d6b80;
      --border: #d6deed;
      --accent: #1f4aa3;
      --accent-soft: #d9e5ff;
      --positive: #1f8a4c;
      --negative: #c63f3f;
      --warning-bg: #fff4de;
      --warning-border: #f2c46f;
      --shadow: 0 16px 32px rgba(22, 32, 50, 0.08);
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--text);
      background: linear-gradient(165deg, var(--bg-start), var(--bg-end));
      min-height: 100vh;
    }
    .shell {
      max-width: 1320px;
      margin: 0 auto;
      padding: 22px;
      display: grid;
      gap: 18px;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
      box-shadow: var(--shadow);
    }
    .headline {
      display: grid;
      gap: 8px;
    }
    h1 {
      margin: 0;
      font-family: "IBM Plex Serif", "Georgia", serif;
      font-weight: 600;
      font-size: clamp(26px, 4vw, 34px);
      letter-spacing: -0.01em;
    }
    h2 {
      margin: 0;
      font-size: 20px;
      color: var(--accent);
      letter-spacing: 0.01em;
    }
    p {
      margin: 0;
      color: var(--muted);
    }
    .meta-line {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 13px;
      color: var(--muted);
    }
    .meta-pill {
      padding: 4px 10px;
      border-radius: 999px;
      background: var(--surface-2);
      border: 1px solid var(--border);
    }
    .filters {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      align-items: end;
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .field label {
      font-weight: 600;
      font-size: 13px;
      color: var(--muted);
    }
    .field input,
    .field select,
    .field button {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 14px;
      background: #fff;
      color: var(--text);
    }
    .field select[multiple] {
      min-height: 120px;
    }
    .field button {
      cursor: pointer;
      font-weight: 600;
      background: linear-gradient(135deg, var(--accent), #315fcc);
      color: #fff;
      border: 0;
    }
    .kpis {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }
    .kpi {
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: grid;
      gap: 4px;
    }
    .kpi .label {
      font-size: 12px;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: 0.06em;
      font-weight: 600;
    }
    .kpi .value {
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.02em;
      overflow-wrap: anywhere;
    }
    .layout-two {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 16px;
    }
    .chart-area {
      display: grid;
      gap: 9px;
    }
    .bar-list {
      display: grid;
      gap: 8px;
    }
    .bar-row {
      display: grid;
      grid-template-columns: minmax(92px, 130px) 1fr auto;
      gap: 10px;
      align-items: center;
      font-size: 13px;
    }
    .bar-label {
      color: var(--muted);
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .bar-track {
      height: 16px;
      border-radius: 999px;
      background: #e9eef9;
      overflow: hidden;
      position: relative;
    }
    .bar-fill {
      height: 100%;
      border-radius: 999px;
    }
    .bar-fill.positive {
      background: linear-gradient(90deg, #5bbf80, var(--positive));
    }
    .bar-fill.negative {
      background: linear-gradient(90deg, #ef8e8e, var(--negative));
    }
    .bar-fill.accent {
      background: linear-gradient(90deg, #5d8dff, var(--accent));
    }
    .bar-value {
      font-variant-numeric: tabular-nums;
      font-weight: 600;
      font-size: 12px;
      color: var(--text);
    }
    .yoy-row {
      display: grid;
      grid-template-columns: 56px 1fr;
      gap: 10px;
      align-items: center;
      font-size: 13px;
    }
    .yoy-bars {
      display: grid;
      gap: 5px;
    }
    .yoy-series {
      display: grid;
      grid-template-columns: 38px 1fr auto;
      gap: 8px;
      align-items: center;
    }
    .series-label {
      color: var(--muted);
      font-weight: 600;
      font-size: 12px;
      text-align: right;
    }
    .table-wrap {
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 12px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }
    th,
    td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      font-size: 13px;
    }
    th {
      background: #f5f8ff;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-size: 12px;
    }
    .status-on {
      color: var(--positive);
      font-weight: 700;
    }
    .status-over {
      color: var(--negative);
      font-weight: 700;
    }
    .warning-box {
      border: 1px solid var(--warning-border);
      background: var(--warning-bg);
      border-radius: 12px;
      padding: 12px;
      display: none;
      gap: 6px;
    }
    .warning-box strong {
      font-size: 14px;
    }
    .warning-box ul {
      margin: 0;
      padding-left: 20px;
      color: #7b5a1e;
      font-size: 13px;
      display: grid;
      gap: 3px;
    }
    .empty {
      color: var(--muted);
      font-size: 13px;
      padding: 8px 0;
    }
    @media (max-width: 720px) {
      .shell {
        padding: 12px;
      }
      .bar-row {
        grid-template-columns: 82px 1fr auto;
      }
      table {
        min-width: 640px;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="card headline">
      <h1>Interactive Finance Dashboard</h1>
      <p id="generated-at">Generated -</p>
      <div class="meta-line" id="run-meta"></div>
    </section>

    <section class="card">
      <h2>Filters</h2>
      <p>Date range, category, and project filters apply to all charts and tables.</p>
      <div class="filters" style="margin-top: 10px;">
        <div class="field">
          <label for="start-date">Start Date</label>
          <input id="start-date" type="date" />
        </div>
        <div class="field">
          <label for="end-date">End Date</label>
          <input id="end-date" type="date" />
        </div>
        <div class="field">
          <label for="category-select">Category (multi-select)</label>
          <select id="category-select" multiple></select>
        </div>
        <div class="field">
          <label for="project-select">Project (multi-select)</label>
          <select id="project-select" multiple></select>
        </div>
        <div class="field">
          <label for="yoy-year">YoY Year</label>
          <select id="yoy-year"></select>
        </div>
        <div class="field">
          <label for="reset-filters">Reset Filters</label>
          <button id="reset-filters" type="button">Reset to Last 12 Months</button>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Key Metrics</h2>
      <div class="kpis" style="margin-top: 10px;">
        <article class="kpi"><span class="label">Income</span><span class="value" id="kpi-income">-</span></article>
        <article class="kpi"><span class="label">Expense</span><span class="value" id="kpi-expense">-</span></article>
        <article class="kpi"><span class="label">Net</span><span class="value" id="kpi-net">-</span></article>
        <article class="kpi"><span class="label">Transactions</span><span class="value" id="kpi-tx-count">-</span></article>
        <article class="kpi"><span class="label">Budget Month</span><span class="value" id="kpi-budget-month">-</span></article>
        <article class="kpi"><span class="label">Budget Variance</span><span class="value" id="kpi-budget-variance">-</span></article>
      </div>
    </section>

    <section class="layout-two">
      <article class="card chart-area">
        <h2>Monthly Net Trend</h2>
        <div id="monthly-net-chart" class="bar-list"></div>
      </article>
      <article class="card chart-area">
        <h2>Spending by Category</h2>
        <div id="category-spend-chart" class="bar-list"></div>
      </article>
    </section>

    <section class="layout-two">
      <article class="card chart-area">
        <h2>Year-over-Year Spending</h2>
        <div id="yoy-chart" class="bar-list"></div>
      </article>
      <article class="card chart-area">
        <h2>Budget Variance by Target</h2>
        <div id="budget-variance-chart" class="bar-list"></div>
      </article>
    </section>

    <section class="card">
      <h2>Budget Status</h2>
      <div class="table-wrap" style="margin-top: 10px;">
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th>Category</th>
              <th>Project</th>
              <th>Budget</th>
              <th>Actual</th>
              <th>Variance</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="budget-table-body"></tbody>
        </table>
      </div>
    </section>

    <section class="warning-box" id="warning-box">
      <strong>Configuration warnings</strong>
      <ul id="warning-list"></ul>
    </section>
  </div>

  <script id="dashboard-data" type="application/json">__PAYLOAD_JSON__</script>
  <script>
    (function () {
      "use strict";

      function parsePayload() {
        const node = document.getElementById("dashboard-data");
        if (!node) {
          return { meta: {}, transactions: [], budget_targets: [], warnings: [] };
        }
        try {
          const parsed = JSON.parse(node.textContent || "{}");
          return {
            meta: parsed.meta || {},
            transactions: Array.isArray(parsed.transactions) ? parsed.transactions : [],
            budget_targets: Array.isArray(parsed.budget_targets) ? parsed.budget_targets : [],
            warnings: Array.isArray(parsed.warnings) ? parsed.warnings : [],
          };
        } catch (error) {
          console.error("Failed to parse embedded dashboard payload", error);
          return { meta: {}, transactions: [], budget_targets: [], warnings: ["Invalid payload"] };
        }
      }

      function parseDate(value) {
        if (typeof value !== "string" || value.length !== 10) {
          return null;
        }
        const parsed = new Date(value + "T00:00:00Z");
        if (Number.isNaN(parsed.getTime())) {
          return null;
        }
        return parsed;
      }

      function formatDate(value) {
        return value.toISOString().slice(0, 10);
      }

      function monthKey(dateValue) {
        return dateValue.slice(0, 7);
      }

      function monthKeysBetween(startDate, endDate) {
        const start = parseDate(startDate);
        const end = parseDate(endDate);
        if (!start || !end || start > end) {
          return [];
        }
        const cursor = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), 1));
        const endMonth = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), 1));
        const months = [];
        while (cursor <= endMonth) {
          months.push(
            cursor.toISOString().slice(0, 7)
          );
          cursor.setUTCMonth(cursor.getUTCMonth() + 1);
        }
        return months;
      }

      function escapeHtml(value) {
        return String(value)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }

      function uniqueSorted(values) {
        return Array.from(new Set(values.filter(Boolean))).sort((left, right) =>
          String(left).localeCompare(String(right))
        );
      }

      function selectedSet(selectNode) {
        const values = [];
        for (const option of Array.from(selectNode.options)) {
          if (option.selected) {
            values.push(option.value);
          }
        }
        return new Set(values);
      }

      function toNumber(value) {
        if (typeof value === "number" && Number.isFinite(value)) {
          return value;
        }
        if (typeof value === "string") {
          const parsed = Number(value);
          if (Number.isFinite(parsed)) {
            return parsed;
          }
        }
        return null;
      }

      const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      const payload = parsePayload();
      const baseCurrency = typeof payload.meta.base_currency === "string" && payload.meta.base_currency
        ? payload.meta.base_currency
        : "EUR";
      const money = new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: baseCurrency,
        maximumFractionDigits: 2,
      });

      const transactions = payload.transactions
        .map((item) => {
          const bookingDate = typeof item.booking_date === "string" ? item.booking_date : "";
          if (!parseDate(bookingDate)) {
            return null;
          }
          return {
            bookingDate: bookingDate,
            month: monthKey(bookingDate),
            category: typeof item.category === "string" && item.category.trim()
              ? item.category.trim()
              : "Uncategorized",
            project: typeof item.project === "string" && item.project.trim()
              ? item.project.trim()
              : "Unassigned",
            amountEur: toNumber(item.amount_eur),
          };
        })
        .filter((item) => item !== null);

      transactions.sort((left, right) => left.bookingDate.localeCompare(right.bookingDate));

      const budgetTargets = payload.budget_targets
        .map((item) => {
          const month = typeof item.month === "string" ? item.month : "";
          const category = typeof item.category === "string" ? item.category.trim() : "";
          const project = typeof item.project === "string" && item.project.trim() ? item.project.trim() : null;
          const amount = toNumber(item.amount);
          if (!month || !category || amount === null || amount <= 0) {
            return null;
          }
          return { month, category, project, amount };
        })
        .filter((item) => item !== null);

      const startInput = document.getElementById("start-date");
      const endInput = document.getElementById("end-date");
      const categorySelect = document.getElementById("category-select");
      const projectSelect = document.getElementById("project-select");
      const yoyYearSelect = document.getElementById("yoy-year");
      const resetButton = document.getElementById("reset-filters");
      const monthlyNetChart = document.getElementById("monthly-net-chart");
      const categorySpendChart = document.getElementById("category-spend-chart");
      const yoyChart = document.getElementById("yoy-chart");
      const budgetVarianceChart = document.getElementById("budget-variance-chart");
      const budgetTableBody = document.getElementById("budget-table-body");

      const minDate = transactions.length > 0 ? transactions[0].bookingDate : formatDate(new Date());
      const maxDate = transactions.length > 0 ? transactions[transactions.length - 1].bookingDate : formatDate(new Date());

      function defaultRange() {
        if (transactions.length === 0) {
          return { startDate: minDate, endDate: maxDate };
        }
        const maxParsed = parseDate(maxDate);
        if (!maxParsed) {
          return { startDate: minDate, endDate: maxDate };
        }
        const proposedStart = new Date(Date.UTC(maxParsed.getUTCFullYear(), maxParsed.getUTCMonth() - 11, 1));
        const proposedStartString = formatDate(proposedStart);
        return {
          startDate: proposedStartString > minDate ? proposedStartString : minDate,
          endDate: maxDate,
        };
      }

      function renderMeta() {
        const generatedAtNode = document.getElementById("generated-at");
        const runMeta = document.getElementById("run-meta");
        generatedAtNode.textContent = "Generated " + (payload.meta.generated_at || "unknown");
        const pills = [
          "Base currency: " + baseCurrency,
          "Files scanned: " + String(payload.meta.files_scanned || 0),
          "Files failed: " + String(payload.meta.files_failed || 0),
          "New rows: " + String(payload.meta.new_rows || 0),
          "Total rows: " + String(payload.meta.total_rows || transactions.length),
        ];
        runMeta.innerHTML = pills.map((value) => "<span class=\\"meta-pill\\">" + escapeHtml(value) + "</span>").join("");
      }

      function renderWarnings() {
        const warningBox = document.getElementById("warning-box");
        const warningList = document.getElementById("warning-list");
        if (!warningBox || !warningList) {
          return;
        }
        if (!payload.warnings.length) {
          warningBox.style.display = "none";
          warningList.innerHTML = "";
          return;
        }
        warningList.innerHTML = payload.warnings.map((warning) => "<li>" + escapeHtml(warning) + "</li>").join("");
        warningBox.style.display = "grid";
      }

      function fillMultiSelect(selectNode, values) {
        selectNode.innerHTML = values
          .map((value) => "<option value=\\"" + escapeHtml(value) + "\\">" + escapeHtml(value) + "</option>")
          .join("");
      }

      function filterTransactions(state) {
        return transactions.filter((tx) => {
          if (tx.bookingDate < state.startDate || tx.bookingDate > state.endDate) {
            return false;
          }
          if (state.categories.size > 0 && !state.categories.has(tx.category)) {
            return false;
          }
          if (state.projects.size > 0 && !state.projects.has(tx.project)) {
            return false;
          }
          return true;
        });
      }

      function aggregateMonthlyNet(filtered, state) {
        const totals = new Map();
        for (const tx of filtered) {
          if (tx.amountEur === null) {
            continue;
          }
          const existing = totals.get(tx.month) || 0;
          totals.set(tx.month, existing + tx.amountEur);
        }
        return monthKeysBetween(state.startDate, state.endDate).map((month) => ({
          month,
          value: totals.get(month) || 0,
        }));
      }

      function aggregateCategorySpend(filtered) {
        const totals = new Map();
        for (const tx of filtered) {
          if (tx.amountEur === null || tx.amountEur >= 0) {
            continue;
          }
          const existing = totals.get(tx.category) || 0;
          totals.set(tx.category, existing + Math.abs(tx.amountEur));
        }
        const rows = Array.from(totals.entries()).map(([category, value]) => ({ category, value }));
        rows.sort((left, right) => right.value - left.value || left.category.localeCompare(right.category));
        return rows.slice(0, 12);
      }

      function collectYears(filtered) {
        const years = new Set();
        for (const tx of filtered) {
          if (tx.amountEur === null || tx.amountEur >= 0) {
            continue;
          }
          years.add(Number(tx.bookingDate.slice(0, 4)));
        }
        return Array.from(years)
          .filter((value) => Number.isFinite(value))
          .sort((left, right) => left - right);
      }

      function syncYearOptions(years) {
        const previous = Number(yoyYearSelect.value);
        yoyYearSelect.innerHTML = years
          .map((year) => "<option value=\\"" + String(year) + "\\">" + String(year) + "</option>")
          .join("");
        if (!years.length) {
          return null;
        }
        const selected = years.includes(previous) ? previous : years[years.length - 1];
        yoyYearSelect.value = String(selected);
        return selected;
      }

      function aggregateYoY(filtered, selectedYear) {
        if (selectedYear === null) {
          return [];
        }
        const current = new Array(12).fill(0);
        const previous = new Array(12).fill(0);
        for (const tx of filtered) {
          if (tx.amountEur === null || tx.amountEur >= 0) {
            continue;
          }
          const year = Number(tx.bookingDate.slice(0, 4));
          const month = Number(tx.bookingDate.slice(5, 7)) - 1;
          if (month < 0 || month > 11) {
            continue;
          }
          const spend = Math.abs(tx.amountEur);
          if (year === selectedYear) {
            current[month] += spend;
          } else if (year === selectedYear - 1) {
            previous[month] += spend;
          }
        }
        return monthNames.map((label, index) => ({
          month: label,
          current: current[index],
          previous: previous[index],
        }));
      }

      function buildBudgetRows(filtered, state) {
        const categoryActual = new Map();
        const projectActual = new Map();
        for (const tx of filtered) {
          if (tx.amountEur === null || tx.amountEur >= 0) {
            continue;
          }
          const spend = Math.abs(tx.amountEur);
          const categoryKey = tx.month + "||" + tx.category.toLowerCase();
          categoryActual.set(categoryKey, (categoryActual.get(categoryKey) || 0) + spend);
          const projectKey = tx.month + "||" + tx.category.toLowerCase() + "||" + tx.project.toLowerCase();
          projectActual.set(projectKey, (projectActual.get(projectKey) || 0) + spend);
        }

        const startMonth = state.startDate.slice(0, 7);
        const endMonth = state.endDate.slice(0, 7);
        const rows = [];
        for (const target of budgetTargets) {
          if (target.month < startMonth || target.month > endMonth) {
            continue;
          }
          if (state.categories.size > 0 && !state.categories.has(target.category)) {
            continue;
          }
          if (state.projects.size > 0 && target.project && !state.projects.has(target.project)) {
            continue;
          }

          const categoryKey = target.month + "||" + target.category.toLowerCase();
          const projectKey = categoryKey + "||" + (target.project ? target.project.toLowerCase() : "");
          const actual = target.project
            ? (projectActual.get(projectKey) || 0)
            : (categoryActual.get(categoryKey) || 0);
          const variance = target.amount - actual;
          rows.push({
            month: target.month,
            category: target.category,
            project: target.project,
            budget: target.amount,
            actual: actual,
            variance: variance,
            status: actual <= target.amount ? "On Track" : "Over Budget",
          });
        }

        rows.sort((left, right) => {
          if (left.month !== right.month) {
            return left.month.localeCompare(right.month);
          }
          if (left.category !== right.category) {
            return left.category.localeCompare(right.category);
          }
          return (left.project || "").localeCompare(right.project || "");
        });
        return rows;
      }

      function setKpi(id, value) {
        const node = document.getElementById(id);
        if (node) {
          node.textContent = value;
        }
      }

      function renderBarRows(container, rows, formatValue, classForValue) {
        if (!rows.length) {
          container.innerHTML = "<p class=\\"empty\\">No data for the current filters.</p>";
          return;
        }
        const maxAbs = Math.max(
          ...rows.map((row) => {
            const value = typeof row.value === "number" ? row.value : 0;
            return Math.abs(value);
          }),
          1
        );
        container.innerHTML = rows
          .map((row) => {
            const value = typeof row.value === "number" ? row.value : 0;
            const width = Math.max(2, (Math.abs(value) / maxAbs) * 100);
            return (
              "<div class=\\"bar-row\\">" +
                "<span class=\\"bar-label\\" title=\\"" + escapeHtml(row.label) + "\\">" + escapeHtml(row.label) + "</span>" +
                "<div class=\\"bar-track\\"><div class=\\"bar-fill " + classForValue(value) + "\\" style=\\"width:" + width.toFixed(2) + "%\\"></div></div>" +
                "<span class=\\"bar-value\\">" + escapeHtml(formatValue(value)) + "</span>" +
              "</div>"
            );
          })
          .join("");
      }

      function renderYoY(rows, selectedYear) {
        if (!rows.length || selectedYear === null) {
          yoyChart.innerHTML = "<p class=\\"empty\\">No expense data available for YoY view.</p>";
          return;
        }
        const maxValue = Math.max(
          ...rows.flatMap((row) => [row.current, row.previous]),
          1
        );
        yoyChart.innerHTML = rows
          .map((row) => {
            const currentWidth = Math.max(2, (row.current / maxValue) * 100);
            const previousWidth = Math.max(2, (row.previous / maxValue) * 100);
            return (
              "<div class=\\"yoy-row\\">" +
                "<span class=\\"bar-label\\">" + escapeHtml(row.month) + "</span>" +
                "<div class=\\"yoy-bars\\">" +
                  "<div class=\\"yoy-series\\">" +
                    "<span class=\\"series-label\\">" + String(selectedYear) + "</span>" +
                    "<div class=\\"bar-track\\"><div class=\\"bar-fill accent\\" style=\\"width:" + currentWidth.toFixed(2) + "%\\"></div></div>" +
                    "<span class=\\"bar-value\\">" + escapeHtml(money.format(row.current)) + "</span>" +
                  "</div>" +
                  "<div class=\\"yoy-series\\">" +
                    "<span class=\\"series-label\\">" + String(selectedYear - 1) + "</span>" +
                    "<div class=\\"bar-track\\"><div class=\\"bar-fill positive\\" style=\\"width:" + previousWidth.toFixed(2) + "%\\"></div></div>" +
                    "<span class=\\"bar-value\\">" + escapeHtml(money.format(row.previous)) + "</span>" +
                  "</div>" +
                "</div>" +
              "</div>"
            );
          })
          .join("");
      }

      function renderBudgetTable(rows) {
        if (!rows.length) {
          budgetTableBody.innerHTML = "<tr><td colspan=\\"7\\"><span class=\\"empty\\">No budget rows for the current filters.</span></td></tr>";
          return;
        }
        budgetTableBody.innerHTML = rows
          .map((row) => {
            const statusClass = row.status === "On Track" ? "status-on" : "status-over";
            return (
              "<tr>" +
                "<td>" + escapeHtml(row.month) + "</td>" +
                "<td>" + escapeHtml(row.category) + "</td>" +
                "<td>" + escapeHtml(row.project || "All Projects") + "</td>" +
                "<td>" + escapeHtml(money.format(row.budget)) + "</td>" +
                "<td>" + escapeHtml(money.format(row.actual)) + "</td>" +
                "<td>" + escapeHtml(money.format(row.variance)) + "</td>" +
                "<td class=\\"" + statusClass + "\\">" + escapeHtml(row.status) + "</td>" +
              "</tr>"
            );
          })
          .join("");
      }

      function refreshDashboard() {
        const state = {
          startDate: startInput.value || minDate,
          endDate: endInput.value || maxDate,
          categories: selectedSet(categorySelect),
          projects: selectedSet(projectSelect),
        };
        if (state.startDate > state.endDate) {
          state.endDate = state.startDate;
          endInput.value = state.endDate;
        }

        const filtered = filterTransactions(state);
        let income = 0;
        let expense = 0;
        let net = 0;
        for (const tx of filtered) {
          if (tx.amountEur === null) {
            continue;
          }
          net += tx.amountEur;
          if (tx.amountEur >= 0) {
            income += tx.amountEur;
          } else {
            expense += Math.abs(tx.amountEur);
          }
        }

        setKpi("kpi-income", money.format(income));
        setKpi("kpi-expense", money.format(expense));
        setKpi("kpi-net", money.format(net));
        setKpi("kpi-tx-count", String(filtered.length));

        const monthlyRows = aggregateMonthlyNet(filtered, state).map((row) => ({
          label: row.month,
          value: row.value,
        }));
        renderBarRows(
          monthlyNetChart,
          monthlyRows,
          (value) => money.format(value),
          (value) => (value < 0 ? "negative" : "positive")
        );

        const categoryRows = aggregateCategorySpend(filtered).map((row) => ({
          label: row.category,
          value: row.value,
        }));
        renderBarRows(
          categorySpendChart,
          categoryRows,
          (value) => money.format(value),
          function () {
            return "accent";
          }
        );

        const years = collectYears(filtered);
        const selectedYear = syncYearOptions(years);
        renderYoY(aggregateYoY(filtered, selectedYear), selectedYear);

        const budgetRows = buildBudgetRows(filtered, state);
        renderBudgetTable(budgetRows);

        const varianceRows = budgetRows.map((row) => ({
          label: row.month + " " + row.category + (row.project ? " / " + row.project : ""),
          value: row.variance,
        }));
        renderBarRows(
          budgetVarianceChart,
          varianceRows.slice(0, 12),
          (value) => money.format(value),
          (value) => (value < 0 ? "negative" : "positive")
        );

        if (!budgetRows.length) {
          setKpi("kpi-budget-month", "-");
          setKpi("kpi-budget-variance", "-");
        } else {
          const latestMonth = budgetRows[budgetRows.length - 1].month;
          const monthRows = budgetRows.filter((row) => row.month === latestMonth);
          const monthVariance = monthRows.reduce((sum, row) => sum + row.variance, 0);
          setKpi("kpi-budget-month", latestMonth);
          setKpi("kpi-budget-variance", money.format(monthVariance));
        }
      }

      function initializeFilters() {
        startInput.min = minDate;
        startInput.max = maxDate;
        endInput.min = minDate;
        endInput.max = maxDate;

        fillMultiSelect(categorySelect, uniqueSorted(transactions.map((tx) => tx.category)));
        fillMultiSelect(projectSelect, uniqueSorted(transactions.map((tx) => tx.project)));

        const defaults = defaultRange();
        startInput.value = defaults.startDate;
        endInput.value = defaults.endDate;

        resetButton.addEventListener("click", function () {
          const range = defaultRange();
          startInput.value = range.startDate;
          endInput.value = range.endDate;
          for (const option of Array.from(categorySelect.options)) {
            option.selected = false;
          }
          for (const option of Array.from(projectSelect.options)) {
            option.selected = false;
          }
          refreshDashboard();
        });

        for (const node of [startInput, endInput, categorySelect, projectSelect, yoyYearSelect]) {
          node.addEventListener("change", refreshDashboard);
        }
      }

      renderMeta();
      renderWarnings();
      initializeFilters();
      refreshDashboard();
    })();
  </script>
</body>
</html>
"""


def render_dashboard_html(
    dataframe: pd.DataFrame,
    destination: Path,
    *,
    base_currency: str,
    files_scanned: int,
    files_failed: int,
    new_rows: int,
    project_rules_path: Path | None = None,
    budget_targets_path: Path | None = None,
) -> Path:
    """Render a self-contained interactive HTML dashboard."""
    payload = _build_dashboard_payload(
        dataframe,
        base_currency=base_currency,
        files_scanned=files_scanned,
        files_failed=files_failed,
        new_rows=new_rows,
        project_rules_path=project_rules_path,
        budget_targets_path=budget_targets_path,
    )
    html = _HTML_TEMPLATE.replace("__PAYLOAD_JSON__", _serialize_payload(payload))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination

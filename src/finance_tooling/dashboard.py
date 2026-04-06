# ruff: noqa: E501
"""Self-contained interactive dashboard rendering for workflow outputs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.budgeting import BudgetConfig, budget_targets_to_rows, load_budget_config
from finance_tooling.cashflow import build_cashflow_rows_frame, build_cashflow_yoy_summary
from finance_tooling.projecting import (
    ProjectConfig,
    assign_projects_to_dataframe,
    load_project_config,
)


def _normalized_string_series(dataframe: pd.DataFrame, column: str, *, default: str) -> pd.Series:
    values = dataframe[column].astype("string").str.strip()
    return values.mask(values.isna() | values.eq(""), default)


def _build_transaction_rows_frame(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return pd.DataFrame(
            columns=[
                "booking_date",
                "category",
                "project",
                "amount_eur",
                "cashflow_type",
                "is_transfer",
                "tracked_savings",
                "neutral_transfer",
            ]
        )

    working = build_cashflow_rows_frame(dataframe)
    if working.empty:
        return pd.DataFrame(
            columns=[
                "booking_date",
                "category",
                "project",
                "amount_eur",
                "cashflow_type",
                "is_transfer",
                "tracked_savings",
                "neutral_transfer",
            ]
        )

    working["project"] = _normalized_string_series(working, "project", default="Unassigned")
    amounts = pd.to_numeric(working["amount_eur"], errors="coerce")
    working["amount_eur"] = amounts.astype(object)
    working.loc[amounts.isna(), "amount_eur"] = None
    working["is_transfer"] = working["category"].str.casefold().eq("transfers")

    return working[
        [
            "booking_date",
            "category",
            "project",
            "amount_eur",
            "cashflow_type",
            "is_transfer",
            "tracked_savings",
            "neutral_transfer",
        ]
    ].sort_values("booking_date", kind="stable", ignore_index=True)


def _build_transaction_rows(dataframe: pd.DataFrame) -> list[dict[str, object]]:
    rows_frame = _build_transaction_rows_frame(dataframe)
    return rows_frame.to_dict(orient="records")


def _build_cashflow_diagnostic_warnings(dataframe: pd.DataFrame) -> list[str]:
    rows_frame = build_cashflow_rows_frame(dataframe)
    if rows_frame.empty or "cashflow_type" not in rows_frame.columns:
        return []

    warnings: list[str] = []
    unknown_mask = rows_frame["cashflow_type"].astype("string").str.casefold().eq("unknown")
    unknown_count = int(unknown_mask.sum())
    if unknown_count > 0:
        unknown_categories = sorted(
            {
                str(category).strip() or "Uncategorized"
                for category in rows_frame.loc[unknown_mask, "category"].astype("string").fillna("")
            }
        )
        preview_categories = unknown_categories[:5]
        if len(unknown_categories) > 5:
            preview_categories.append(f"+{len(unknown_categories) - 5} more")
        category_list = ", ".join(preview_categories)
        transaction_word = "transaction" if unknown_count == 1 else "transactions"
        warnings.append(
            f"Cashflow type unresolved for {unknown_count} {transaction_word} across: {category_list}"
        )

    exclude_mask = rows_frame["cashflow_type"].astype("string").str.casefold().eq("exclude")
    exclude_count = int(exclude_mask.sum())
    if exclude_count > 0:
        exclude_categories = sorted(
            {
                str(category).strip() or "Uncategorized"
                for category in rows_frame.loc[exclude_mask, "category"].astype("string").fillna("")
            }
        )
        preview_categories = exclude_categories[:5]
        if len(exclude_categories) > 5:
            preview_categories.append(f"+{len(exclude_categories) - 5} more")
        category_list = ", ".join(preview_categories)
        transaction_word = "transaction" if exclude_count == 1 else "transactions"
        warnings.append(
            f"Cashflow type exclude applies to {exclude_count} {transaction_word} across: {category_list}"
        )

    return warnings


def _build_account_diagnostic_warnings(dataframe: pd.DataFrame) -> list[str]:
    if dataframe.empty or (
        "from_account_type" not in dataframe.columns and "to_account_type" not in dataframe.columns
    ):
        return []

    from_type = (
        dataframe.get("from_account_type", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    to_type = (
        dataframe.get("to_account_type", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    unknown_mask = from_type.isin(("", "unknown")) | to_type.isin(("", "unknown"))
    unknown_count = int(unknown_mask.sum())
    if unknown_count == 0:
        return []

    source_series = (
        dataframe.get(
            "account_inference_source", pd.Series("", index=dataframe.index, dtype="object")
        )
        .astype("string")
        .fillna("")
        .str.strip()
        .replace("", "unknown")
    )
    source_counts = {
        str(index): int(value)
        for index, value in source_series.loc[unknown_mask].value_counts().items()
    }
    summary = ", ".join(f"{key}={value}" for key, value in sorted(source_counts.items()))
    transaction_word = "transaction" if unknown_count == 1 else "transactions"
    return [f"Account boundary unresolved for {unknown_count} {transaction_word}; sources: {summary}"]


def _build_account_transfer_diagnostic_warnings(dataframe: pd.DataFrame) -> list[str]:
    if dataframe.empty:
        return []

    from_type = (
        dataframe.get("from_account_type", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    to_type = (
        dataframe.get("to_account_type", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    cashflow_type = (
        dataframe.get("cashflow_type", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    category = (
        dataframe.get("category", pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
        .str.casefold()
    )
    boundary_transfer_mask = (
        from_type.eq("internal") & to_type.eq("internal") & cashflow_type.eq("transfer")
    )
    override_count = int(boundary_transfer_mask.sum())
    if override_count == 0:
        return []

    conflict_count = int((boundary_transfer_mask & ~category.eq("transfers")).sum())
    transaction_word = "transaction" if override_count == 1 else "transactions"
    warnings = [
        f"Account boundary reclassified {override_count} internal-to-internal {transaction_word} as transfer"
    ]
    if conflict_count > 0:
        warnings.append(
            f"Account boundary transfer conflicts remain on {conflict_count} categorized rows"
        )
    return warnings


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
        "cashflow_yoy": build_cashflow_yoy_summary(projected),
        "warnings": [
            *project_warnings,
            *budget_warnings,
            *_build_cashflow_diagnostic_warnings(projected),
            *_build_account_diagnostic_warnings(projected),
            *_build_account_transfer_diagnostic_warnings(projected),
        ],
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
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }
    .cashflow-grid {
      grid-template-columns: minmax(620px, 1.8fr) minmax(280px, 1fr);
      align-items: start;
    }
    .summary-card {
      display: grid;
      gap: 10px;
    }
    .cashflow-table table {
      min-width: 0;
    }
    .summary-note {
      font-size: 13px;
      color: var(--muted);
    }
    .metric-line {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      color: var(--text);
    }
    .metric-line span:first-child {
      color: var(--muted);
    }
    .delta-positive {
      color: var(--positive);
      font-weight: 600;
    }
    .delta-negative {
      color: var(--negative);
      font-weight: 600;
    }
    .delta-neutral {
      color: var(--muted);
      font-weight: 600;
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
    @media (max-width: 980px) {
      .cashflow-grid {
        grid-template-columns: 1fr;
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
      <h2>Year-over-Year Cashflow</h2>
      <p class="summary-note">Full-year rows include completed calendar years only. The current year appears separately as YTD and this section does not change with the time-window filters below.</p>
      <div class="summary-grid cashflow-grid" style="margin-top: 10px;">
        <article class="summary-card">
          <div class="table-wrap cashflow-table">
            <table>
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Income</th>
                  <th>Expenses</th>
                  <th>Net Cashflow</th>
                  <th>Margin</th>
                </tr>
              </thead>
              <tbody id="cashflow-yoy-body"></tbody>
            </table>
          </div>
        </article>
        <article class="summary-card" id="cashflow-ytd-card"></article>
      </div>
    </section>

    <section class="card">
      <h2>Filters</h2>
      <p>Date window, category, and project filters apply to all charts and tables.</p>
      <div class="filters" style="margin-top: 10px;">
        <div class="field">
          <label for="window-select">Display Window</label>
          <select id="window-select">
            <option value="last_12_months">Last 12 Months</option>
            <option value="last_3_years">Last 3 Years</option>
            <option value="last_5_years">Last 5 Years</option>
            <option value="last_10_years">Last 10 Years</option>
            <option value="full_history">Full History</option>
            <option value="specific_year">Specific Year</option>
            <option value="custom">Custom Range</option>
          </select>
        </div>
        <div class="field">
          <label for="specific-year">Specific Year</label>
          <select id="specific-year"></select>
        </div>
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
        <article class="kpi"><span class="label">Transfers</span><span class="value" id="kpi-transfers">-</span></article>
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
        <p class="empty">YoY uses full selected years and category/project filters.</p>
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
      <strong>Diagnostics</strong>
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
          return { meta: {}, transactions: [], budget_targets: [], cashflow_yoy: {}, warnings: [] };
        }
        try {
          const parsed = JSON.parse(node.textContent || "{}");
          return {
            meta: parsed.meta || {},
            transactions: Array.isArray(parsed.transactions) ? parsed.transactions : [],
            budget_targets: Array.isArray(parsed.budget_targets) ? parsed.budget_targets : [],
            cashflow_yoy: parsed.cashflow_yoy || {},
            warnings: Array.isArray(parsed.warnings) ? parsed.warnings : [],
          };
        } catch (error) {
          console.error("Failed to parse embedded dashboard payload", error);
          return {
            meta: {},
            transactions: [],
            budget_targets: [],
            cashflow_yoy: {},
            warnings: ["Invalid payload"],
          };
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
            cashflowType: typeof item.cashflow_type === "string" ? item.cashflow_type.trim().toLowerCase() : "unknown",
            isTransfer: Boolean(item.is_transfer) || (typeof item.category === "string" && item.category.trim().toLowerCase() === "transfers"),
            trackedSavings: Boolean(item.tracked_savings),
            neutralTransfer: Boolean(item.neutral_transfer),
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
      const windowSelect = document.getElementById("window-select");
      const specificYearSelect = document.getElementById("specific-year");
      const categorySelect = document.getElementById("category-select");
      const projectSelect = document.getElementById("project-select");
      const yoyYearSelect = document.getElementById("yoy-year");
      const resetButton = document.getElementById("reset-filters");
      const monthlyNetChart = document.getElementById("monthly-net-chart");
      const categorySpendChart = document.getElementById("category-spend-chart");
      const yoyChart = document.getElementById("yoy-chart");
      const budgetVarianceChart = document.getElementById("budget-variance-chart");
      const budgetTableBody = document.getElementById("budget-table-body");
      const cashflowYoyBody = document.getElementById("cashflow-yoy-body");
      const cashflowYtdCard = document.getElementById("cashflow-ytd-card");

      const minDate = transactions.length > 0 ? transactions[0].bookingDate : formatDate(new Date());
      const maxDate = transactions.length > 0 ? transactions[transactions.length - 1].bookingDate : formatDate(new Date());
      const allowedWindows = new Set([
        "last_12_months",
        "last_3_years",
        "last_5_years",
        "last_10_years",
        "full_history",
        "specific_year",
        "custom",
      ]);
      const dataYears = Array.from(
        new Set(
          transactions
            .map((tx) => Number(tx.bookingDate.slice(0, 4)))
            .filter((value) => Number.isFinite(value))
        )
      ).sort((left, right) => left - right);

      function clampDateRange(startDate, endDate) {
        let nextStart = startDate;
        let nextEnd = endDate;
        if (nextStart < minDate) {
          nextStart = minDate;
        }
        if (nextEnd > maxDate) {
          nextEnd = maxDate;
        }
        if (nextStart > nextEnd) {
          nextStart = minDate;
          nextEnd = maxDate;
        }
        return { startDate: nextStart, endDate: nextEnd };
      }

      function normalizeCustomFullYearRange(startDate, endDate) {
        if (windowSelect.value !== "custom") {
          return { startDate, endDate };
        }
        const startMatch = /^(\\d{4})-01-01$/.exec(startDate);
        const endMatch = /^(\\d{4})-01-01$/.exec(endDate);
        if (!startMatch || !endMatch) {
          return { startDate, endDate };
        }
        const startYear = Number(startMatch[1]);
        const endYear = Number(endMatch[1]);
        if (!Number.isFinite(startYear) || !Number.isFinite(endYear) || endYear !== startYear + 1) {
          return { startDate, endDate };
        }
        return {
          startDate,
          endDate: String(startYear) + "-12-31",
        };
      }

      function rangeForLastMonths(monthCount) {
        if (transactions.length === 0) {
          return { startDate: minDate, endDate: maxDate };
        }
        const maxParsed = parseDate(maxDate);
        if (!maxParsed) {
          return { startDate: minDate, endDate: maxDate };
        }
        const proposedStart = new Date(Date.UTC(maxParsed.getUTCFullYear(), maxParsed.getUTCMonth() - (monthCount - 1), 1));
        return clampDateRange(formatDate(proposedStart), maxDate);
      }

      function rangeForYear(year) {
        const typedYear = Number(year);
        if (!Number.isFinite(typedYear)) {
          return { startDate: minDate, endDate: maxDate };
        }
        const startDate = String(typedYear) + "-01-01";
        const endDate = String(typedYear) + "-12-31";
        return clampDateRange(startDate, endDate);
      }

      function setSpecificYearState() {
        specificYearSelect.disabled = windowSelect.value !== "specific_year" || dataYears.length === 0;
      }

      function fillSpecificYearOptions() {
        const previous = Number(specificYearSelect.value);
        specificYearSelect.innerHTML = dataYears
          .map((year) => "<option value=\\"" + String(year) + "\\">" + String(year) + "</option>")
          .join("");
        if (!dataYears.length) {
          specificYearSelect.disabled = true;
          return;
        }
        const selected = dataYears.includes(previous) ? previous : dataYears[dataYears.length - 1];
        specificYearSelect.value = String(selected);
      }

      function applyWindowSelection(windowValue) {
        let range = null;
        if (windowValue === "last_12_months") {
          range = rangeForLastMonths(12);
        } else if (windowValue === "last_3_years") {
          range = rangeForLastMonths(36);
        } else if (windowValue === "last_5_years") {
          range = rangeForLastMonths(60);
        } else if (windowValue === "last_10_years") {
          range = rangeForLastMonths(120);
        } else if (windowValue === "full_history") {
          range = { startDate: minDate, endDate: maxDate };
        } else if (windowValue === "specific_year") {
          range = rangeForYear(specificYearSelect.value);
        }
        setSpecificYearState();
        if (range !== null) {
          startInput.value = range.startDate;
          endInput.value = range.endDate;
        }
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

      function filterByCategoryProject(state) {
        return transactions.filter((tx) => {
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
          if (tx.amountEur === null || !["in", "out"].includes(tx.cashflowType)) {
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
          if (tx.amountEur === null || tx.cashflowType !== "out") {
            continue;
          }
          const existing = totals.get(tx.category) || 0;
          totals.set(tx.category, existing - tx.amountEur);
        }
        const rows = Array.from(totals.entries())
          .map(([category, value]) => ({ category, value }))
          .filter((row) => row.value > 0);
        rows.sort((left, right) => right.value - left.value || left.category.localeCompare(right.category));
        return rows.slice(0, 12);
      }

      function collectYears(filtered) {
        const years = new Set();
        for (const tx of filtered) {
          if (tx.amountEur === null || tx.cashflowType !== "out") {
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
          if (tx.amountEur === null || tx.cashflowType !== "out") {
            continue;
          }
          const year = Number(tx.bookingDate.slice(0, 4));
          const month = Number(tx.bookingDate.slice(5, 7)) - 1;
          if (month < 0 || month > 11) {
            continue;
          }
          const spend = -tx.amountEur;
          if (year === selectedYear) {
            current[month] += spend;
          } else if (year === selectedYear - 1) {
            previous[month] += spend;
          }
        }
        return monthNames
          .map((label, index) => ({
            month: label,
            current: current[index],
            previous: previous[index],
          }))
          .filter((row) => row.current > 0 || row.previous > 0);
      }

      function buildBudgetRows(filtered, state) {
        const categoryActual = new Map();
        const projectActual = new Map();
        for (const tx of filtered) {
          if (tx.amountEur === null || tx.cashflowType !== "out") {
            continue;
          }
          const spend = -tx.amountEur;
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

      function formatPercent(value) {
        if (typeof value !== "number" || !Number.isFinite(value)) {
          return "-";
        }
        return (value * 100).toFixed(1) + "%";
      }

      function renderCashflowYoy() {
        const yearlyRows = Array.isArray(payload.cashflow_yoy && payload.cashflow_yoy.years)
          ? payload.cashflow_yoy.years
          : [];
        if (!yearlyRows.length) {
          cashflowYoyBody.innerHTML =
            "<tr><td colspan=\\"5\\"><span class=\\"empty\\">Not enough completed years to show year-over-year cashflow yet.</span></td></tr>";
        } else {
          cashflowYoyBody.innerHTML = yearlyRows
            .map((row) => {
              const netValue = toNumber(row.net_cashflow) || 0;
              const netClass = netValue > 0 ? "delta-positive" : (netValue < 0 ? "delta-negative" : "delta-neutral");
              return (
                "<tr>" +
                  "<td>" + escapeHtml(String(row.year || "-")) + "</td>" +
                  "<td>" + escapeHtml(money.format(toNumber(row.income) || 0)) + "</td>" +
                  "<td>" + escapeHtml(money.format(toNumber(row.expenses) || 0)) + "</td>" +
                  "<td class=\\"" + netClass + "\\">" +
                    escapeHtml(money.format(netValue)) +
                  "</td>" +
                  "<td>" + escapeHtml(formatPercent(toNumber(row.cashflow_margin))) + "</td>" +
                "</tr>"
              );
            })
            .join("");
        }

        const ytd = payload.cashflow_yoy && typeof payload.cashflow_yoy.current_ytd === "object"
          ? payload.cashflow_yoy.current_ytd
          : null;
        if (!ytd || !ytd.current || !ytd.prior || !ytd.delta) {
          cashflowYtdCard.innerHTML =
            "<h2>Current YTD</h2><p class=\\"empty\\">No current-year YTD comparison is available yet.</p>";
          return;
        }

        const netDelta = toNumber(ytd.delta.net_cashflow);
        const deltaClass = netDelta === null
          ? "delta-neutral"
          : (netDelta > 0 ? "delta-positive" : (netDelta < 0 ? "delta-negative" : "delta-neutral"));
        cashflowYtdCard.innerHTML =
          "<h2>" + escapeHtml(String(ytd.label || "Current YTD")) + "</h2>" +
          "<p class=\\"summary-note\\">" +
            escapeHtml(String(ytd.current_period_start || "")) +
            " to " +
            escapeHtml(String(ytd.current_period_end || "")) +
          "</p>" +
          "<div class=\\"metric-line\\"><span>Income</span><strong>" +
            escapeHtml(money.format(toNumber(ytd.current.income) || 0)) +
            "</strong></div>" +
          "<div class=\\"metric-line\\"><span>Expenses</span><strong>" +
            escapeHtml(money.format(toNumber(ytd.current.expenses) || 0)) +
            "</strong></div>" +
          "<div class=\\"metric-line\\"><span>Net cashflow</span><strong>" +
            escapeHtml(money.format(toNumber(ytd.current.net_cashflow) || 0)) +
            "</strong></div>" +
          "<div class=\\"metric-line\\"><span>Margin</span><strong>" +
            escapeHtml(formatPercent(toNumber(ytd.current.cashflow_margin))) +
            "</strong></div>" +
          "<div class=\\"metric-line\\"><span>vs prior YTD</span><strong class=\\"" + deltaClass + "\\">" +
            escapeHtml(money.format(netDelta || 0)) +
            " / " +
            escapeHtml(formatPercent(toNumber(ytd.delta.cashflow_margin))) +
            "</strong></div>";
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
        const normalizedRange = normalizeCustomFullYearRange(state.startDate, state.endDate);
        state.startDate = normalizedRange.startDate;
        state.endDate = normalizedRange.endDate;
        if (startInput.value !== state.startDate) {
          startInput.value = state.startDate;
        }
        if (endInput.value !== state.endDate) {
          endInput.value = state.endDate;
        }

        const filtered = filterTransactions(state);
        const categoryProjectFiltered = filterByCategoryProject(state);
        let income = 0;
        let expense = 0;
        let transfers = 0;
        let net = 0;
        for (const tx of filtered) {
          if (tx.amountEur === null) {
            continue;
          }
          if (tx.cashflowType === "transfer") {
            transfers += Math.abs(tx.amountEur);
            continue;
          }
          if (tx.cashflowType === "in") {
            income += tx.amountEur;
            net += tx.amountEur;
          } else if (tx.cashflowType === "out") {
            expense -= tx.amountEur;
            net += tx.amountEur;
          }
        }

        setKpi("kpi-income", money.format(income));
        setKpi("kpi-expense", money.format(expense));
        setKpi("kpi-transfers", money.format(transfers));
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

        const years = collectYears(categoryProjectFiltered);
        const selectedYear = syncYearOptions(years);
        renderYoY(aggregateYoY(categoryProjectFiltered, selectedYear), selectedYear);

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
        fillSpecificYearOptions();

        const defaultWindow =
          typeof payload.meta.default_window === "string" && allowedWindows.has(payload.meta.default_window)
            ? payload.meta.default_window
            : "last_12_months";
        windowSelect.value = defaultWindow;
        applyWindowSelection(defaultWindow);

        resetButton.addEventListener("click", function () {
          windowSelect.value = defaultWindow;
          fillSpecificYearOptions();
          applyWindowSelection(defaultWindow);
          for (const option of Array.from(categorySelect.options)) {
            option.selected = false;
          }
          for (const option of Array.from(projectSelect.options)) {
            option.selected = false;
          }
          refreshDashboard();
        });

        windowSelect.addEventListener("change", function () {
          applyWindowSelection(windowSelect.value);
          refreshDashboard();
        });
        specificYearSelect.addEventListener("change", function () {
          if (windowSelect.value === "specific_year") {
            applyWindowSelection("specific_year");
          }
          refreshDashboard();
        });
        startInput.addEventListener("change", function () {
          windowSelect.value = "custom";
          setSpecificYearState();
          refreshDashboard();
        });
        endInput.addEventListener("change", function () {
          windowSelect.value = "custom";
          setSpecificYearState();
          refreshDashboard();
        });
        for (const node of [categorySelect, projectSelect, yoyYearSelect]) {
          node.addEventListener("change", refreshDashboard);
        }
      }

      renderMeta();
      renderWarnings();
      renderCashflowYoy();
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

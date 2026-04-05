"""Self-contained household finance healthcheck dashboard rendering."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.cashflow import build_cashflow_rows_frame
from finance_tooling.classify import normalize_description

_ESSENTIAL_CATEGORIES = frozenset(
    {
        "Housing",
        "Utilities",
        "Groceries",
        "Transport",
        "Healthcare",
        "Insurance",
        "Taxes",
        "Family",
        "Fees",
        "Memberships",
    }
)


def _serialize_payload(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return serialized.replace("</", "<\\/")


def _build_rows_frame(dataframe: pd.DataFrame) -> pd.DataFrame:
    working = build_cashflow_rows_frame(dataframe)
    if working.empty:
        return pd.DataFrame(
            columns=[
                "booking_date",
                "month",
                "amount_eur",
                "category",
                "description",
                "project",
                "subcategory",
                "tracked_savings",
                "neutral_transfer",
                "essential",
                "uncategorized",
                "housing",
            ]
        )

    category_casefold = working["category"].str.casefold()
    amount_is_outflow = working["amount_eur"] < 0
    working["essential"] = amount_is_outflow & working["category"].isin(_ESSENTIAL_CATEGORIES)
    working["uncategorized"] = category_casefold.eq("uncategorized")
    working["housing"] = amount_is_outflow & category_casefold.eq("housing")

    return working[
        [
            "booking_date",
            "month",
            "amount_eur",
            "category",
            "description",
            "project",
            "subcategory",
            "tracked_savings",
            "neutral_transfer",
            "essential",
            "uncategorized",
            "housing",
        ]
    ].sort_values("booking_date", kind="stable", ignore_index=True)


def _month_start(value: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(year=value.year, month=value.month, day=1)


def _month_count(start: pd.Timestamp, end: pd.Timestamp) -> int:
    return ((end.year - start.year) * 12) + (end.month - start.month) + 1


def _window_ranges(rows: pd.DataFrame) -> list[tuple[str, str, pd.Timestamp, pd.Timestamp]]:
    if rows.empty:
        today = _month_start(pd.Timestamp(datetime.now(UTC).date()))
        return [
            ("last_12_months", "Trailing 12 Months", today, today),
            ("last_6_months", "Trailing 6 Months", today, today),
            ("last_3_months", "Trailing 3 Months", today, today),
            ("year_to_date", "Year to Date", today, today),
        ]

    last_date = pd.to_datetime(rows["booking_date"], errors="coerce").dropna().max()
    assert last_date is not pd.NaT
    end = _month_start(last_date)
    return [
        ("last_12_months", "Trailing 12 Months", end - pd.DateOffset(months=11), end),
        ("last_6_months", "Trailing 6 Months", end - pd.DateOffset(months=5), end),
        ("last_3_months", "Trailing 3 Months", end - pd.DateOffset(months=2), end),
        ("year_to_date", "Year to Date", pd.Timestamp(year=end.year, month=1, day=1), end),
    ]


def _status_for_ratio(value: float, *, green_max: float, amber_max: float) -> str:
    if value < green_max:
        return "green"
    if value <= amber_max:
        return "amber"
    return "red"


def _status_for_positive_ratio(value: float, *, green_min: float, amber_min: float) -> str:
    if value > green_min:
        return "green"
    if value >= amber_min:
        return "amber"
    return "red"


def _build_window_payload(
    rows: pd.DataFrame,
    *,
    label: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, object]:
    window_start = start.strftime("%Y-%m")
    window_end = end.strftime("%Y-%m")
    mask = rows["month"].ge(window_start) & rows["month"].le(window_end)
    window_rows = rows.loc[mask].copy()
    month_count = _month_count(start, end)

    if window_rows.empty:
        monthly_rows = [
            {
                "month": (start + pd.DateOffset(months=offset)).strftime("%Y-%m"),
                "inflow": 0.0,
                "consumption_spend": 0.0,
                "tracked_savings": 0.0,
                "net_residual": 0.0,
            }
            for offset in range(month_count)
        ]
        metrics = {
            "avg_monthly_inflow": 0.0,
            "avg_monthly_consumption_spend": 0.0,
            "avg_monthly_tracked_savings": 0.0,
            "avg_monthly_net_residual": 0.0,
            "tracked_savings_rate": 0.0,
            "essential_spending_ratio": 0.0,
            "housing_cost_ratio": 0.0,
            "uncategorized_amount_ratio": 0.0,
            "uncategorized_count_ratio": 0.0,
        }
        status = {
            "overall": "amber",
            "net_residual": "amber",
            "tracked_savings_rate": "red",
            "essential_spending_ratio": "green",
            "housing_cost_ratio": "green",
            "uncategorized_amount_ratio": "green",
        }
        return {
            "label": label,
            "start_month": window_start,
            "end_month": window_end,
            "months": month_count,
            "metrics": metrics,
            "status": status,
            "monthly": monthly_rows,
            "category_breakdown": [],
            "top_uncategorized": [],
            "interpretation": [
                "No transactions landed in this window after exclusions.",
                (
                    "The dashboard is ready, but this time range has no usable "
                    "household cash-flow data."
                ),
            ],
        }

    outflows = window_rows["amount_eur"] < 0
    neutral_transfer_mask = window_rows["neutral_transfer"]
    inflows = (window_rows["amount_eur"] > 0) & ~neutral_transfer_mask
    tracked_savings_mask = window_rows["tracked_savings"]
    consumption_mask = outflows & ~tracked_savings_mask & ~neutral_transfer_mask
    essential_mask = window_rows["essential"] & ~tracked_savings_mask
    housing_mask = window_rows["housing"] & ~tracked_savings_mask
    uncategorized_mask = window_rows["uncategorized"] & ~neutral_transfer_mask

    inflow_total = float(window_rows.loc[inflows, "amount_eur"].sum())
    consumption_total = float((-window_rows.loc[consumption_mask, "amount_eur"]).sum())
    tracked_savings_total = float((-window_rows.loc[tracked_savings_mask, "amount_eur"]).sum())
    essential_total = float((-window_rows.loc[essential_mask, "amount_eur"]).sum())
    housing_total = float((-window_rows.loc[housing_mask, "amount_eur"]).sum())
    net_residual_total = inflow_total - consumption_total - tracked_savings_total

    absolute_amounts = window_rows.loc[~neutral_transfer_mask, "amount_eur"].abs()
    uncategorized_amount_total = float(absolute_amounts.loc[uncategorized_mask].sum())
    total_absolute_amount = float(absolute_amounts.sum())
    uncategorized_count = int(uncategorized_mask.sum())
    total_count = int((~neutral_transfer_mask).sum())

    metrics = {
        "avg_monthly_inflow": round(inflow_total / month_count, 2),
        "avg_monthly_consumption_spend": round(consumption_total / month_count, 2),
        "avg_monthly_tracked_savings": round(tracked_savings_total / month_count, 2),
        "avg_monthly_net_residual": round(net_residual_total / month_count, 2),
        "tracked_savings_rate": (
            round(tracked_savings_total / inflow_total, 4) if inflow_total else 0.0
        ),
        "essential_spending_ratio": (
            round(essential_total / consumption_total, 4) if consumption_total else 0.0
        ),
        "housing_cost_ratio": round(housing_total / inflow_total, 4) if inflow_total else 0.0,
        "uncategorized_amount_ratio": (
            round(uncategorized_amount_total / total_absolute_amount, 4)
            if total_absolute_amount
            else 0.0
        ),
        "uncategorized_count_ratio": (
            round(uncategorized_count / total_count, 4) if total_count else 0.0
        ),
    }

    status = {
        "net_residual": _status_for_positive_ratio(
            metrics["avg_monthly_net_residual"] / metrics["avg_monthly_inflow"]
            if metrics["avg_monthly_inflow"]
            else 0.0,
            green_min=0.10,
            amber_min=0.0,
        ),
        "tracked_savings_rate": _status_for_positive_ratio(
            metrics["tracked_savings_rate"],
            green_min=0.15,
            amber_min=0.05,
        ),
        "essential_spending_ratio": _status_for_ratio(
            metrics["essential_spending_ratio"],
            green_max=0.60,
            amber_max=0.75,
        ),
        "housing_cost_ratio": _status_for_ratio(
            metrics["housing_cost_ratio"],
            green_max=0.30,
            amber_max=0.40,
        ),
        "uncategorized_amount_ratio": _status_for_ratio(
            metrics["uncategorized_amount_ratio"],
            green_max=0.05,
            amber_max=0.12,
        ),
    }
    if "red" in status.values():
        overall = "red"
    elif "amber" in status.values():
        overall = "amber"
    else:
        overall = "green"
    status["overall"] = overall

    monthly = (
        window_rows.assign(
            inflow=window_rows["amount_eur"].where(inflows, 0.0),
            consumption_spend=(-window_rows["amount_eur"]).where(consumption_mask, 0.0),
            tracked_savings_amount=(-window_rows["amount_eur"]).where(tracked_savings_mask, 0.0),
        )
        .groupby("month", sort=True)
        .agg(
            inflow=("inflow", "sum"),
            consumption_spend=("consumption_spend", "sum"),
            tracked_savings=("tracked_savings_amount", "sum"),
        )
        .reset_index()
    )
    monthly["net_residual"] = (
        monthly["inflow"] - monthly["consumption_spend"] - monthly["tracked_savings"]
    )
    monthly_rows = [
        {
            "month": str(row["month"]),
            "inflow": round(float(row["inflow"]), 2),
            "consumption_spend": round(float(row["consumption_spend"]), 2),
            "tracked_savings": round(float(row["tracked_savings"]), 2),
            "net_residual": round(float(row["net_residual"]), 2),
        }
        for _, row in monthly.iterrows()
    ]

    category_breakdown_series = (
        (-window_rows.loc[consumption_mask].groupby("category")["amount_eur"].sum())
        .sort_values(ascending=False)
        .head(12)
    )
    category_breakdown = [
        {"category": str(category), "amount_eur": round(float(amount), 2)}
        for category, amount in category_breakdown_series.items()
    ]

    uncategorized_descriptions = (
        window_rows.loc[uncategorized_mask]
        .assign(
            normalized_description=lambda frame: frame["description"].map(
                lambda value: normalize_description(str(value)) or "unknown"
            ),
            absolute_amount=lambda frame: frame["amount_eur"].abs(),
        )
        .groupby("normalized_description", sort=True)
        .agg(count=("normalized_description", "size"), amount_eur=("absolute_amount", "sum"))
        .sort_values(["amount_eur", "count"], ascending=[False, False])
        .head(10)
    )
    top_uncategorized = [
        {
            "description": str(description),
            "count": int(row["count"]),
            "amount_eur": round(float(row["amount_eur"]), 2),
        }
        for description, row in uncategorized_descriptions.iterrows()
    ]

    interpretation: list[str] = []
    if metrics["avg_monthly_net_residual"] < 0:
        interpretation.append(
            "The household is spending more than it brings in over this window."
        )
    elif metrics["avg_monthly_net_residual"] <= metrics["avg_monthly_inflow"] * 0.10:
        interpretation.append(
            "The household remains cash-flow positive, but the monthly buffer is thin."
        )
    else:
        interpretation.append(
            "The household keeps a meaningful positive monthly buffer in this window."
        )

    if metrics["tracked_savings_rate"] < 0.05:
        interpretation.append(
            "Tracked savings and investing contributions are low relative to inflow."
        )
    elif metrics["tracked_savings_rate"] <= 0.15:
        interpretation.append(
            "Tracked savings is present, but still modest compared with income."
        )
    else:
        interpretation.append("Tracked savings and investing contributions are strong.")

    if metrics["uncategorized_amount_ratio"] > 0.12:
        interpretation.append("Too much money is still uncategorized for a crisp healthcheck.")
    elif metrics["uncategorized_amount_ratio"] > 0.05:
        interpretation.append(
            "Some spending still needs categorization cleanup, but the amount view is usable."
        )
    else:
        interpretation.append(
            "Categorization quality is good enough for a reliable amount-level overview."
        )

    return {
        "label": label,
        "start_month": window_start,
        "end_month": window_end,
        "months": month_count,
        "metrics": metrics,
        "status": status,
        "monthly": monthly_rows,
        "category_breakdown": category_breakdown,
        "top_uncategorized": top_uncategorized,
        "interpretation": interpretation,
    }


def _build_payload(dataframe: pd.DataFrame, *, base_currency: str) -> dict[str, object]:
    rows = _build_rows_frame(dataframe)
    windows = {}
    for key, label, start, end in _window_ranges(rows):
        windows[key] = _build_window_payload(rows, label=label, start=start, end=end)

    return {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "title": "Household Finance Healthcheck",
            "base_currency": base_currency,
            "default_window": "last_12_months",
            "treat_cash_as_expense": True,
        },
        "windows": windows,
    }


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Household Finance Healthcheck</title>
  <style>
    :root {
      --bg: #f4f1ea;
      --panel: rgba(255, 251, 244, 0.95);
      --text: #1e1a16;
      --muted: #6f655d;
      --line: #d8cdc0;
      --green: #2d6a4f;
      --amber: #b7791f;
      --red: #b33a3a;
      --ink-soft: #efe5d8;
      --shadow: 0 18px 40px rgba(41, 30, 21, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(45, 106, 79, 0.10), transparent 28%),
        radial-gradient(circle at bottom right, rgba(183, 121, 31, 0.10), transparent 24%),
        linear-gradient(180deg, #f7f3ec, var(--bg));
      color: var(--text);
      min-height: 100vh;
    }
    .shell {
      max-width: 1320px;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      gap: 18px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 20px;
    }
    .hero {
      display: grid;
      gap: 10px;
    }
    h1, h2 {
      margin: 0;
      font-family: "IBM Plex Serif", Georgia, serif;
      letter-spacing: -0.02em;
    }
    p { margin: 0; color: var(--muted); }
    .status-banner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-radius: 14px;
      color: #fff;
      font-weight: 700;
    }
    .status-green { background: linear-gradient(135deg, #2d6a4f, #3f8a66); }
    .status-amber { background: linear-gradient(135deg, #a86b1a, #d08c28); }
    .status-red { background: linear-gradient(135deg, #9f3131, #cc4b4b); }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
    }
    select {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    .kpis {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }
    .kpi {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: rgba(255,255,255,0.72);
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
      font-size: 24px;
      font-weight: 700;
    }
    .metric-status {
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.9fr);
      gap: 18px;
    }
    .chart-wrap {
      display: grid;
      gap: 10px;
      position: relative;
    }
    svg {
      width: 100%;
      height: 320px;
      border-radius: 14px;
      background: rgba(255,255,255,0.78);
      border: 1px solid var(--line);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      color: var(--muted);
      font-size: 13px;
    }
    .legend span::before {
      content: "";
      display: inline-block;
      width: 11px;
      height: 11px;
      border-radius: 999px;
      margin-right: 8px;
      vertical-align: middle;
    }
    .legend .inflow::before { background: #2d6a4f; }
    .legend .consumption::before { background: #b33a3a; }
    .legend .savings::before { background: #1f4a7b; }
    .legend .net::before { background: #6b4e9b; }
    .chart-tooltip {
      position: absolute;
      min-width: 220px;
      max-width: 280px;
      pointer-events: none;
      opacity: 0;
      transform: translate(-50%, calc(-100% - 14px));
      padding: 12px 14px;
      border-radius: 12px;
      background: rgba(30, 26, 22, 0.94);
      color: #fffaf3;
      box-shadow: 0 16px 28px rgba(30, 26, 22, 0.22);
      transition: opacity 120ms ease;
      z-index: 2;
    }
    .chart-tooltip.visible {
      opacity: 1;
    }
    .chart-tooltip .month {
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 8px;
      color: #f7dfb6;
    }
    .chart-tooltip .row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      margin-top: 4px;
    }
    .chart-tooltip .label {
      color: #d9cab6;
    }
    .chart-tooltip .value {
      font-variant-numeric: tabular-nums;
      text-align: right;
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
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
    td.amount { text-align: right; font-variant-numeric: tabular-nums; }
    .notes {
      display: grid;
      gap: 8px;
      padding-left: 18px;
      color: var(--muted);
    }
    @media (max-width: 980px) {
      .layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="card hero">
      <h1>Household Finance Healthcheck</h1>
      <p>
        Cash-flow-first household overview built from the canonical processed transaction
        dataset. Cash withdrawals stay in the spending view; only Transfers and
        Non Personal Transactions are excluded.
      </p>
      <div class="toolbar">
        <label for="window-select">Window</label>
        <select id="window-select"></select>
        <span id="window-range"></span>
      </div>
      <div id="status-banner" class="status-banner status-amber"></div>
    </section>

    <section class="kpis" id="kpis"></section>

    <section class="layout">
      <div class="card chart-wrap">
        <h2>Monthly Trend</h2>
      <div class="legend">
        <span class="inflow">Inflow</span>
        <span class="consumption">Consumption Spend</span>
        <span class="savings">Tracked Savings</span>
        <span class="net">Net Residual</span>
      </div>
      <svg id="trend-chart" viewBox="0 0 900 320" preserveAspectRatio="none"></svg>
      <div id="chart-tooltip" class="chart-tooltip"></div>
    </div>

      <aside class="card">
        <h2>Interpretation</h2>
        <ul id="interpretation-list" class="notes"></ul>
      </aside>
    </section>

    <section class="layout">
      <section class="card">
        <h2>Consumption Breakdown</h2>
        <table>
          <thead>
            <tr><th>Category</th><th class="amount">Amount</th></tr>
          </thead>
          <tbody id="category-breakdown-body"></tbody>
        </table>
      </section>

      <section class="card">
        <h2>Top Uncategorized</h2>
        <table>
          <thead>
            <tr><th>Description</th><th class="amount">Amount</th><th class="amount">Count</th></tr>
          </thead>
          <tbody id="uncategorized-body"></tbody>
        </table>
      </section>
    </section>
  </div>

  <script id="household-healthcheck-data" type="application/json">__PAYLOAD_JSON__</script>
  <script>
    (function () {
      "use strict";

      function parsePayload() {
        const node = document.getElementById("household-healthcheck-data");
        if (!node) {
          return { meta: {}, windows: {} };
        }
        try {
          return JSON.parse(node.textContent || "{}");
        } catch (error) {
          console.error("Failed to parse healthcheck payload", error);
          return { meta: {}, windows: {} };
        }
      }

      function formatCurrency(value, currency) {
        return new Intl.NumberFormat("en-GB", {
          style: "currency",
          currency: currency || "EUR",
          maximumFractionDigits: 0
        }).format(value || 0);
      }

      function formatCompactCurrency(value, currency) {
        return new Intl.NumberFormat("en-GB", {
          style: "currency",
          currency: currency || "EUR",
          notation: "compact",
          maximumFractionDigits: 1
        }).format(value || 0);
      }

      function formatPct(value) {
        return ((value || 0) * 100).toFixed(1) + "%";
      }

      function statusLabel(status) {
        if (status === "green") return "Healthy";
        if (status === "red") return "Needs Attention";
        return "Watch";
      }

      function statusClass(status) {
        if (status === "green") return "status-green";
        if (status === "red") return "status-red";
        return "status-amber";
      }

      function metricTone(status) {
        if (status === "green") return "color: var(--green)";
        if (status === "red") return "color: var(--red)";
        return "color: var(--amber)";
      }

      const payload = parsePayload();
      const meta = payload.meta || {};
      const windows = payload.windows || {};
      const select = document.getElementById("window-select");
      const kpis = document.getElementById("kpis");
      const rangeNode = document.getElementById("window-range");
      const statusBanner = document.getElementById("status-banner");
      const interpretationList = document.getElementById("interpretation-list");
      const categoryBody = document.getElementById("category-breakdown-body");
      const uncategorizedBody = document.getElementById("uncategorized-body");
      const chart = document.getElementById("trend-chart");
      const chartTooltip = document.getElementById("chart-tooltip");
      const defaultWindow = meta.default_window || "last_12_months";

      function linePath(points, xScale, yScale, left, height) {
        return points.map(function (point, index) {
          const x = left + (xScale * index);
          const y = height - (point * yScale);
          return (index === 0 ? "M" : "L") + x.toFixed(2) + " " + y.toFixed(2);
        }).join(" ");
      }

      function renderChart(rows) {
        chart.innerHTML = "";
        chart.onmousemove = null;
        chart.onmouseleave = null;
        if (chartTooltip) {
          chartTooltip.classList.remove("visible");
        }
        if (!Array.isArray(rows) || rows.length === 0) {
          return;
        }
        const width = 900;
        const height = 320;
        const left = 52;
        const right = 20;
        const top = 20;
        const bottom = 40;
        const innerWidth = width - left - right;
        const innerHeight = height - top - bottom;
        const allValues = [];
        rows.forEach(function (row) {
          allValues.push(
            row.inflow || 0,
            row.consumption_spend || 0,
            row.tracked_savings || 0,
            row.net_residual || 0
          );
        });
        const maxValue = Math.max.apply(null, allValues.concat([0]));
        const minValue = Math.min.apply(null, allValues.concat([0]));
        const tickCount = 5;
        const positiveStep =
          maxValue > 0 ? Math.ceil(maxValue / tickCount / 100) * 100 : 100;
        const negativeStep =
          minValue < 0 ? Math.ceil(Math.abs(minValue) / tickCount / 100) * 100 : 100;
        const roundedMaxValue = maxValue > 0 ? positiveStep * tickCount : 0;
        const roundedMinValue = minValue < 0 ? -(negativeStep * tickCount) : 0;
        const xScale = rows.length > 1 ? innerWidth / (rows.length - 1) : innerWidth;
        const valueRange = roundedMaxValue - roundedMinValue || 1;
        const yScale = innerHeight / valueRange;

        function chartY(value) {
          return top + ((roundedMaxValue - value) * yScale);
        }

        const frame = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        frame.setAttribute("x", String(left));
        frame.setAttribute("y", String(top));
        frame.setAttribute("width", String(innerWidth));
        frame.setAttribute("height", String(innerHeight));
        frame.setAttribute("fill", "transparent");
        frame.setAttribute("stroke", "#d8cdc0");
        chart.appendChild(frame);

        for (let tick = 0; tick <= tickCount; tick += 1) {
          const tickValue = roundedMinValue + ((valueRange / tickCount) * tick);
          const y = chartY(tickValue);

          const grid = document.createElementNS("http://www.w3.org/2000/svg", "line");
          grid.setAttribute("x1", String(left));
          grid.setAttribute("x2", String(left + innerWidth));
          grid.setAttribute("y1", String(y));
          grid.setAttribute("y2", String(y));
          const isZeroLine = Math.abs(tickValue) < 1e-9;
          grid.setAttribute("stroke", isZeroLine ? "#b8aa98" : "#e5dbcf");
          grid.setAttribute("stroke-width", isZeroLine ? "1.5" : "1");
          grid.setAttribute("stroke-dasharray", isZeroLine ? "0" : "4 4");
          chart.appendChild(grid);

          const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
          label.setAttribute("x", String(left - 10));
          label.setAttribute("y", String(y + 4));
          label.setAttribute("text-anchor", "end");
          label.setAttribute("font-size", "12");
          label.setAttribute("fill", "#6f655d");
          label.textContent = formatCompactCurrency(tickValue, meta.base_currency || "EUR");
          chart.appendChild(label);
        }

        const series = [
          { key: "inflow", color: "#2d6a4f" },
          { key: "consumption_spend", color: "#b33a3a" },
          { key: "tracked_savings", color: "#1f4a7b" },
          { key: "net_residual", color: "#6b4e9b", absolute: true }
        ];

        series.forEach(function (item) {
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          const values = rows.map(function (row) {
            return row[item.key] || 0;
          });
          path.setAttribute(
            "d",
            values.map(function (point, index) {
              const x = left + (xScale * index);
              const y = chartY(point);
              return (index === 0 ? "M" : "L") + x.toFixed(2) + " " + y.toFixed(2);
            }).join(" ")
          );
          path.setAttribute("fill", "none");
          path.setAttribute("stroke", item.color);
          path.setAttribute("stroke-width", "3");
          chart.appendChild(path);
        });

        rows.forEach(function (row, index) {
          const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
          const x = left + (xScale * index);
          label.setAttribute("x", String(x));
          label.setAttribute("y", String(height - 12));
          label.setAttribute(
            "text-anchor",
            index === 0 ? "start" : index === rows.length - 1 ? "end" : "middle"
          );
          label.setAttribute("font-size", "12");
          label.setAttribute("fill", "#6f655d");
          label.textContent = row.month;
          chart.appendChild(label);
        });

        chart.onmousemove = function (event) {
          if (!chartTooltip) {
            return;
          }
          const bounds = chart.getBoundingClientRect();
          const plotLeftPx = (left / width) * bounds.width;
          const plotRightPx = (right / width) * bounds.width;
          const plotWidthPx = bounds.width - plotLeftPx - plotRightPx;
          const relativeX = event.clientX - bounds.left;
          const clampedX = Math.max(
            plotLeftPx,
            Math.min(bounds.width - plotRightPx, relativeX)
          );
          const ratio = plotWidthPx <= 0 ? 0 : (clampedX - plotLeftPx) / plotWidthPx;
          const index = rows.length === 1
            ? 0
            : Math.max(0, Math.min(rows.length - 1, Math.round(ratio * (rows.length - 1))));
          const month = rows[index];
          chartTooltip.innerHTML =
            '<div class="month">' +
            month.month +
            '</div>' +
            '<div class="row"><span class="label">Inflow</span><span class="value">' +
            formatCurrency(month.inflow, meta.base_currency || "EUR") +
            '</span></div>' +
            '<div class="row"><span class="label">Consumption</span><span class="value">' +
            formatCurrency(month.consumption_spend, meta.base_currency || "EUR") +
            '</span></div>' +
            '<div class="row"><span class="label">Tracked Savings</span><span class="value">' +
            formatCurrency(month.tracked_savings, meta.base_currency || "EUR") +
            '</span></div>' +
            '<div class="row"><span class="label">Net Residual</span><span class="value">' +
            formatCurrency(month.net_residual, meta.base_currency || "EUR") +
            "</span></div>";
          chartTooltip.style.left = relativeX + "px";
          chartTooltip.style.top = (event.clientY - bounds.top) + "px";
          chartTooltip.classList.add("visible");
        };

        chart.onmouseleave = function () {
          if (chartTooltip) {
            chartTooltip.classList.remove("visible");
          }
        };
      }

      function renderWindow(key) {
        const windowData = windows[key] || {};
        const metrics = windowData.metrics || {};
        const status = windowData.status || {};
        const currency = meta.base_currency || "EUR";
        rangeNode.textContent =
          (windowData.start_month || "") + " to " + (windowData.end_month || "");
        statusBanner.className = "status-banner " + statusClass(status.overall);
        statusBanner.textContent = statusLabel(status.overall) + " - " + (windowData.label || "");

        const cards = [
          [
            "Avg Monthly Inflow",
            formatCurrency(metrics.avg_monthly_inflow, currency),
            status.net_residual
          ],
          [
            "Consumption Spend",
            formatCurrency(metrics.avg_monthly_consumption_spend, currency),
            status.essential_spending_ratio
          ],
          [
            "Tracked Savings",
            formatCurrency(metrics.avg_monthly_tracked_savings, currency),
            status.tracked_savings_rate
          ],
          [
            "Net Residual",
            formatCurrency(metrics.avg_monthly_net_residual, currency),
            status.net_residual
          ],
          ["Savings Rate", formatPct(metrics.tracked_savings_rate), status.tracked_savings_rate],
          [
            "Essential Ratio",
            formatPct(metrics.essential_spending_ratio),
            status.essential_spending_ratio
          ],
          ["Housing Ratio", formatPct(metrics.housing_cost_ratio), status.housing_cost_ratio],
          [
            "Uncategorized Amount",
            formatPct(metrics.uncategorized_amount_ratio),
            status.uncategorized_amount_ratio
          ],
          [
            "Uncategorized Count",
            formatPct(metrics.uncategorized_count_ratio),
            status.uncategorized_amount_ratio
          ]
        ];
        kpis.innerHTML = cards.map(function (card) {
          return (
            '<div class="kpi"><div class="label">' +
            card[0] +
            '</div><div class="value">' +
            card[1] +
            '</div><div class="metric-status" style="' +
            metricTone(card[2]) +
            '">' +
            statusLabel(card[2]) +
            "</div></div>"
          );
        }).join("");

        interpretationList.innerHTML = (windowData.interpretation || []).map(function (item) {
          return "<li>" + item + "</li>";
        }).join("");

        categoryBody.innerHTML = (windowData.category_breakdown || []).map(function (item) {
          return (
            "<tr><td>" +
            item.category +
            '</td><td class=\\"amount\\">' +
            formatCurrency(item.amount_eur, currency) +
            "</td></tr>"
          );
        }).join("");

        uncategorizedBody.innerHTML = (windowData.top_uncategorized || []).map(function (item) {
          return (
            "<tr><td>" +
            item.description +
            '</td><td class=\\"amount\\">' +
            formatCurrency(item.amount_eur, currency) +
            '</td><td class=\\"amount\\">' +
            item.count +
            "</td></tr>"
          );
        }).join("");

        renderChart(windowData.monthly || []);
      }

      Object.keys(windows).forEach(function (key) {
        const option = document.createElement("option");
        option.value = key;
        option.textContent = (windows[key] || {}).label || key;
        if (key === defaultWindow) {
          option.selected = true;
        }
        select.appendChild(option);
      });

      select.addEventListener("change", function () {
        renderWindow(select.value);
      });

      renderWindow(defaultWindow);
    })();
  </script>
</body>
</html>
"""


def render_household_healthcheck_html(
    dataframe: pd.DataFrame,
    destination: Path,
    *,
    base_currency: str,
) -> Path:
    """Render a self-contained household healthcheck HTML dashboard."""
    payload = _build_payload(dataframe, base_currency=base_currency)
    html = _HTML_TEMPLATE.replace("__PAYLOAD_JSON__", _serialize_payload(payload))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination

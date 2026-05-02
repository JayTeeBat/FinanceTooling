# ruff: noqa: E501
"""Planning stage orchestration from canonical transactions to decision artifacts."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pandas as pd
from tqdm import tqdm

from finance_tooling.categorization.classify import load_classification_rules
from finance_tooling.core.config import (
    PLANNING_BUDGET_STATUS_FILENAME,
    PLANNING_DASHBOARD_FILENAME,
    PLANNING_KPI_SUMMARY_FILENAME,
    PLANNING_LEDGER_CSV_FILENAME,
    PLANNING_LEDGER_FILENAME,
    Settings,
    planning_root_path,
    resolve_transform_artifact_path,
)
from finance_tooling.planning.budgeting import (
    BudgetConfig,
    build_budget_status,
    build_monthly_planning_ledger,
    load_budget_config,
)
from finance_tooling.workflow.reporting import write_json


@dataclass(frozen=True)
class PlanningExecutionResult:
    """Outputs of planning stage execution."""

    ledger_path: Path
    ledger_csv_path: Path
    kpi_summary_path: Path
    budget_status_path: Path
    dashboard_path: Path
    input_transactions_path: Path
    ledger_rows: int
    budget_status_rows: int
    warnings: tuple[str, ...] = ()


def _load_transactions(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Planning input transactions file not found: {path}")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


def _bucket_totals(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {}
    totals = frame.groupby("planning_bucket", dropna=False)["planning_amount_eur"].sum()
    return {str(bucket): round(float(amount), 2) for bucket, amount in totals.items()}


def _surface_totals(frame: pd.DataFrame, column: str) -> dict[str, float]:
    if frame.empty or column not in frame.columns:
        return {}
    working = frame.copy()
    working[column] = working[column].map(_normalize_surface_bucket_label)
    totals = working.groupby(column, dropna=False)["planning_amount_eur"].sum()
    return {
        _normalize_surface_bucket_label(bucket): round(float(amount), 2)
        for bucket, amount in totals.items()
    }


def _monthly_surface_breakdown(frame: pd.DataFrame, column: str) -> list[dict[str, object]]:
    if frame.empty or column not in frame.columns:
        return []
    working = frame.copy()
    working[column] = working[column].map(_normalize_surface_bucket_label)
    grouped = working.groupby(["month", column], dropna=False)["planning_amount_eur"].sum()
    rows: list[dict[str, object]] = []
    for (month, bucket), amount in grouped.items():
        rows.append(
            {
                "month": str(month),
                "bucket": _normalize_surface_bucket_label(bucket),
                "amount_eur": round(float(amount), 2),
            }
        )
    rows.sort(key=lambda row: (str(row["month"]), str(row["bucket"])))
    return rows


def _surface_monthly_breakdown_by_month(
    frame: pd.DataFrame,
    column: str,
) -> dict[str, dict[str, float]]:
    if frame.empty or column not in frame.columns:
        return {}
    working = frame.copy()
    working[column] = working[column].map(_normalize_surface_bucket_label)
    grouped = working.groupby(["month", column], dropna=False)["planning_amount_eur"].sum()
    monthly: dict[str, dict[str, float]] = {}
    for (month, bucket), amount in grouped.items():
        month_key = str(month)
        bucket_key = _normalize_surface_bucket_label(bucket)
        month_totals = monthly.setdefault(month_key, {})
        month_totals[bucket_key] = round(float(amount), 2)
    return {
        month: dict(sorted(bucket_totals.items(), key=lambda item: item[0]))
        for month, bucket_totals in sorted(monthly.items(), key=lambda item: item[0])
    }


def _available_months(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "month" not in frame.columns:
        return []
    month_values = frame["month"].dropna().astype("string")
    return [str(month) for month in dict.fromkeys(month_values.tolist())]


def _available_years(months: list[str]) -> list[str]:
    return list(dict.fromkeys(month[:4] for month in months if len(month) >= 4))


def _normalize_surface_bucket_label(bucket: object) -> str:
    if bucket is None or pd.isna(bucket):
        return "unknown"
    label = str(bucket).strip()
    return label if label else "unknown"


def _normalize_surface_breakdowns(
    surface_breakdowns: dict[str, object],
) -> dict[str, dict[str, object]]:
    normalized: dict[str, dict[str, object]] = {}
    for surface_key, surface_payload in surface_breakdowns.items():
        if not isinstance(surface_payload, dict):
            continue
        surface_mapping = cast(dict[str, object], surface_payload)
        monthly_totals = surface_mapping.get("monthly_totals", [])
        monthly_totals_by_month = surface_mapping.get("monthly_totals_by_month", {})
        bucket_totals = surface_mapping.get("bucket_totals", {})

        normalized_monthly_totals: list[dict[str, object]] = []
        if isinstance(monthly_totals, list):
            for row in monthly_totals:
                if not isinstance(row, dict):
                    continue
                row_mapping = cast(dict[str, object], row)
                normalized_monthly_totals.append(
                    {
                        "month": row_mapping.get("month"),
                        "bucket": _normalize_surface_bucket_label(row_mapping.get("bucket")),
                        "amount_eur": row_mapping.get("amount_eur"),
                    }
                )

        normalized_monthly_totals_by_month: dict[str, dict[str, object]] = {}
        if isinstance(monthly_totals_by_month, dict):
            for month, month_buckets in monthly_totals_by_month.items():
                if not isinstance(month_buckets, dict):
                    continue
                normalized_monthly_totals_by_month[str(month)] = {
                    _normalize_surface_bucket_label(bucket): value
                    for bucket, value in month_buckets.items()
                }

        normalized_bucket_totals = (
            {
                _normalize_surface_bucket_label(bucket): value
                for bucket, value in bucket_totals.items()
            }
            if isinstance(bucket_totals, dict)
            else {}
        )

        normalized[surface_key] = cast(
            dict[str, object],
            {
                **surface_mapping,
                "monthly_totals": normalized_monthly_totals,
                "monthly_totals_by_month": normalized_monthly_totals_by_month,
                "bucket_totals": normalized_bucket_totals,
            },
        )
    return normalized


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {
        str(index): int(value)
        for index, value in frame[column].fillna("unknown").astype("string").value_counts().items()
    }


def _summary_card(label: str, value: object, *, detail: str | None = None) -> str:
    detail_html = f'<div class="detail">{detail}</div>' if detail else ""
    return f"""
      <div class="card">
        <div class="label">{label}</div>
        <div class="value">{value}</div>
        {detail_html}
      </div>
    """


def _option_html(value: str, label: str, *, selected: bool) -> str:
    selected_attr = " selected" if selected else ""
    return f'<option value="{value}"{selected_attr}>{label}</option>'


def _month_option_html(month: str, *, selected: bool) -> str:
    return _option_html(month, month, selected=selected)


def _payload_mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _payload_float(payload: dict[str, object], key: str) -> float:
    value = payload.get(key, 0.0)
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _serialize_payload(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return serialized.replace("</", "<\\/")


def _row_text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _row_float(row: dict[str, object], key: str) -> float:
    value = row.get(key, 0.0)
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def build_planning_kpi_summary(
    ledger: pd.DataFrame,
    budget_status: pd.DataFrame,
    *,
    budget_config: BudgetConfig,
    warnings: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build planning KPIs from the planning ledger only."""
    generated_at = datetime.now(UTC).isoformat()
    if ledger.empty:
        month_min = None
        month_max = None
        ytd_year = None
        available_months: list[str] = []
        available_years: list[str] = []
        ytd_totals: dict[str, float] = {}
        monthly_totals: list[dict[str, object]] = []
        surface_breakdowns: dict[str, dict[str, object]] = {}
    else:
        available_months = _available_months(ledger)
        available_years = _available_years(available_months)
        month_values = pd.Series(available_months, dtype="string")
        month_min = str(month_values.min()) if not month_values.empty else None
        month_max = str(month_values.max()) if not month_values.empty else None
        ytd_year = month_max[:4] if month_max else None
        ytd_frame = ledger[ledger["month"].astype("string").str.startswith(f"{ytd_year}-")]
        ytd_totals = _bucket_totals(ytd_frame)
        monthly_totals = []
        grouped = ledger.groupby(["month", "planning_bucket"], dropna=False)[
            "planning_amount_eur"
        ].sum()
        for (month, bucket), amount in grouped.items():
            monthly_totals.append(
                {
                    "month": str(month),
                    "planning_bucket": str(bucket),
                    "amount_eur": round(float(amount), 2),
                }
            )
        monthly_totals.sort(
            key=lambda row: (str(row["month"]), str(row["planning_bucket"])),
        )
        surface_breakdowns = {
            "economic_role": {
                "monthly_totals": _monthly_surface_breakdown(ledger, "economic_role"),
                "monthly_totals_by_month": _surface_monthly_breakdown_by_month(
                    ledger,
                    "economic_role",
                ),
                "bucket_totals": _surface_totals(ledger, "economic_role"),
            },
            "cashflow_type": {
                "monthly_totals": _monthly_surface_breakdown(ledger, "cashflow_type"),
                "monthly_totals_by_month": _surface_monthly_breakdown_by_month(
                    ledger,
                    "cashflow_type",
                ),
                "bucket_totals": _surface_totals(ledger, "cashflow_type"),
            },
            "decision_role": {
                "monthly_totals": _monthly_surface_breakdown(ledger, "decision_role"),
                "monthly_totals_by_month": _surface_monthly_breakdown_by_month(
                    ledger,
                    "decision_role",
                ),
                "bucket_totals": _surface_totals(ledger, "decision_role"),
            },
        }

    budget_actual_total = 0.0
    budget_target_total = 0.0
    budget_variance_total = 0.0
    budget_over_target_count = 0
    if not budget_status.empty:
        budget_actual_total = round(float(budget_status["actual_amount"].sum()), 2)
        budget_target_total = round(float(budget_status["budget_amount"].sum()), 2)
        budget_variance_total = round(float(budget_status["variance"].sum()), 2)
        budget_over_target_count = int(budget_status["status"].eq("over_budget").sum())

    return {
        "generated_at": generated_at,
        "ledger_rows": len(ledger),
        "month_min": month_min,
        "month_max": month_max,
        "ytd_year": ytd_year,
        "available_months": available_months,
        "available_years": available_years,
        "default_window": {
            "start_month": month_min,
            "end_month": month_max,
            "month": month_max,
            "year": ytd_year,
        },
        "totals_by_planning_bucket": _bucket_totals(ledger),
        "ytd_totals_by_planning_bucket": ytd_totals,
        "monthly_totals_by_planning_bucket": monthly_totals,
        "surface_breakdowns": surface_breakdowns,
        "cashflow_type_counts": _value_counts(ledger, "cashflow_type"),
        "economic_role_counts": _value_counts(ledger, "economic_role"),
        "decision_role_counts": _value_counts(ledger, "decision_role"),
        "budget_target_count": len(budget_config.targets),
        "budget_status_rows": len(budget_status),
        "budget_actual_total_eur": budget_actual_total,
        "budget_target_total_eur": budget_target_total,
        "budget_variance_total_eur": budget_variance_total,
        "budget_over_target_count": budget_over_target_count,
        "warnings": list(warnings),
    }


def _render_planning_stage_dashboard_html_legacy(
    dashboard_path: Path,
    *,
    kpi_summary: dict[str, object],
    budget_rows: list[dict[str, object]],
) -> Path:
    """Render a static planning dashboard from persisted stage artifacts."""
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    totals_by_bucket = _payload_mapping(kpi_summary, "totals_by_planning_bucket")
    surface_breakdowns = _payload_mapping(kpi_summary, "surface_breakdowns")
    monthly_totals_raw = kpi_summary.get("monthly_totals_by_planning_bucket", [])
    monthly_totals = (
        cast(list[dict[str, object]], monthly_totals_raw)
        if isinstance(monthly_totals_raw, list)
        else []
    )
    months = list(
        dict.fromkeys(
            str(row.get("month")) for row in monthly_totals if row.get("month") is not None
        )
    )
    month_start_options_html = (
        "\n".join(
            _month_option_html(month, selected=index == 0) for index, month in enumerate(months)
        )
        or '<option value="">No months available</option>'
    )
    month_end_options_html = (
        "\n".join(
            _month_option_html(month, selected=index == len(months) - 1)
            for index, month in enumerate(months)
        )
        or '<option value="">No months available</option>'
    )
    cards = [
        _summary_card("Income", f"{_payload_float(totals_by_bucket, 'income'):.2f}"),
        _summary_card("Expense", f"{_payload_float(totals_by_bucket, 'expense'):.2f}"),
        _summary_card("Savings", f"{_payload_float(totals_by_bucket, 'savings'):.2f}"),
        _summary_card(
            "Month range",
            f"{kpi_summary.get('month_min') or 'n/a'} to {kpi_summary.get('month_max') or 'n/a'}",
            detail=f"YTD: {kpi_summary.get('ytd_year') or 'n/a'}",
        ),
        _summary_card(
            "Budget variance",
            f"{_payload_float(kpi_summary, 'budget_variance_total_eur'):.2f}",
            detail=f"Targets loaded: {kpi_summary.get('budget_target_count', 0)}",
        ),
        _summary_card(
            "Over budget",
            kpi_summary.get("budget_over_target_count", 0),
        ),
    ]
    budget_rows_html = (
        "\n".join(
            f"""
        <tr>
          <td>{_row_text(row, "month")}</td>
          <td>{_row_text(row, "category")}</td>
          <td>{_row_text(row, "project")}</td>
          <td>{_row_float(row, "budget_amount"):.2f}</td>
          <td>{_row_float(row, "actual_amount"):.2f}</td>
          <td>{_row_float(row, "variance"):.2f}</td>
          <td>{_row_text(row, "status")}</td>
        </tr>
        """
            for row in budget_rows
        )
        or """
        <tr>
          <td colspan="7">No budget targets loaded.</td>
        </tr>
        """
    )
    surface_json = _serialize_payload(
        {
            "surface_breakdowns": surface_breakdowns,
            "available_months": months,
        }
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Planning Dashboard</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; color: #172026; background: #f7f9fb; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px; display: grid; gap: 20px; }}
    h1, h2 {{ margin: 0; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .card {{ background: #fff; border: 1px solid #d8e1e8; border-radius: 8px; padding: 16px; }}
    .label {{ color: #52616b; font-size: 12px; text-transform: uppercase; }}
    .value {{ font-size: 28px; font-weight: 750; margin-top: 4px; }}
    .detail {{ color: #52616b; font-size: 13px; margin-top: 4px; }}
    .panel {{
      background: #fff;
      border: 1px solid #d8e1e8;
      border-radius: 8px;
      padding: 16px;
      display: grid;
      gap: 12px;
    }}
    .controls {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      align-items: end;
    }}
    label {{ display: grid; gap: 6px; font-size: 13px; color: #52616b; }}
    select {{
      width: 100%;
      border: 1px solid #c7d2da;
      border-radius: 6px;
      padding: 8px 10px;
      background: #fff;
      color: #172026;
    }}
    .surface-summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
    }}
    .bar-table {{ width: 100%; border-collapse: collapse; }}
    .bar-track {{
      display: flex;
      width: 100%;
      height: 14px;
      background: #eef3f7;
      border-radius: 999px;
      overflow: hidden;
    }}
    .bar-segment {{ height: 100%; }}
    .bar-value {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8e1e8; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #e6edf2; text-align: left; }}
    th {{ font-size: 12px; color: #52616b; text-transform: uppercase; }}
  </style>
</head>
<body>
  <main>
    <h1>Planning Dashboard</h1>
    <section class="grid">
      {"".join(cards)}
    </section>
    <section class="panel">
      <div>
        <h2>Monthly Surface Explorer</h2>
        <div class="detail">
          Compare month-by-month splits across economic role, cashflow type, and decision role.
        </div>
      </div>
      <div class="controls">
        <label>
          From month
          <select id="month-start">{month_start_options_html}</select>
        </label>
        <label>
          To month
          <select id="month-end">{month_end_options_html}</select>
        </label>
      </div>
      <div class="surface-summary" id="surface-summary"></div>
    </section>
    <section class="panel">
      <div>
        <h2>Economic Role</h2>
        <div class="detail">Monthly operating structure by economic role.</div>
      </div>
      <div class="surface-summary" id="surface-summary-economic_role"></div>
      <table class="bar-table">
        <thead id="surface-table-head-economic_role"></thead>
        <tbody id="surface-table-body-economic_role"></tbody>
      </table>
    </section>
    <section class="panel">
      <div>
        <h2>Cashflow Type</h2>
        <div class="detail">Monthly cashflow distribution by cashflow type.</div>
      </div>
      <div class="surface-summary" id="surface-summary-cashflow_type"></div>
      <table class="bar-table">
        <thead id="surface-table-head-cashflow_type"></thead>
        <tbody id="surface-table-body-cashflow_type"></tbody>
      </table>
    </section>
    <section class="panel">
      <div>
        <h2>Decision Role</h2>
        <div class="detail">Monthly decision split by decision role.</div>
      </div>
      <div class="surface-summary" id="surface-summary-decision_role"></div>
      <table class="bar-table">
        <thead id="surface-table-head-decision_role"></thead>
        <tbody id="surface-table-body-decision_role"></tbody>
      </table>
    </section>
    <section class="panel">
      <div>
        <h2>Budget Status</h2>
        <div class="detail">Budget targets are loaded from the configured budget targets file.</div>
      </div>
      <table>
        <thead>
          <tr><th>Month</th><th>Category</th><th>Project</th><th>Budget</th><th>Actual</th><th>Variance</th><th>Status</th></tr>
        </thead>
        <tbody>
          {budget_rows_html}
        </tbody>
      </table>
    </section>
  </main>
  <script id="planning-stage-data" type="application/json">{surface_json}</script>
  <script>
    const payload = JSON.parse(document.getElementById("planning-stage-data").textContent);
    const months = [...new Set(payload.available_months || [])];
    const surfaces = payload.surface_breakdowns || {{}};
    const startSelect = document.getElementById("month-start");
    const endSelect = document.getElementById("month-end");
    const surfaceSummary = document.getElementById("surface-summary");
    const surfaceKeys = ["economic_role", "cashflow_type", "decision_role"];
    const surfaceLabels = {{
      economic_role: "Economic Role",
      cashflow_type: "Cashflow Type",
      decision_role: "Decision Role",
    }};

    function monthIndex(month) {{
      return months.indexOf(month);
    }}

    function monthInRange(month, start, end) {{
      const index = monthIndex(month);
      const startIndex = monthIndex(start);
      const endIndex = monthIndex(end);
      return index >= startIndex && index <= endIndex;
    }}

    function currency(value) {{
      return Number(value || 0).toLocaleString(undefined, {{
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }});
    }}

    function populateMonths() {{
      if (months.length > 0) {{
        startSelect.value = months[0];
        endSelect.value = months[months.length - 1];
      }}
    }}

    function renderSurface(surfaceKey) {{
      const surface = surfaces[surfaceKey] || {{}};
      const summary = document.getElementById(`surface-summary-${{surfaceKey}}`);
      const tableHead = document.getElementById(`surface-table-head-${{surfaceKey}}`);
      const tableBody = document.getElementById(`surface-table-body-${{surfaceKey}}`);

      if (months.length === 0) {{
        summary.innerHTML = (
          '<div class="card"><div class="label">No data</div>'
          '<div class="value">n/a</div></div>'
        );
        tableHead.innerHTML = "";
        tableBody.innerHTML = '<tr><td>No planning surface data available.</td></tr>';
        return;
      }}

      const rows = (surface.monthly_totals || []).filter((row) =>
        monthInRange(row.month, startSelect.value, endSelect.value)
      );

      const buckets = [...new Set(rows.map((row) => row.bucket))].sort((left, right) =>
        String(left).localeCompare(String(right))
      );
      const selectedMonths = months.filter((month) =>
        monthInRange(month, startSelect.value, endSelect.value)
      );
      const monthMap = new Map();

      selectedMonths.forEach((month) => monthMap.set(month, new Map()));
      rows.forEach((row) => {{
        const monthMapEntry = monthMap.get(row.month) || new Map();
        monthMapEntry.set(row.bucket, Number(row.amount_eur || 0));
        monthMap.set(row.month, monthMapEntry);
      }});

      const selectedRows = rows.length;
      const total = rows.reduce((sum, row) => sum + Number(row.amount_eur || 0), 0);
      const periodTotals = surface.bucket_totals || {{}};
      const periodCards = Object.entries(periodTotals).sort((left, right) =>
        String(left[0]).localeCompare(String(right[0]))
      );
      summary.innerHTML = [
        ['Surface', surfaceLabels[surfaceKey] || surfaceKey.replaceAll('_', ' ')],
        [
          'Months',
          `${{selectedMonths[0] || 'n/a'}} to `
          + `${{selectedMonths[selectedMonths.length - 1] || 'n/a'}}`,
        ],
        ['Buckets', buckets.length.toString()],
        ['Rows', selectedRows.toString()],
        ['Total', currency(total)],
      ].map(([label, value]) => `
        <div class="card">
          <div class="label">${{label}}</div>
          <div class="value">${{value}}</div>
        </div>
      `).join("");
      if (periodCards.length > 0) {{
        summary.innerHTML += periodCards.map(([label, value]) => `
          <div class="card">
            <div class="label">${{label}}</div>
            <div class="value">${{currency(value)}}</div>
          </div>
        `).join("");
      }}

      tableHead.innerHTML = `
        <tr>
          <th>Month</th>
          ${{buckets.map((bucket) => `<th>${{bucket}}</th>`).join("")}}
          <th>Total</th>
        </tr>
      `;

      tableBody.innerHTML = selectedMonths.map((month) => {{
        const monthTotals = monthMap.get(month) || new Map();
        const rowTotal = buckets.reduce(
          (sum, bucket) => sum + Number(monthTotals.get(bucket) || 0),
          0
        );
        const cells = buckets
          .map((bucket) => `<td>${{currency(monthTotals.get(bucket) || 0)}}</td>`)
          .join("");
        return `
          <tr>
            <td>${{month}}</td>
            ${{cells}}
            <td class="bar-value">${{currency(rowTotal)}}</td>
          </tr>
        `;
      }}).join("");
    }}

    populateMonths();
    startSelect.addEventListener("change", () => {{
      if (monthIndex(startSelect.value) > monthIndex(endSelect.value)) {{
        endSelect.value = startSelect.value;
      }}
      renderAllSurfaces();
    }});
    endSelect.addEventListener("change", () => {{
      if (monthIndex(startSelect.value) > monthIndex(endSelect.value)) {{
        startSelect.value = endSelect.value;
      }}
      renderAllSurfaces();
    }});
    function renderAllSurfaces() {{
      surfaceKeys.forEach((surfaceKey) => renderSurface(surfaceKey));
    }}
    renderAllSurfaces();
  </script>
</body>
</html>
"""
    dashboard_path.write_text(html, encoding="utf-8")
    return dashboard_path


def render_planning_stage_dashboard_html(
    dashboard_path: Path,
    *,
    kpi_summary: dict[str, object],
    budget_rows: list[dict[str, object]],
) -> Path:
    """Render the month-window planning dashboard from persisted stage artifacts."""
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    surface_breakdowns = _payload_mapping(kpi_summary, "surface_breakdowns")
    available_months_raw = kpi_summary.get("available_months", [])
    if isinstance(available_months_raw, list):
        available_months = [str(month) for month in available_months_raw if month is not None]
    else:
        available_months = []
    if not available_months:
        month_candidates: list[str] = []
        for surface in surface_breakdowns.values():
            if not isinstance(surface, dict):
                continue
            surface_mapping = cast(dict[str, object], surface)
            monthly_by_month = surface_mapping.get("monthly_totals_by_month")
            if isinstance(monthly_by_month, dict):
                month_candidates.extend(str(month) for month in monthly_by_month.keys())
        available_months = list(dict.fromkeys(month_candidates))
    available_years_raw = kpi_summary.get("available_years", [])
    if isinstance(available_years_raw, list) and available_years_raw:
        available_years = [str(year) for year in available_years_raw if year is not None]
    else:
        available_years = _available_years(available_months)
    surface_breakdowns = _normalize_surface_breakdowns(surface_breakdowns)

    month_start_options_html = (
        "\n".join(
            _month_option_html(month, selected=index == 0)
            for index, month in enumerate(available_months)
        )
        or '<option value="">No months available</option>'
    )
    month_end_options_html = (
        "\n".join(
            _month_option_html(month, selected=index == len(available_months) - 1)
            for index, month in enumerate(available_months)
        )
        or '<option value="">No months available</option>'
    )
    quick_month_options_html = (
        "\n".join(
            _month_option_html(month, selected=index == len(available_months) - 1)
            for index, month in enumerate(available_months)
        )
        or '<option value="">No months available</option>'
    )
    quick_year_options_html = (
        "\n".join(
            _option_html(year, year, selected=index == len(available_years) - 1)
            for index, year in enumerate(available_years)
        )
        or '<option value="">No years available</option>'
    )
    budget_rows_html = (
        "\n".join(
            f"""
        <tr>
          <td>{_row_text(row, "month")}</td>
          <td>{_row_text(row, "category")}</td>
          <td>{_row_text(row, "project")}</td>
          <td class="amount">{_row_float(row, "budget_amount"):.2f}</td>
          <td class="amount">{_row_float(row, "actual_amount"):.2f}</td>
          <td class="amount">{_row_float(row, "variance"):.2f}</td>
          <td>{_row_text(row, "status")}</td>
        </tr>
        """
            for row in budget_rows
        )
        or """
        <tr>
          <td colspan="7">No budget targets loaded.</td>
        </tr>
        """
    )
    surface_json = _serialize_payload(
        {
            "surface_breakdowns": surface_breakdowns,
            "available_months": available_months,
            "available_years": available_years,
            "default_window": kpi_summary.get("default_window", {}),
        }
    )
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Planning Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4efe6;
      --panel: rgba(255, 250, 244, 0.92);
      --ink: #1f1813;
      --muted: #695f54;
      --line: #d9cab8;
      --accent: #8f5f35;
      --shadow: 0 20px 44px rgba(62, 45, 29, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(143, 95, 53, 0.15), transparent 34%),
        radial-gradient(circle at bottom right, rgba(79, 115, 88, 0.16), transparent 28%),
        linear-gradient(180deg, #f7f0e6, var(--bg));
      min-height: 100vh;
    }
    .shell {
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      gap: 18px;
    }
    .hero, .panel, .chart-card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }
    .hero {
      padding: 24px;
      display: grid;
      gap: 12px;
    }
    h1 {
      margin: 0;
      font-family: "IBM Plex Serif", Georgia, serif;
      font-size: clamp(30px, 4vw, 44px);
      letter-spacing: -0.03em;
    }
    h2, h3 { margin: 0; }
    h2 { font-size: 20px; color: var(--accent); }
    h3 { font-size: 18px; }
    .hero p, .muted, .chart-note { margin: 0; color: var(--muted); }
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
      background: rgba(143, 95, 53, 0.08);
      border: 1px solid var(--line);
    }
    .panel {
      padding: 18px;
      display: grid;
      gap: 16px;
    }
    .panel-header {
      display: grid;
      gap: 6px;
    }
    .controls-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
      gap: 14px;
      align-items: start;
    }
    .control-group {
      display: grid;
      gap: 12px;
      padding: 14px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.55);
      border: 1px solid var(--line);
    }
    .control-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    select, button {
      width: 100%;
      border-radius: 12px;
      border: 1px solid var(--line);
      padding: 11px 12px;
      font: inherit;
    }
    select {
      background: rgba(255, 255, 255, 0.92);
      color: var(--ink);
    }
    button {
      cursor: pointer;
      background: linear-gradient(135deg, var(--accent), #6f4726);
      color: #fffaf4;
      font-weight: 700;
      letter-spacing: 0.01em;
      box-shadow: 0 10px 18px rgba(143, 95, 53, 0.18);
    }
    .window-summary {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.66);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 14px;
    }
    .charts-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }
    .chart-card {
      padding: 16px;
      display: grid;
      gap: 10px;
      position: relative;
      overflow: hidden;
    }
    .chart-card svg {
      width: 100%;
      height: 270px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.76);
      border: 1px solid var(--line);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid rgba(217, 202, 184, 0.82);
    }
    .legend-swatch {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      flex: 0 0 auto;
    }
    .legend-amount {
      font-variant-numeric: tabular-nums;
      color: var(--ink);
    }
    .chart-tooltip {
      position: absolute;
      min-width: 220px;
      max-width: 300px;
      pointer-events: none;
      opacity: 0;
      transform: translate(16px, 16px);
      padding: 12px 14px;
      border-radius: 12px;
      background: rgba(31, 24, 19, 0.96);
      color: #fffaf4;
      box-shadow: 0 16px 28px rgba(31, 24, 19, 0.24);
      transition: opacity 120ms ease;
      z-index: 2;
    }
    .chart-tooltip.visible { opacity: 1; }
    .chart-tooltip .title {
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 6px;
      color: #f4d0a5;
    }
    .chart-tooltip .context {
      font-size: 12px;
      color: #dbcbb8;
      margin-bottom: 10px;
    }
    .chart-tooltip .row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      margin-top: 4px;
    }
    .chart-tooltip .label { color: #d8cab8; }
    .chart-tooltip .value {
      font-variant-numeric: tabular-nums;
      text-align: right;
    }
    .budget-table {
      width: 100%;
      border-collapse: collapse;
      background: rgba(255, 255, 255, 0.76);
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      font-size: 14px;
    }
    .budget-table th, .budget-table td {
      padding: 10px 12px;
      border-bottom: 1px solid #eadfd1;
      text-align: left;
    }
    .budget-table th {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      background: rgba(255, 250, 244, 0.84);
    }
    .budget-table td.amount {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    @media (max-width: 1180px) {
      .charts-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 760px) {
      .shell { padding: 16px; }
      .hero, .panel { padding: 16px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <h1>Planning Dashboard</h1>
      <p>Explore how the planning ledger splits across economic role, cashflow type, and decision role for any month window.</p>
      <div class="meta-row">
        <span class="pill">Ledger rows: __LEDGER_ROWS__</span>
        <span class="pill">Available months: __MONTH_COUNT__</span>
        <span class="pill">Available years: __YEAR_COUNT__</span>
        <span class="pill">Budget targets: __BUDGET_TARGET_COUNT__</span>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h2>Monthly Surface Explorer</h2>
        <div class="muted">Select a month range, snap to a single month, or jump to an entire year.</div>
      </div>
      <div class="controls-grid">
        <div class="control-group">
          <div class="control-grid">
            <label>
              From month
              <select id="month-start">__MONTH_START_OPTIONS__</select>
            </label>
            <label>
              To month
              <select id="month-end">__MONTH_END_OPTIONS__</select>
            </label>
          </div>
        </div>
        <div class="control-group">
          <div class="control-grid">
            <label>
              Specific month
              <select id="quick-month">__QUICK_MONTH_OPTIONS__</select>
            </label>
            <button id="apply-month" type="button">Use month</button>
            <label>
              Full year
              <select id="quick-year">__QUICK_YEAR_OPTIONS__</select>
            </label>
            <button id="apply-year" type="button">Use year</button>
          </div>
        </div>
      </div>
      <div id="window-summary" class="window-summary"></div>
      <div class="charts-grid">
        <article class="chart-card" data-surface="economic_role">
          <div class="panel-header">
            <h3>Economic Role</h3>
            <div class="chart-note" id="chart-note-economic_role"></div>
          </div>
          <svg id="chart-economic_role" viewBox="0 0 320 270" preserveAspectRatio="xMidYMid meet"></svg>
          <div class="legend" id="legend-economic_role"></div>
        </article>
        <article class="chart-card" data-surface="cashflow_type">
          <div class="panel-header">
            <h3>Cashflow Type</h3>
            <div class="chart-note" id="chart-note-cashflow_type"></div>
          </div>
          <svg id="chart-cashflow_type" viewBox="0 0 320 270" preserveAspectRatio="xMidYMid meet"></svg>
          <div class="legend" id="legend-cashflow_type"></div>
        </article>
        <article class="chart-card" data-surface="decision_role">
          <div class="panel-header">
            <h3>Decision Role</h3>
            <div class="chart-note" id="chart-note-decision_role"></div>
          </div>
          <svg id="chart-decision_role" viewBox="0 0 320 270" preserveAspectRatio="xMidYMid meet"></svg>
          <div class="legend" id="legend-decision_role"></div>
        </article>
      </div>
      <div id="chart-tooltip" class="chart-tooltip"></div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h2>Budget Status</h2>
        <div class="muted">Budget targets are loaded from the configured budget targets file.</div>
      </div>
      <table class="budget-table">
        <thead>
          <tr><th>Month</th><th>Category</th><th>Project</th><th>Budget</th><th>Actual</th><th>Variance</th><th>Status</th></tr>
        </thead>
        <tbody>
          __BUDGET_ROWS__
        </tbody>
      </table>
    </section>
  </main>
  <script id="planning-stage-data" type="application/json">__PAYLOAD_JSON__</script>
  <script>
    const payload = JSON.parse(document.getElementById("planning-stage-data").textContent);
    const months = Array.isArray(payload.available_months) ? payload.available_months.slice() : [];
    const years = Array.isArray(payload.available_years) ? payload.available_years.slice() : [];
    const surfaces = payload.surface_breakdowns || {};
    const defaultWindow = payload.default_window || {};
    const startSelect = document.getElementById("month-start");
    const endSelect = document.getElementById("month-end");
    const quickMonthSelect = document.getElementById("quick-month");
    const quickYearSelect = document.getElementById("quick-year");
    const applyMonthButton = document.getElementById("apply-month");
    const applyYearButton = document.getElementById("apply-year");
    const windowSummary = document.getElementById("window-summary");
    const chartTooltip = document.getElementById("chart-tooltip");
    const surfaceKeys = ["economic_role", "cashflow_type", "decision_role"];
    const surfaceLabels = {
      economic_role: "Economic Role",
      cashflow_type: "Cashflow Type",
      decision_role: "Decision Role",
    };
    const palette = ["#9a6b4c", "#4f7358", "#6f86b8", "#c36a5c", "#7c8f43", "#a0739f", "#d08b47", "#567f8c"];
    const fixedBucketColors = {
      in: "#2563eb",
      out: "#d97706",
      income: "#2563eb",
      expense: "#b45309",
      fixed_expense: "#92400e",
      variable_expense: "#d97706",
      savings: "#0f766e",
      investment: "#7c3aed",
      debt_service: "#be185d",
      tax: "#0f766e",
      essential: "#0f766e",
      discretionary: "#b91c1c",
      non_spend: "#8f8a83",
      unknown: "#8f8a83",
      excluded: "#8f8a83",
      transfer: "#5f7fa8",
      exclude: "#6b7280",
    };

    function monthIndex(month) {
      return months.indexOf(month);
    }

    function normalizeWindow(start, end) {
      if (!months.length) {
        return ["", ""];
      }
      const first = start && months.includes(start) ? start : months[0];
      const last = end && months.includes(end) ? end : months[months.length - 1];
      if (monthIndex(first) <= monthIndex(last)) {
        return [first, last];
      }
      return [last, first];
    }

    function currency(value) {
      return Number(value || 0).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    }

    function percent(value) {
      return (Number(value || 0) * 100).toFixed(1) + "%";
    }

    function displayBucketLabel(bucket) {
      const normalized = normalizedBucketKey(bucket);
      if (normalized === "non_spend") {
        return "Non spend";
      }
      if (normalized === "unknown" || normalized === "") {
        return "Unknown";
      }
      if (normalized === "excluded") {
        return "Non spend";
      }
      return bucket;
    }

    function normalizedBucketKey(bucket) {
      return String(bucket || "").trim().toLowerCase();
    }

    function bucketColor(bucket) {
      const key = normalizedBucketKey(bucket);
      if (Object.prototype.hasOwnProperty.call(fixedBucketColors, key)) {
        return fixedBucketColors[key];
      }
      let hash = 0;
      for (let index = 0; index < key.length; index += 1) {
        hash = (hash * 31 + key.charCodeAt(index)) >>> 0;
      }
      return palette[hash % palette.length];
    }

    function setSelectOptions(select, values, selectedValue, emptyLabel) {
      select.innerHTML = "";
      if (!values.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = emptyLabel;
        option.selected = true;
        select.appendChild(option);
        return;
      }
      values.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        option.selected = value === selectedValue;
        select.appendChild(option);
      });
    }

    function selectedMonths() {
      if (!months.length) {
        return [];
      }
      const start = monthIndex(startSelect.value);
      const end = monthIndex(endSelect.value);
      if (start < 0 || end < 0) {
        return months.slice();
      }
      return months.slice(Math.min(start, end), Math.max(start, end) + 1);
    }

    function windowLabel(windowMonths) {
      if (!windowMonths.length) {
        return "No months available";
      }
      if (windowMonths.length === 1) {
        return `Selected month: ${windowMonths[0]}`;
      }
      return `Selected window: ${windowMonths[0]} to ${windowMonths[windowMonths.length - 1]} (${windowMonths.length} months)`;
    }

    function aggregateSurface(surfaceKey, windowMonths) {
      const monthly = ((surfaces[surfaceKey] || {}).monthly_totals_by_month) || {};
      const totals = {};
      windowMonths.forEach((month) => {
        const monthData = monthly[month] || {};
        Object.entries(monthData).forEach(([bucket, amount]) => {
          const normalizedBucket = displayBucketLabel(normalizedBucketKey(bucket));
          totals[normalizedBucket] = (totals[normalizedBucket] || 0) + Number(amount || 0);
        });
      });
      return Object.entries(totals)
        .filter(([, amount]) => Math.abs(Number(amount || 0)) > 1e-9)
        .sort((left, right) => {
          const amountDelta = Number(right[1] || 0) - Number(left[1] || 0);
          return Math.abs(amountDelta) > 1e-9
            ? amountDelta
            : String(left[0]).localeCompare(String(right[0]));
        });
    }

    function createSvgElement(tag) {
      return document.createElementNS("http://www.w3.org/2000/svg", tag);
    }

    function arcPath(cx, cy, radius, startAngle, endAngle) {
      const startX = cx + radius * Math.cos(startAngle);
      const startY = cy + radius * Math.sin(startAngle);
      const endX = cx + radius * Math.cos(endAngle);
      const endY = cy + radius * Math.sin(endAngle);
      const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
      return `M ${cx} ${cy} L ${startX.toFixed(2)} ${startY.toFixed(2)} A ${radius} ${radius} 0 ${largeArc} 1 ${endX.toFixed(2)} ${endY.toFixed(2)} Z`;
    }

    function fullCirclePath(cx, cy, radius) {
      return [
        `M ${cx} ${(cy - radius).toFixed(2)}`,
        `A ${radius} ${radius} 0 1 1 ${cx} ${(cy + radius).toFixed(2)}`,
        `A ${radius} ${radius} 0 1 1 ${cx} ${(cy - radius).toFixed(2)} Z`,
      ].join(" ");
    }

    function hideTooltip() {
      chartTooltip.classList.remove("visible");
    }

    function showTooltip(event, html) {
      const bounds = event.currentTarget.getBoundingClientRect();
      chartTooltip.innerHTML = html;
      chartTooltip.style.left = `${event.clientX - bounds.left + 16}px`;
      chartTooltip.style.top = `${event.clientY - bounds.top + 16}px`;
      chartTooltip.classList.add("visible");
    }

    function renderSurface(surfaceKey, windowMonths) {
      const svg = document.getElementById(`chart-${surfaceKey}`);
      const legend = document.getElementById(`legend-${surfaceKey}`);
      const note = document.getElementById(`chart-note-${surfaceKey}`);
      const buckets = aggregateSurface(surfaceKey, windowMonths);
      const total = buckets.reduce((sum, [, amount]) => sum + Number(amount || 0), 0);
      const context = windowLabel(windowMonths);
      svg.innerHTML = "";
      legend.innerHTML = "";
      note.textContent = total > 0
        ? `Total ${currency(total)} across ${buckets.length} buckets.`
        : "No data for the selected window.";

      if (!buckets.length || total <= 0) {
        const empty = createSvgElement("text");
        empty.setAttribute("x", "160");
        empty.setAttribute("y", "128");
        empty.setAttribute("text-anchor", "middle");
        empty.setAttribute("fill", "#7b7168");
        empty.setAttribute("font-size", "14");
        empty.textContent = "No planning data";
        svg.appendChild(empty);
        return;
      }

      const cx = 160;
      const cy = 118;
      const radius = 84;
      let startAngle = -Math.PI / 2;
      buckets.forEach(([label, amount], index) => {
        const value = Number(amount || 0);
        const share = value / total;
        const endAngle = startAngle + ((Math.PI * 2) * share);
        const color = bucketColor(label);
        const path = createSvgElement("path");
        path.setAttribute("fill", color);
        path.setAttribute("stroke", "rgba(255,250,244,0.92)");
        path.setAttribute("stroke-width", "2");
        path.setAttribute(
          "d",
          share >= 0.999999 ? fullCirclePath(cx, cy, radius) : arcPath(cx, cy, radius, startAngle, endAngle)
        );
        path.setAttribute("tabindex", "0");
        path.setAttribute(
          "aria-label",
          `${surfaceLabels[surfaceKey]} slice ${displayBucketLabel(label)} representing ${percent(share)}`
        );
        const tooltipHtml = [
          `<div class="title">${surfaceLabels[surfaceKey]}</div>`,
          `<div class="context">${context}</div>`,
          `<div class="row"><span class="label">Slice</span><span class="value">${displayBucketLabel(label)}</span></div>`,
          `<div class="row"><span class="label">Amount</span><span class="value">${currency(value)}</span></div>`,
          `<div class="row"><span class="label">Share</span><span class="value">${percent(share)}</span></div>`
        ].join("");
        path.addEventListener("mouseenter", (event) => showTooltip(event, tooltipHtml));
        path.addEventListener("mousemove", (event) => showTooltip(event, tooltipHtml));
        path.addEventListener("mouseleave", hideTooltip);
        path.addEventListener("blur", hideTooltip);
        svg.appendChild(path);
        startAngle = endAngle;

        const legendItem = document.createElement("div");
        legendItem.className = "legend-item";
        legendItem.innerHTML =
          `<span class="legend-swatch" style="background:${color}"></span>` +
          `<span>${displayBucketLabel(label)}</span>` +
          `<span class="legend-amount">${currency(value)}</span>`;
        legend.appendChild(legendItem);
      });
    }

    function renderWindow() {
      const windowMonths = selectedMonths();
      windowSummary.textContent = windowLabel(windowMonths);
      surfaceKeys.forEach((surfaceKey) => renderSurface(surfaceKey, windowMonths));
    }

    function applyMonthPreset() {
      if (!months.length) {
        return;
      }
      const selectedMonth = quickMonthSelect.value || months[months.length - 1];
      startSelect.value = selectedMonth;
      endSelect.value = selectedMonth;
      renderWindow();
    }

    function applyYearPreset() {
      if (!months.length) {
        return;
      }
      const selectedYear = quickYearSelect.value || years[years.length - 1];
      const yearMonths = months.filter((month) => month.startsWith(`${selectedYear}-`));
      if (!yearMonths.length) {
        return;
      }
      startSelect.value = yearMonths[0];
      endSelect.value = yearMonths[yearMonths.length - 1];
      renderWindow();
    }

    setSelectOptions(startSelect, months, defaultWindow.start_month || months[0], "No months available");
    setSelectOptions(endSelect, months, defaultWindow.end_month || months[months.length - 1], "No months available");
    setSelectOptions(quickMonthSelect, months, defaultWindow.month || months[months.length - 1], "No months available");
    setSelectOptions(quickYearSelect, years, defaultWindow.year || years[years.length - 1], "No years available");

    if (months.length > 0) {
      const [startMonth, endMonth] = normalizeWindow(defaultWindow.start_month, defaultWindow.end_month);
      startSelect.value = startMonth;
      endSelect.value = endMonth;
    }

    startSelect.addEventListener("change", () => {
      if (monthIndex(startSelect.value) > monthIndex(endSelect.value)) {
        endSelect.value = startSelect.value;
      }
      renderWindow();
    });
    endSelect.addEventListener("change", () => {
      if (monthIndex(startSelect.value) > monthIndex(endSelect.value)) {
        startSelect.value = endSelect.value;
      }
      renderWindow();
    });
    applyMonthButton.addEventListener("click", applyMonthPreset);
    applyYearButton.addEventListener("click", applyYearPreset);
    chartTooltip.addEventListener("mouseleave", hideTooltip);

    renderWindow();
    hideTooltip();
  </script>
</body>
</html>
"""
    html = html.replace("__LEDGER_ROWS__", str(kpi_summary.get("ledger_rows", 0)))
    html = html.replace("__MONTH_COUNT__", str(len(available_months)))
    html = html.replace("__YEAR_COUNT__", str(len(available_years)))
    html = html.replace("__BUDGET_TARGET_COUNT__", str(kpi_summary.get("budget_target_count", 0)))
    html = html.replace("__MONTH_START_OPTIONS__", month_start_options_html)
    html = html.replace("__MONTH_END_OPTIONS__", month_end_options_html)
    html = html.replace("__QUICK_MONTH_OPTIONS__", quick_month_options_html)
    html = html.replace("__QUICK_YEAR_OPTIONS__", quick_year_options_html)
    html = html.replace("__BUDGET_ROWS__", budget_rows_html)
    html = html.replace("__PAYLOAD_JSON__", surface_json)
    dashboard_path.write_text(html, encoding="utf-8")
    return dashboard_path


def run_planning(
    settings: Settings,
    *,
    input_transactions_path: Path | None = None,
    output_dir: Path | None = None,
    budget_targets_path: Path | None = None,
) -> PlanningExecutionResult:
    """Execute planning stage and write planning artifacts."""
    resolved_input = input_transactions_path or resolve_transform_artifact_path(
        settings,
        settings.master_parquet_path,
    )
    resolved_output_dir = output_dir or planning_root_path(settings)
    resolved_budget_path = budget_targets_path or settings.budget_targets_path

    progress = tqdm(
        total=5,
        desc="Planning",
        unit="step",
        disable=not sys.stderr.isatty(),
        leave=False,
    )
    progress.set_postfix_str("load transactions")
    transactions = _load_transactions(resolved_input)
    progress.update()
    progress.set_postfix_str("load config")
    classification_rules, rule_warnings = load_classification_rules(settings.category_rules_path)
    budget_config, budget_warnings = load_budget_config(resolved_budget_path)
    warnings = [*rule_warnings, *budget_warnings]
    if not resolved_budget_path.exists():
        warnings.append(
            f"Budget targets file not found; using empty budget config: {resolved_budget_path}"
        )
    progress.update()
    progress.set_postfix_str("build ledger")
    ledger = build_monthly_planning_ledger(
        transactions,
        classification_rules=classification_rules,
    )
    progress.update()
    progress.set_postfix_str("build budget status")
    budget_status = build_budget_status(
        transactions,
        budget_config,
        ledger=ledger,
        classification_rules=classification_rules,
    )
    kpi_summary = build_planning_kpi_summary(
        ledger,
        budget_status,
        budget_config=budget_config,
        warnings=tuple(warnings),
    )
    kpi_summary["input_transactions_path"] = str(resolved_input)
    kpi_summary["budget_targets_path"] = str(resolved_budget_path)
    progress.update()

    ledger_path = resolved_output_dir / PLANNING_LEDGER_FILENAME
    ledger_csv_path = resolved_output_dir / PLANNING_LEDGER_CSV_FILENAME
    kpi_summary_path = resolved_output_dir / PLANNING_KPI_SUMMARY_FILENAME
    budget_status_path = resolved_output_dir / PLANNING_BUDGET_STATUS_FILENAME
    dashboard_path = resolved_output_dir / PLANNING_DASHBOARD_FILENAME

    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    progress.set_postfix_str("write artifacts")
    ledger.to_parquet(ledger_path, index=False)
    ledger.to_csv(ledger_csv_path, index=False)
    budget_status.to_csv(budget_status_path, index=False)
    write_json(kpi_summary_path, kpi_summary)
    render_planning_stage_dashboard_html(
        dashboard_path,
        kpi_summary=kpi_summary,
        budget_rows=budget_status.to_dict(orient="records"),
    )
    progress.update()
    progress.close()

    return PlanningExecutionResult(
        ledger_path=ledger_path,
        ledger_csv_path=ledger_csv_path,
        kpi_summary_path=kpi_summary_path,
        budget_status_path=budget_status_path,
        dashboard_path=dashboard_path,
        input_transactions_path=resolved_input,
        ledger_rows=len(ledger),
        budget_status_rows=len(budget_status),
        warnings=tuple(warnings),
    )

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
    totals = frame.groupby(column, dropna=False)["planning_amount_eur"].sum()
    return {
        "unknown" if pd.isna(bucket) else str(bucket): round(float(amount), 2)
        for bucket, amount in totals.items()
    }


def _monthly_surface_breakdown(frame: pd.DataFrame, column: str) -> list[dict[str, object]]:
    if frame.empty or column not in frame.columns:
        return []
    grouped = frame.groupby(["month", column], dropna=False)["planning_amount_eur"].sum()
    rows: list[dict[str, object]] = []
    for (month, bucket), amount in grouped.items():
        rows.append(
            {
                "month": str(month),
                "bucket": "unknown" if pd.isna(bucket) else str(bucket),
                "amount_eur": round(float(amount), 2),
            }
        )
    rows.sort(key=lambda row: (str(row["month"]), str(row["bucket"])))
    return rows


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
        ytd_totals: dict[str, float] = {}
        monthly_totals: list[dict[str, object]] = []
        surface_breakdowns: dict[str, dict[str, object]] = {}
    else:
        month_values = ledger["month"].dropna().astype("string")
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
                "bucket_totals": _surface_totals(ledger, "economic_role"),
            },
            "cashflow_type": {
                "monthly_totals": _monthly_surface_breakdown(ledger, "cashflow_type"),
                "bucket_totals": _surface_totals(ledger, "cashflow_type"),
            },
            "decision_role": {
                "monthly_totals": _monthly_surface_breakdown(ledger, "decision_role"),
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


def render_planning_stage_dashboard_html(
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
    months = [str(row.get("month")) for row in monthly_totals if row.get("month") is not None]
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
        <h2>Surface Explorer</h2>
        <div class="detail">
          Compare monthly splits across economic role, cashflow type, and decision role.
        </div>
      </div>
      <div class="controls">
        <label>
          Surface
          <select id="surface-select">
            <option value="economic_role">Economic role</option>
            <option value="cashflow_type">Cashflow type</option>
            <option value="decision_role">Decision role</option>
          </select>
        </label>
        <label>
          From month
          <select id="month-start"></select>
        </label>
        <label>
          To month
          <select id="month-end"></select>
        </label>
      </div>
      <div class="surface-summary" id="surface-summary"></div>
      <table class="bar-table">
        <thead id="surface-table-head"></thead>
        <tbody id="surface-table-body"></tbody>
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
    const months = payload.available_months || [];
    const surfaces = payload.surface_breakdowns || {{}};
    const surfaceSelect = document.getElementById("surface-select");
    const startSelect = document.getElementById("month-start");
    const endSelect = document.getElementById("month-end");
    const summary = document.getElementById("surface-summary");
    const tableHead = document.getElementById("surface-table-head");
    const tableBody = document.getElementById("surface-table-body");

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
      const options = months
        .map((month) => `<option value="${{month}}">${{month}}</option>`)
        .join("");
      startSelect.innerHTML = options;
      endSelect.innerHTML = options;
      if (months.length > 0) {{
        startSelect.value = months[0];
        endSelect.value = months[months.length - 1];
      }}
    }}

    function renderSurface() {{
      if (months.length === 0) {{
        summary.innerHTML = (
          '<div class="card"><div class="label">No data</div>'
          '<div class="value">n/a</div></div>'
        );
        tableHead.innerHTML = "";
        tableBody.innerHTML = '<tr><td>No planning surface data available.</td></tr>';
        return;
      }}

      const surfaceKey = surfaceSelect.value;
      const surface = surfaces[surfaceKey] || {{}};
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
        ['Surface', surfaceKey.replaceAll('_', ' ')],
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
    surfaceSelect.addEventListener("change", renderSurface);
    startSelect.addEventListener("change", () => {{
      if (monthIndex(startSelect.value) > monthIndex(endSelect.value)) {{
        endSelect.value = startSelect.value;
      }}
      renderSurface();
    }});
    endSelect.addEventListener("change", () => {{
      if (monthIndex(startSelect.value) > monthIndex(endSelect.value)) {{
        startSelect.value = endSelect.value;
      }}
      renderSurface();
    }});
    renderSurface();
  </script>
</body>
</html>
"""
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

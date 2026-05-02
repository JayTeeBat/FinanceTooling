"""Planning stage orchestration from canonical transactions to decision artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

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


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {
        str(index): int(value)
        for index, value in frame[column].fillna("unknown").astype("string").value_counts().items()
    }


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


def _serialize_payload(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return serialized.replace("</", "<\\/")


def render_planning_stage_dashboard_html(
    dashboard_path: Path,
    *,
    kpi_summary: dict[str, object],
    budget_rows: list[dict[str, object]],
) -> Path:
    """Render a small self-contained planning dashboard from persisted stage artifacts."""
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_payload({"kpis": kpi_summary, "budget_status": budget_rows})
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
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8e1e8; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #e6edf2; text-align: left; }}
    th {{ font-size: 12px; color: #52616b; text-transform: uppercase; }}
  </style>
</head>
<body>
  <main>
    <h1>Planning Dashboard</h1>
    <section class="grid" id="kpis"></section>
    <section>
      <h2>Budget Status</h2>
      <table>
        <thead><tr><th>Month</th><th>Category</th><th>Budget</th><th>Actual</th><th>Status</th></tr></thead>
        <tbody id="budget"></tbody>
      </table>
    </section>
  </main>
  <script id="planning-stage-data" type="application/json">{payload}</script>
  <script>
    const payload = JSON.parse(document.getElementById("planning-stage-data").textContent);
    const kpis = payload.kpis;
    const cards = [
      ["Ledger rows", kpis.ledger_rows],
      ["Month range", `${{kpis.month_min || "n/a"}} to ${{kpis.month_max || "n/a"}}`],
      ["Expense", (kpis.totals_by_planning_bucket.expense || 0).toFixed(2)],
      ["Savings", (kpis.totals_by_planning_bucket.savings || 0).toFixed(2)],
      ["Budget variance", kpis.budget_variance_total_eur.toFixed(2)],
      ["Over budget", kpis.budget_over_target_count],
    ];
    document.getElementById("kpis").innerHTML = cards.map(([label, value]) =>
      `<div class="card"><div class="label">${{label}}</div>` +
      `<div class="value">${{value}}</div></div>`
    ).join("");
    document.getElementById("budget").innerHTML = payload.budget_status.map(row =>
      `<tr><td>${{row.month}}</td><td>${{row.category}}</td><td>${{row.budget_amount}}</td><td>${{row.actual_amount}}</td><td>${{row.status}}</td></tr>`
    ).join("");
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

    transactions = _load_transactions(resolved_input)
    classification_rules, rule_warnings = load_classification_rules(settings.category_rules_path)
    budget_config, budget_warnings = load_budget_config(resolved_budget_path)
    warnings = [*rule_warnings, *budget_warnings]
    if not resolved_budget_path.exists():
        warnings.append(
            "Budget targets file not found; using empty budget config: "
            f"{resolved_budget_path}"
        )

    ledger = build_monthly_planning_ledger(
        transactions,
        classification_rules=classification_rules,
    )
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

    ledger_path = resolved_output_dir / PLANNING_LEDGER_FILENAME
    ledger_csv_path = resolved_output_dir / PLANNING_LEDGER_CSV_FILENAME
    kpi_summary_path = resolved_output_dir / PLANNING_KPI_SUMMARY_FILENAME
    budget_status_path = resolved_output_dir / PLANNING_BUDGET_STATUS_FILENAME
    dashboard_path = resolved_output_dir / PLANNING_DASHBOARD_FILENAME

    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    ledger.to_parquet(ledger_path, index=False)
    ledger.to_csv(ledger_csv_path, index=False)
    budget_status.to_csv(budget_status_path, index=False)
    write_json(kpi_summary_path, kpi_summary)
    render_planning_stage_dashboard_html(
        dashboard_path,
        kpi_summary=kpi_summary,
        budget_rows=budget_status.to_dict(orient="records"),
    )

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

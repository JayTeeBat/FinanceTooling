"""Dashboard rendering for workflow outputs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.metrics import (
    build_base_currency_summary,
    build_monthly_net_eur,
    build_spend_by_category_eur,
    build_summary_by_currency,
)


def _table_html(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{header}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_dashboard_html(
    dataframe: pd.DataFrame,
    destination: Path,
    *,
    base_currency: str,
    files_scanned: int,
    files_failed: int,
    new_rows: int,
) -> Path:
    """Render an HTML dashboard with key metrics and write it to destination."""
    summary_native = build_summary_by_currency(dataframe)
    summary_base = build_base_currency_summary(dataframe)
    spend_eur = build_spend_by_category_eur(dataframe)
    monthly_eur = build_monthly_net_eur(dataframe)

    summary_rows = [
        [
            str(row["currency"]),
            f"{row['income']:.2f}",
            f"{row['expense']:.2f}",
            f"{row['net']:.2f}",
            str(int(row["transactions"])),
        ]
        for _, row in summary_native.iterrows()
    ]
    spend_rows = []
    for _, row in spend_eur.iterrows():
        spend_rows.append([str(row["category"]), f"{row['spend_eur']:.2f}"])

    monthly_rows = []
    for _, row in monthly_eur.iterrows():
        monthly_rows.append([str(row["month"]), f"{row['net_eur']:.2f}"])

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Finance Dashboard</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --surface: #ffffff;
      --text: #17212b;
      --muted: #4f5d6b;
      --border: #d7dee5;
      --accent: #0f6cbd;
    }}
    body {{
      margin: 0;
      padding: 24px;
      font-family: "Source Sans 3", "Segoe UI", sans-serif;
      color: var(--text);
      background: radial-gradient(circle at top right, #e9f2ff, var(--bg) 45%);
    }}
    .container {{ max-width: 1200px; margin: 0 auto; display: grid; gap: 20px; }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      box-shadow: 0 8px 24px rgba(23, 33, 43, 0.05);
      padding: 20px;
    }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    h2 {{ margin: 0 0 12px; color: var(--accent); font-size: 20px; }}
    p {{ margin: 0 0 8px; color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--border); text-align: left; padding: 10px 6px; }}
    th {{
      color: var(--muted);
      font-weight: 600;
      font-size: 13px;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .kpi {{
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fbfcfe;
    }}
    .kpi strong {{ display: block; font-size: 22px; }}
  </style>
</head>
<body>
  <div class="container">
    <section class="card">
      <h1>Financial Metrics Dashboard</h1>
      <p>Generated {generated_at}</p>
      <p>
        Files scanned: {files_scanned} | Files failed: {files_failed} |
        New rows: {new_rows} | Total rows: {len(dataframe)}
      </p>
    </section>
    <section class="card">
      <h2>{base_currency} Converted KPIs</h2>
      <div class="kpis">
        <div class="kpi"><span>Income</span><strong>{summary_base["income"]:.2f}</strong></div>
        <div class="kpi"><span>Expense</span><strong>{summary_base["expense"]:.2f}</strong></div>
        <div class="kpi"><span>Net</span><strong>{summary_base["net"]:.2f}</strong></div>
      </div>
    </section>
    <section class="card">
      <h2>Summary by Currency</h2>
      {_table_html(["Currency", "Income", "Expense", "Net", "Transactions"], summary_rows)}
    </section>
    <section class="card">
      <h2>Spending by Category ({base_currency})</h2>
      {_table_html(["Category", "Spend"], spend_rows)}
    </section>
    <section class="card">
      <h2>Monthly Net Trend ({base_currency})</h2>
      {_table_html(["Month", "Net"], monthly_rows)}
    </section>
  </div>
</body>
</html>
""".strip()

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination

"""Workflow orchestration for scanning, extracting, classifying, and reporting."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from finance_tooling.classify import classify_transactions
from finance_tooling.config import Settings
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.extract import extract_text_from_pdf
from finance_tooling.models import Transaction, WorkflowResult
from finance_tooling.parsers import select_parser
from finance_tooling.scanner import discover_statement_pdfs
from finance_tooling.store import upsert_transactions


def _apply_fx_and_mtime(
    transactions: list[Transaction], settings: Settings
) -> tuple[list[Transaction], list[str]]:
    enriched: list[Transaction] = []
    warnings: list[str] = []

    for tx in transactions:
        currency = tx.currency.upper()
        amount_eur: Decimal | None = None

        rate = settings.fx_rates.get(currency)
        if rate is None:
            warnings.append(
                "Missing FX rate for currency "
                f"{currency} ({tx.source_file.name}); "
                "converted metrics will skip this row"
            )
        else:
            amount_eur = tx.amount_native * rate

        mtime = datetime.fromtimestamp(tx.source_file.stat().st_mtime, tz=UTC)
        enriched.append(
            replace(
                tx,
                currency=currency,
                amount_eur=amount_eur,
                source_file_mtime=mtime,
            )
        )

    return enriched, warnings


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def run_workflow(settings: Settings) -> WorkflowResult:
    """Execute the full finance statement workflow."""
    warnings: list[str] = []
    files_failed = 0
    extracted: list[Transaction] = []

    files = discover_statement_pdfs(settings.input_path)
    for pdf_path in files:
        try:
            extracted_text = extract_text_from_pdf(pdf_path)
            parser = select_parser(pdf_path, extracted_text.first_page_text)
            output = parser.parse(pdf_path, extracted_text.full_text)
            extracted.extend(output.transactions)
            warnings.extend(output.warnings)
        except Exception as exc:
            files_failed += 1
            warnings.append(f"Failed to process {pdf_path}: {exc}")

    classified = classify_transactions(extracted)
    enriched, fx_warnings = _apply_fx_and_mtime(classified, settings)
    warnings.extend(fx_warnings)

    upsert = upsert_transactions(settings.master_parquet_path, enriched)

    settings.export_csv_path.parent.mkdir(parents=True, exist_ok=True)
    settings.export_json_path.parent.mkdir(parents=True, exist_ok=True)
    upsert.dataframe.to_csv(settings.export_csv_path, index=False)
    upsert.dataframe.to_json(settings.export_json_path, orient="records", indent=2)

    dashboard_path = render_dashboard_html(
        upsert.dataframe,
        settings.output_path,
        base_currency=settings.base_currency,
        files_scanned=len(files),
        files_failed=files_failed,
        new_rows=upsert.new_rows,
    )

    _write_json(
        settings.summary_json_path,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "files_scanned": len(files),
            "files_failed": files_failed,
            "transactions_parsed": len(enriched),
            "new_rows": upsert.new_rows,
            "total_rows": upsert.total_rows,
            "parquet_path": str(upsert.parquet_path),
            "dashboard_path": str(dashboard_path),
            "warnings": warnings,
        },
    )

    return WorkflowResult(
        dashboard_path=dashboard_path,
        parquet_path=upsert.parquet_path,
        csv_path=settings.export_csv_path,
        json_path=settings.export_json_path,
        summary_path=settings.summary_json_path,
        files_scanned=len(files),
        files_failed=files_failed,
        transactions_parsed=len(enriched),
        new_rows=upsert.new_rows,
        total_rows=upsert.total_rows,
        warnings=tuple(warnings),
    )

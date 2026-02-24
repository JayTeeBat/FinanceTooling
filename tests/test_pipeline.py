import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pandas as pd

from finance_tooling.config import Settings
from finance_tooling.extract import ExtractedPdfText
from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput, StatementParser
from finance_tooling.parsers.registry import ParserScoreItem, ParserSelection
from finance_tooling.pipeline import run_workflow
from finance_tooling.store import UpsertResult


@dataclass
class _DummyParser:
    name: str = "dummy"
    bank: str = "DummyBank"

    def match_score(self, file_path: Path, first_page_text: str) -> int:
        del file_path, first_page_text
        return 2

    def parse(self, file_path: Path, _full_text: str) -> ParserOutput:
        if "parsed" not in file_path.stem:
            return ParserOutput(transactions=[], warnings=[])

        tx = Transaction(
            booking_date=date(2024, 5, 6),
            description="Salary",
            amount_native=Decimal("100.00"),
            currency="EUR",
            source_file=file_path,
            bank="DummyBank",
            parser=self.name,
        )
        return ParserOutput(transactions=[tx], warnings=[])


def test_run_workflow_writes_completeness_report_and_summary(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    parsed_pdf = input_dir / "parsed_2024.pdf"
    missing_pdf = input_dir / "missing_2025.pdf"
    parsed_pdf.write_text("fake", encoding="utf-8")
    missing_pdf.write_text("fake", encoding="utf-8")

    settings = Settings(
        input_path=input_dir,
        output_path=input_dir / "dashboard.html",
        master_parquet_path=input_dir / "transactions_master.parquet",
        export_csv_path=input_dir / "transactions_normalized.csv",
        export_json_path=input_dir / "transactions_normalized.json",
        summary_json_path=input_dir / "run_summary.json",
        completeness_json_path=input_dir / "completeness_report.json",
        base_currency="EUR",
        fx_cache_path=input_dir / "fx.parquet",
        fx_auto_fetch=False,
    )

    monkeypatch.setattr(
        "finance_tooling.pipeline.discover_statement_pdfs", lambda _: [parsed_pdf, missing_pdf]
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.extract_text_from_pdf",
        lambda _: ExtractedPdfText(first_page_text="", full_text=""),
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.select_parser_with_diagnostics",
        lambda *_: ParserSelection(
            parser=cast(StatementParser, _DummyParser()),
            score=2,
            threshold=2,
            candidates=(
                ParserScoreItem(parser_name="dummy", score=2),
                ParserScoreItem(parser_name="generic", score=0),
            ),
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.render_dashboard_html",
        lambda *args, **kwargs: settings.output_path,
    )

    dataframe = pd.DataFrame(
        [
            {
                "transaction_id": "tx-1",
                "booking_date": "2024-05-06",
                "description": "Salary",
                "amount_native": 100.0,
                "currency": "EUR",
                "fx_rate_to_eur": 1.0,
                "fx_rate_date": "2024-05-06",
                "fx_source": "BASE",
                "amount_eur": 100.0,
                "category": "Income",
                "bank": "DummyBank",
                "account_label": None,
                "source_file": str(parsed_pdf),
                "source_file_mtime": None,
                "parser": "dummy",
                "ingested_at": "2026-02-23T00:00:00+00:00",
            }
        ]
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.upsert_transactions",
        lambda *_: UpsertResult(
            parquet_path=settings.master_parquet_path,
            dataframe=dataframe,
            new_rows=1,
            total_rows=1,
        ),
    )

    result = run_workflow(settings)

    completeness_payload = json.loads(settings.completeness_json_path.read_text(encoding="utf-8"))
    assert completeness_payload["source_pdf_count"] == 2
    assert completeness_payload["parsed_unique_source_file_count"] == 1
    assert completeness_payload["missing_source_file_count"] == 1
    assert completeness_payload["status"] == "fail"

    summary_payload = json.loads(settings.summary_json_path.read_text(encoding="utf-8"))
    assert summary_payload["completeness_report_path"] == str(settings.completeness_json_path)
    assert summary_payload["completeness_status"] == "fail"
    assert summary_payload["missing_source_file_count"] == 1
    assert summary_payload["statement_reconciliation_checkable_file_count"] == 0
    assert summary_payload["statement_reconciliation_fail_count"] == 0
    assert summary_payload["statement_reconciliation_uncheckable_file_count"] == 0
    assert summary_payload["statement_reconciliation_pass_ratio"] is None
    assert summary_payload["statement_reconciliation_median_abs_difference"] is None
    assert summary_payload["statement_reconciliation_hsbc_median_abs_difference"] is None
    assert summary_payload["parser_low_confidence_file_count"] == 2
    assert len(summary_payload["parser_selection_diagnostics"]) == 2

    assert result.completeness_path == settings.completeness_json_path
    assert result.completeness_status == "fail"
    assert result.completeness_coverage_ratio == 0.5
    assert result.missing_source_file_count == 1
    assert result.reconciliation_checkable_file_count == 0
    assert result.reconciliation_fail_count == 0
    assert result.reconciliation_uncheckable_file_count == 0
    assert result.reconciliation_pass_ratio is None

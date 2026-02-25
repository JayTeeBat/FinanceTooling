import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pandas as pd

from finance_tooling.config import Settings
from finance_tooling.extract import ExtractedPdfText
from finance_tooling.importers.hsbc_csv import HsbcCsvImportResult
from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput, StatementParser, StatementValidation
from finance_tooling.parsers.registry import ParserScoreItem, ParserSelection
from finance_tooling.pipeline import (
    _assign_hsbc_csv_transactions_to_statement_dates,
    _parse_hsbc_statement_period,
    run_workflow,
)
from finance_tooling.store import UpsertResult


@dataclass
class _DummyParser:
    name: str = "dummy"
    bank: str = "DummyBank"
    currency: str = "EUR"

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
            currency=self.currency,
            source_file=file_path,
            bank=self.bank,
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
        hsbc_csv_path=None,
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
    assert summary_payload["hsbc_period_parse_variant_match_count"] == 0
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


def test_parse_hsbc_statement_period_parses_inclusive_window() -> None:
    full_text = "Account Summary 30 March to 29 April 2017 Branch Identifier Code"

    period = _parse_hsbc_statement_period(full_text)

    assert period is not None
    assert period[0] == date(2017, 3, 30)
    assert period[1] == date(2017, 4, 29)


def test_parse_hsbc_statement_period_parses_compact_to_spacing_variant() -> None:
    full_text = "Account Summary 30 Januaryto 28 February 2017 Branch Identifier Code"

    period = _parse_hsbc_statement_period(full_text)

    assert period is not None
    assert period[0] == date(2017, 1, 30)
    assert period[1] == date(2017, 2, 28)


def test_parse_hsbc_statement_period_parses_start_year_and_compact_end_year() -> None:
    full_text = "Account Summary 30 December 2016 to 29 January2017 Branch Identifier Code"

    period = _parse_hsbc_statement_period(full_text)

    assert period is not None
    assert period[0] == date(2016, 12, 30)
    assert period[1] == date(2017, 1, 29)


def test_assign_hsbc_csv_transactions_reassigns_boundary_day() -> None:
    may_csv = Path("/tmp/HSBC Jacques NPB_40-22-30_31492861-2017-05-29.csv")
    transactions = [
        Transaction(
            booking_date=date(2017, 4, 29),
            description="Boundary day in following CSV",
            amount_native=Decimal("-1949.25"),
            currency="GBP",
            source_file=may_csv,
            bank="HSBC",
            parser="hsbc_csv",
        ),
        Transaction(
            booking_date=date(2017, 5, 1),
            description="Normal May row",
            amount_native=Decimal("-10.00"),
            currency="GBP",
            source_file=may_csv,
            bank="HSBC",
            parser="hsbc_csv",
        ),
    ]
    statement_periods = {
        "2017-04-29": (date(2017, 3, 30), date(2017, 4, 29)),
        "2017-05-29": (date(2017, 4, 30), date(2017, 5, 29)),
    }

    assigned, unassigned, metrics = _assign_hsbc_csv_transactions_to_statement_dates(
        transactions,
        statement_periods,
    )

    assert unassigned == []
    assert len(assigned["2017-04-29"]) == 1
    assert len(assigned["2017-05-29"]) == 1
    assert metrics["hsbc_period_remap_reassigned_tx_count"] == 1
    assert metrics["hsbc_period_remap_unassigned_csv_tx_count"] == 0


def test_run_workflow_prefers_hsbc_csv_for_same_statement_month(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    parsed_pdf = input_dir / "HSBC parsed 2024-05-06_Statement.pdf"
    parsed_pdf.write_text("fake", encoding="utf-8")
    hsbc_csv = input_dir / "HSBC Jacques NPB_40-22-30_31492861-2024-05-06.csv"
    hsbc_csv.write_text("Date,Payee,Amount\n", encoding="utf-8")

    settings = Settings(
        input_path=input_dir,
        output_path=input_dir / "dashboard.html",
        master_parquet_path=input_dir / "transactions_master.parquet",
        export_csv_path=input_dir / "transactions_normalized.csv",
        export_json_path=input_dir / "transactions_normalized.json",
        summary_json_path=input_dir / "run_summary.json",
        completeness_json_path=input_dir / "completeness_report.json",
        base_currency="GBP",
        fx_cache_path=input_dir / "fx.parquet",
        fx_auto_fetch=False,
        hsbc_csv_path=hsbc_csv,
    )

    monkeypatch.setattr("finance_tooling.pipeline.discover_statement_pdfs", lambda _: [parsed_pdf])
    monkeypatch.setattr(
        "finance_tooling.pipeline.extract_text_from_pdf",
        lambda _: ExtractedPdfText(first_page_text="", full_text=""),
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.select_parser_with_diagnostics",
        lambda *_: ParserSelection(
            parser=cast(StatementParser, _DummyParser(name="hsbc", bank="HSBC", currency="GBP")),
            score=3,
            threshold=2,
            candidates=(
                ParserScoreItem(parser_name="hsbc", score=3),
                ParserScoreItem(parser_name="generic", score=0),
            ),
        ),
    )
    monkeypatch.setattr("finance_tooling.pipeline.discover_csv_files", lambda _: [hsbc_csv])
    monkeypatch.setattr(
        "finance_tooling.pipeline.load_hsbc_csv_transactions",
        lambda _: HsbcCsvImportResult(
            transactions=[
                Transaction(
                    booking_date=date(2024, 5, 6),
                    description="Card payment groceries",
                    amount_native=Decimal("100.00"),
                    currency="GBP",
                    source_file=hsbc_csv,
                    bank="HSBC",
                    parser="hsbc_csv",
                    account_label=None,
                )
            ],
            warnings=[],
            files_scanned=1,
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.render_dashboard_html",
        lambda *args, **kwargs: settings.output_path,
    )

    captured: dict[str, object] = {}

    def _capture_upsert(_path: Path, transactions: list[Transaction]) -> UpsertResult:
        captured["transactions"] = transactions
        dataframe = pd.DataFrame(
            [
                {
                    "transaction_id": "tx-1",
                    "booking_date": tx.booking_date.isoformat(),
                    "description": tx.description,
                    "amount_native": float(tx.amount_native),
                    "currency": tx.currency,
                    "fx_rate_to_eur": 1.0,
                    "fx_rate_date": tx.booking_date.isoformat(),
                    "fx_source": "BASE",
                    "amount_eur": float(tx.amount_native),
                    "category": tx.category,
                    "bank": tx.bank,
                    "account_label": tx.account_label,
                    "source_file": str(tx.source_file),
                    "source_file_mtime": None,
                    "parser": tx.parser,
                    "ingested_at": "2026-02-23T00:00:00+00:00",
                }
                for tx in transactions
            ]
        )
        return UpsertResult(
            parquet_path=settings.master_parquet_path,
            dataframe=dataframe,
            new_rows=len(transactions),
            total_rows=len(transactions),
        )

    monkeypatch.setattr("finance_tooling.pipeline.upsert_transactions", _capture_upsert)

    run_workflow(settings)

    kept_transactions = cast(list[Transaction], captured["transactions"])
    assert len(kept_transactions) == 1
    assert kept_transactions[0].parser == "hsbc_csv"
    assert kept_transactions[0].source_file == parsed_pdf

    summary_payload = json.loads(settings.summary_json_path.read_text(encoding="utf-8"))
    assert summary_payload["hsbc_csv_files_scanned"] == 1
    assert summary_payload["hsbc_csv_statement_replaced_count"] == 1
    assert summary_payload["hsbc_pdf_fallback_statement_count"] == 0
    assert summary_payload["hsbc_csv_only_statement_count"] == 0
    assert summary_payload["hsbc_selection_policy"] == "adaptive_reconciliation"
    assert summary_payload["hsbc_adaptive_source_switch_count"] == 0
    assert summary_payload["hsbc_selected_csv_month_count"] == 1
    assert summary_payload["hsbc_selected_pdf_month_count"] == 0


def test_run_workflow_keeps_pdf_fallback_and_csv_only_statements(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    parsed_pdf = input_dir / "HSBC parsed 2024-05-06_Statement.pdf"
    parsed_pdf.write_text("fake", encoding="utf-8")
    hsbc_csv = input_dir / "HSBC Jacques NPB_40-22-30_31492861-2024-06-06.csv"
    hsbc_csv.write_text("Date,Payee,Amount\n", encoding="utf-8")

    settings = Settings(
        input_path=input_dir,
        output_path=input_dir / "dashboard.html",
        master_parquet_path=input_dir / "transactions_master.parquet",
        export_csv_path=input_dir / "transactions_normalized.csv",
        export_json_path=input_dir / "transactions_normalized.json",
        summary_json_path=input_dir / "run_summary.json",
        completeness_json_path=input_dir / "completeness_report.json",
        base_currency="GBP",
        fx_cache_path=input_dir / "fx.parquet",
        fx_auto_fetch=False,
        hsbc_csv_path=hsbc_csv,
    )

    monkeypatch.setattr("finance_tooling.pipeline.discover_statement_pdfs", lambda _: [parsed_pdf])
    monkeypatch.setattr(
        "finance_tooling.pipeline.extract_text_from_pdf",
        lambda _: ExtractedPdfText(first_page_text="", full_text=""),
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.select_parser_with_diagnostics",
        lambda *_: ParserSelection(
            parser=cast(StatementParser, _DummyParser(name="hsbc", bank="HSBC", currency="GBP")),
            score=3,
            threshold=2,
            candidates=(
                ParserScoreItem(parser_name="hsbc", score=3),
                ParserScoreItem(parser_name="generic", score=0),
            ),
        ),
    )
    monkeypatch.setattr("finance_tooling.pipeline.discover_csv_files", lambda _: [hsbc_csv])
    monkeypatch.setattr(
        "finance_tooling.pipeline.load_hsbc_csv_transactions",
        lambda _: HsbcCsvImportResult(
            transactions=[
                Transaction(
                    booking_date=date(2024, 5, 6),
                    description="Salary April payroll",
                    amount_native=Decimal("100.00"),
                    currency="GBP",
                    source_file=hsbc_csv,
                    bank="HSBC",
                    parser="hsbc_csv",
                    account_label=None,
                )
            ],
            warnings=[],
            files_scanned=1,
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.render_dashboard_html",
        lambda *args, **kwargs: settings.output_path,
    )

    captured: dict[str, object] = {}

    def _capture_upsert(_path: Path, transactions: list[Transaction]) -> UpsertResult:
        captured["transactions"] = transactions
        dataframe = pd.DataFrame(
            [
                {
                    "transaction_id": "tx-1",
                    "booking_date": tx.booking_date.isoformat(),
                    "description": tx.description,
                    "amount_native": float(tx.amount_native),
                    "currency": tx.currency,
                    "fx_rate_to_eur": 1.0,
                    "fx_rate_date": tx.booking_date.isoformat(),
                    "fx_source": "BASE",
                    "amount_eur": float(tx.amount_native),
                    "category": tx.category,
                    "bank": tx.bank,
                    "account_label": tx.account_label,
                    "source_file": str(tx.source_file),
                    "source_file_mtime": None,
                    "parser": tx.parser,
                    "ingested_at": "2026-02-23T00:00:00+00:00",
                }
                for tx in transactions
            ]
        )
        return UpsertResult(
            parquet_path=settings.master_parquet_path,
            dataframe=dataframe,
            new_rows=len(transactions),
            total_rows=len(transactions),
        )

    monkeypatch.setattr("finance_tooling.pipeline.upsert_transactions", _capture_upsert)

    run_workflow(settings)

    kept_transactions = cast(list[Transaction], captured["transactions"])
    assert len(kept_transactions) == 2
    parsers = {transaction.parser for transaction in kept_transactions}
    assert parsers == {"hsbc", "hsbc_csv"}
    csv_transaction = next(
        transaction for transaction in kept_transactions if transaction.parser == "hsbc_csv"
    )
    assert csv_transaction.source_file == hsbc_csv

    summary_payload = json.loads(settings.summary_json_path.read_text(encoding="utf-8"))
    assert summary_payload["hsbc_csv_statement_replaced_count"] == 0
    assert summary_payload["hsbc_pdf_fallback_statement_count"] == 1
    assert summary_payload["hsbc_csv_only_statement_count"] == 1


def test_run_workflow_uses_pdf_balances_to_adaptively_select_source(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    parsed_pdf = input_dir / "HSBC parsed 2024-05-06_Statement.pdf"
    parsed_pdf.write_text("fake", encoding="utf-8")
    hsbc_csv = input_dir / "HSBC Jacques NPB_40-22-30_31492861-2024-05-06.csv"
    hsbc_csv.write_text("Date,Payee,Amount\n", encoding="utf-8")

    settings = Settings(
        input_path=input_dir,
        output_path=input_dir / "dashboard.html",
        master_parquet_path=input_dir / "transactions_master.parquet",
        export_csv_path=input_dir / "transactions_normalized.csv",
        export_json_path=input_dir / "transactions_normalized.json",
        summary_json_path=input_dir / "run_summary.json",
        completeness_json_path=input_dir / "completeness_report.json",
        base_currency="GBP",
        fx_cache_path=input_dir / "fx.parquet",
        fx_auto_fetch=False,
        hsbc_csv_path=hsbc_csv,
    )

    class _ValidatingHsbcParser:
        name = "hsbc"
        bank = "HSBC"

        def match_score(self, file_path: Path, first_page_text: str) -> int:
            del file_path, first_page_text
            return 3

        def parse(self, file_path: Path, _full_text: str) -> ParserOutput:
            tx = Transaction(
                booking_date=date(2024, 5, 6),
                description="Salary",
                amount_native=Decimal("40.00"),
                currency="GBP",
                source_file=file_path,
                bank="HSBC",
                parser="hsbc",
            )
            validation = StatementValidation(
                source_file=file_path,
                bank="HSBC",
                parser="hsbc",
                statement_type="statement",
                opening_balance=Decimal("100.00"),
                closing_balance=Decimal("130.00"),
                transaction_sum=Decimal("40.00"),
                expected_closing_balance=Decimal("140.00"),
                difference=Decimal("10.00"),
                status="fail",
                reason="balance_mismatch",
                severity="warning",
            )
            return ParserOutput(transactions=[tx], warnings=[], validation=validation)

    monkeypatch.setattr("finance_tooling.pipeline.discover_statement_pdfs", lambda _: [parsed_pdf])
    monkeypatch.setattr(
        "finance_tooling.pipeline.extract_text_from_pdf",
        lambda _: ExtractedPdfText(first_page_text="", full_text=""),
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.select_parser_with_diagnostics",
        lambda *_: ParserSelection(
            parser=cast(StatementParser, _ValidatingHsbcParser()),
            score=3,
            threshold=2,
            candidates=(
                ParserScoreItem(parser_name="hsbc", score=3),
                ParserScoreItem(parser_name="generic", score=0),
            ),
        ),
    )
    monkeypatch.setattr("finance_tooling.pipeline.discover_csv_files", lambda _: [hsbc_csv])
    monkeypatch.setattr(
        "finance_tooling.pipeline.load_hsbc_csv_transactions",
        lambda _: HsbcCsvImportResult(
            transactions=[
                Transaction(
                    booking_date=date(2024, 5, 6),
                    description="Salary from CSV",
                    amount_native=Decimal("50.00"),
                    currency="GBP",
                    source_file=hsbc_csv,
                    bank="HSBC",
                    parser="hsbc_csv",
                    account_label=None,
                )
            ],
            warnings=[],
            files_scanned=1,
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.pipeline.render_dashboard_html",
        lambda *args, **kwargs: settings.output_path,
    )

    def _capture_upsert(_path: Path, transactions: list[Transaction]) -> UpsertResult:
        dataframe = pd.DataFrame(
            [
                {
                    "transaction_id": "tx-1",
                    "booking_date": tx.booking_date.isoformat(),
                    "description": tx.description,
                    "amount_native": float(tx.amount_native),
                    "currency": tx.currency,
                    "fx_rate_to_eur": 1.0,
                    "fx_rate_date": tx.booking_date.isoformat(),
                    "fx_source": "BASE",
                    "amount_eur": float(tx.amount_native),
                    "category": tx.category,
                    "bank": tx.bank,
                    "account_label": tx.account_label,
                    "source_file": str(tx.source_file),
                    "source_file_mtime": None,
                    "parser": tx.parser,
                    "ingested_at": "2026-02-23T00:00:00+00:00",
                }
                for tx in transactions
            ]
        )
        return UpsertResult(
            parquet_path=settings.master_parquet_path,
            dataframe=dataframe,
            new_rows=len(transactions),
            total_rows=len(transactions),
        )

    monkeypatch.setattr("finance_tooling.pipeline.upsert_transactions", _capture_upsert)

    run_workflow(settings)

    summary_payload = json.loads(settings.summary_json_path.read_text(encoding="utf-8"))
    assert summary_payload["hsbc_pdf_balance_validated_count"] == 1
    assert summary_payload["hsbc_pdf_balance_validation_fail_count"] == 1
    assert summary_payload["statement_reconciliation_fail_count"] == 1
    assert summary_payload["hsbc_adaptive_source_switch_count"] == 1
    assert summary_payload["hsbc_selected_csv_month_count"] == 0
    assert summary_payload["hsbc_selected_pdf_month_count"] == 1
    diagnostics = summary_payload["hsbc_selection_diagnostics"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["selected_source"] == "hsbc"
    assert diagnostics[0]["pdf_abs_difference"] < diagnostics[0]["csv_abs_difference"]
    assert any(
        "HSBC hsbc reconciliation mismatch" in warning for warning in summary_payload["warnings"]
    )

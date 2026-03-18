import json
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pandas as pd

from finance_tooling.classify import ClassificationDiagnostics
from finance_tooling.config import Settings
from finance_tooling.extract import ExtractedPdfText
from finance_tooling.models import Transaction, WorkflowResult
from finance_tooling.parsers.base import ParserOutput, StatementParser, StatementValidation
from finance_tooling.parsers.registry import ParserScoreItem, ParserSelection
from finance_tooling.store import UpsertResult, compute_transaction_id, upsert_transactions
from finance_tooling.workflow.ingest_stage import (
    parse_hsbc_statement_period_compat as _parse_hsbc_statement_period,
)
from finance_tooling.workflow.ingest_stage import (
    run_ingest,
)
from finance_tooling.workflow.staging import write_staged_transactions
from finance_tooling.workflow.transform_stage import run_transform
from finance_tooling.workflow.types import EnrichmentResult
from finance_tooling.workflow.update_stage import run_update, run_workflow


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


def _settings(input_dir: Path, *, base_currency: str = "EUR") -> Settings:
    return Settings(
        input_path=input_dir,
        output_path=input_dir / "dashboard.html",
        master_parquet_path=input_dir / "transactions_master.parquet",
        export_csv_path=input_dir / "transactions_normalized.csv",
        export_json_path=input_dir / "transactions_normalized.json",
        staged_transactions_path=input_dir / "staged_transactions.parquet",
        summary_json_path=input_dir / "run_summary.json",
        completeness_json_path=input_dir / "completeness_report.json",
        base_currency=base_currency,
        fx_cache_path=input_dir / "fx.parquet",
        fx_auto_fetch=False,
        ingest_workers=1,
        ingest_text_cache_enabled=False,
        ingest_text_cache_path=input_dir / "ingest_text_cache.parquet",
        category_rules_path=input_dir / "category_rules.json",
        project_rules_path=input_dir / "project_rules.yaml",
        budget_targets_path=input_dir / "budget_targets.yaml",
        project_overrides_path=Path("config/project_overrides.yaml").resolve(),
        transaction_overrides_path=Path("config/transaction_overrides.yaml").resolve(),
        review_state_path=input_dir / "review_state.parquet",
        review_export_dark_safe=True,
    )


def test_run_workflow_writes_completeness_report_and_summary(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    parsed_pdf = input_dir / "parsed_2024.pdf"
    missing_pdf = input_dir / "missing_2025.pdf"
    parsed_pdf.write_text("fake", encoding="utf-8")
    missing_pdf.write_text("fake", encoding="utf-8")

    settings = _settings(input_dir)

    monkeypatch.setattr(
        "finance_tooling.workflow.ingest_stage.discover_statement_pdfs",
        lambda _: [parsed_pdf, missing_pdf],
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest_stage.extract_text_from_pdf",
        lambda _: ExtractedPdfText(first_page_text="", full_text=""),
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest_stage.select_parser_with_diagnostics",
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
        "finance_tooling.workflow.transform_stage.render_dashboard_html",
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
                "reviewed": False,
                "ingested_at": "2026-02-23T00:00:00+00:00",
            }
        ]
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.upsert_transactions",
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
    assert summary_payload["hsbc_boundary_table_start_count"] == 0
    assert summary_payload["hsbc_boundary_table_end_count"] == 0
    assert summary_payload["hsbc_boundary_rows_seen_in_table"] == 0
    assert summary_payload["hsbc_boundary_rows_rejected_outside_table"] == 0
    assert summary_payload["hsbc_boundary_rows_rejected_after_table"] == 0
    assert summary_payload["hsbc_boundary_transition_anomaly_count"] == 0
    assert summary_payload["hsbc_boundary_diagnostics"] == []
    assert summary_payload["hsbc_sign_from_running_balance_count"] == 0
    assert summary_payload["hsbc_sign_from_column_position_count"] == 0
    assert summary_payload["hsbc_sign_from_token_marker_count"] == 0
    assert summary_payload["hsbc_sign_from_description_marker_count"] == 0
    assert summary_payload["hsbc_sign_from_fallback_hint_count"] == 0
    assert summary_payload["hsbc_sign_default_debit_count"] == 0
    assert summary_payload["hsbc_sign_conflict_running_vs_marker_count"] == 0
    assert summary_payload["hsbc_sign_unresolved_ambiguous_count"] == 0
    assert summary_payload["hsbc_sign_diagnostics"] == []
    assert summary_payload["parser_low_confidence_file_count"] == 2
    assert len(summary_payload["parser_selection_diagnostics"]) == 2
    assert summary_payload["hsbc_selection_policy"] == "pdf_only"
    assert summary_payload["hsbc_csv_files_scanned"] == 0
    assert summary_payload["hsbc_csv_statement_replaced_count"] == 0
    assert summary_payload["hsbc_selected_csv_month_count"] == 0
    assert "ingest_parser_duration_seconds_by_parser" in summary_payload
    assert "ingest_duration_seconds_by_bank" in summary_payload
    assert summary_payload["ingest_text_cache_enabled"] is False
    assert summary_payload["ingest_text_cache_hits"] == 0
    assert summary_payload["ingest_text_cache_misses"] == 0
    assert summary_payload["ingest_text_cache_write_count"] == 0
    assert summary_payload["categorized_count"] == 1
    assert summary_payload["uncategorized_count"] == 0
    assert summary_payload["uncategorized_ratio"] == 0.0
    assert summary_payload["categorized_amount_eur_abs"] == 100.0
    assert summary_payload["uncategorized_amount_eur_abs"] == 0.0
    assert summary_payload["total_amount_eur_abs"] == 100.0
    assert summary_payload["categorized_amount_eur_abs_ratio"] == 1.0
    assert summary_payload["uncategorized_amount_eur_abs_ratio"] == 0.0
    assert summary_payload["reviewed_count"] == 0
    assert summary_payload["reviewed_ratio"] == 0.0
    assert summary_payload["category_source_counts"]["rule"] == 1
    assert summary_payload["project_overrides_path"] == str(settings.project_overrides_path)
    assert summary_payload["transaction_overrides_path"] == str(settings.transaction_overrides_path)
    assert summary_payload["review_state_path"] == str(settings.review_state_path)

    assert result.completeness_path == settings.completeness_json_path
    assert result.completeness_status == "fail"
    assert result.completeness_coverage_ratio == 0.5
    assert result.missing_source_file_count == 1
    assert result.reconciliation_checkable_file_count == 0
    assert result.reconciliation_fail_count == 0
    assert result.reconciliation_uncheckable_file_count == 0
    assert result.reconciliation_pass_ratio is None
    assert result.categorized_count == 1
    assert result.uncategorized_count == 0
    assert result.categorized_amount_eur_abs == 100.0
    assert result.uncategorized_amount_eur_abs == 0.0
    assert result.categorized_count_delta is None
    assert result.uncategorized_count_delta is None
    assert result.categorized_amount_eur_abs_delta is None
    assert result.uncategorized_amount_eur_abs_delta is None


def test_run_transform_computes_delta_from_previous_summary(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    previous_summary = {
        "categorized_count": 4,
        "uncategorized_count": 6,
        "categorized_amount_eur_abs": 40.0,
        "uncategorized_amount_eur_abs": 60.0,
    }
    settings.summary_json_path.write_text(json.dumps(previous_summary), encoding="utf-8")
    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.read_staged_transactions",
        lambda _: [],
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.enrich_transactions",
        lambda *_args, **_kwargs: type(
            "EnrichmentStub",
            (),
            {
                "transactions": [],
                "warnings": [],
                "classification_diagnostics": None,
                "manual_category_carry_forward_applied_count": 0,
                "manual_category_carry_forward_ambiguous_skipped_count": 0,
                "manual_category_carry_forward_unmatched_count": 0,
            },
        )(),
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.apply_review_state",
        lambda transactions, _path: transactions,
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.persist_and_report",
        lambda **_kwargs: (
            WorkflowResult(
                dashboard_path=settings.output_path,
                parquet_path=settings.master_parquet_path,
                csv_path=settings.export_csv_path,
                json_path=settings.export_json_path,
                summary_path=settings.summary_json_path,
                completeness_path=settings.completeness_json_path,
                files_scanned=0,
                files_failed=0,
                transactions_parsed=10,
                new_rows=0,
                total_rows=10,
                completeness_status="pass",
                completeness_coverage_ratio=1.0,
                missing_source_file_count=0,
                reconciliation_checkable_file_count=0,
                reconciliation_fail_count=0,
                reconciliation_uncheckable_file_count=0,
                reconciliation_pass_ratio=None,
                categorized_count=7,
                uncategorized_count=3,
                categorized_amount_eur_abs=70.0,
                uncategorized_amount_eur_abs=30.0,
                categorized_amount_eur_abs_ratio=0.7,
                uncategorized_amount_eur_abs_ratio=0.3,
                warnings=(),
            ),
            {
                "categorized_count": 7,
                "uncategorized_count": 3,
                "categorized_amount_eur_abs": 70.0,
                "uncategorized_amount_eur_abs": 30.0,
            },
        ),
    )

    result = run_transform(settings)

    assert result.categorized_count_delta == 3
    assert result.uncategorized_count_delta == -3
    assert result.categorized_amount_eur_abs_delta == 30.0
    assert result.uncategorized_amount_eur_abs_delta == -30.0


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


def test_run_workflow_uses_hsbc_pdf_balances_for_validation(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    parsed_pdf = input_dir / "HSBC parsed 2024-05-06_Statement.pdf"
    parsed_pdf.write_text("fake", encoding="utf-8")
    settings = _settings(input_dir, base_currency="GBP")

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

    monkeypatch.setattr(
        "finance_tooling.workflow.ingest_stage.discover_statement_pdfs",
        lambda _: [parsed_pdf],
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest_stage.extract_text_from_pdf",
        lambda _: ExtractedPdfText(first_page_text="", full_text=""),
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest_stage.select_parser_with_diagnostics",
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
    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.render_dashboard_html",
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

    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.upsert_transactions", _capture_upsert
    )

    run_workflow(settings)

    summary_payload = json.loads(settings.summary_json_path.read_text(encoding="utf-8"))
    assert summary_payload["hsbc_pdf_balance_validated_count"] == 1
    assert summary_payload["hsbc_pdf_balance_validation_fail_count"] == 1
    assert summary_payload["statement_reconciliation_fail_count"] == 1
    assert summary_payload["hsbc_adaptive_source_switch_count"] == 0
    assert summary_payload["hsbc_selected_csv_month_count"] == 0
    assert summary_payload["hsbc_selected_pdf_month_count"] == 1
    assert summary_payload["hsbc_selection_policy"] == "pdf_only"
    diagnostics = summary_payload["hsbc_selection_diagnostics"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["selected_source"] == "hsbc"
    assert diagnostics[0]["csv_transaction_count"] == 0
    assert diagnostics[0]["csv_abs_difference"] is None
    assert diagnostics[0]["pdf_abs_difference"] == 10.0
    assert any(
        "HSBC hsbc reconciliation mismatch" in warning for warning in summary_payload["warnings"]
    )


def test_run_ingest_writes_staged_artifacts_only(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    parsed_pdf = input_dir / "parsed_2024.pdf"
    parsed_pdf.write_text("fake", encoding="utf-8")

    settings = _settings(input_dir)

    monkeypatch.setattr(
        "finance_tooling.workflow.ingest_stage.discover_statement_pdfs",
        lambda _: [parsed_pdf],
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest_stage.extract_text_from_pdf",
        lambda _: ExtractedPdfText(first_page_text="", full_text=""),
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest_stage.select_parser_with_diagnostics",
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

    result = run_ingest(settings)

    assert result.files_scanned == 1
    assert result.transactions_parsed == 1
    assert result.staged_path == settings.staged_transactions_path
    assert settings.staged_transactions_path.exists()
    assert result.ingest_summary_path.exists()
    ingest_summary = json.loads(result.ingest_summary_path.read_text(encoding="utf-8"))
    assert ingest_summary["transactions_parsed"] == 1
    assert ingest_summary["staged_transactions_path"] == str(settings.staged_transactions_path)
    assert not settings.master_parquet_path.exists()
    assert not settings.export_csv_path.exists()
    assert not settings.export_json_path.exists()
    assert not settings.summary_json_path.exists()
    assert not settings.completeness_json_path.exists()


def test_run_transform_reads_staged_and_writes_final_artifacts(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    source_file = input_dir / "statement_2024.pdf"
    source_file.write_text("fake", encoding="utf-8")
    settings = _settings(input_dir)

    staged_transaction = Transaction(
        booking_date=date(2024, 5, 6),
        description="Salary",
        amount_native=Decimal("100.00"),
        currency="EUR",
        source_file=source_file,
        bank="DummyBank",
        parser="dummy",
    )
    write_staged_transactions(settings.staged_transactions_path, [staged_transaction])

    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.render_dashboard_html",
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
                    "subcategory": tx.subcategory,
                    "category_confidence": tx.category_confidence,
                    "category_source": tx.category_source,
                    "category_rule_id": tx.category_rule_id,
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

    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.upsert_transactions", _capture_upsert
    )

    result = run_transform(settings)

    assert result.transactions_parsed == 1
    assert settings.summary_json_path.exists()
    assert settings.completeness_json_path.exists()
    assert settings.export_csv_path.exists()
    assert settings.export_json_path.exists()


def test_run_transform_overwrites_existing_row_with_new_enrichment(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    source_file = input_dir / "statement_2024.pdf"
    source_file.write_text("fake", encoding="utf-8")
    base_settings = _settings(input_dir)
    settings = replace(
        base_settings,
        project_overrides_path=(tmp_path / "project_overrides.yaml"),
        transaction_overrides_path=(tmp_path / "transaction_overrides.yaml"),
    )
    settings.project_overrides_path.write_text(
        "version: 1\nrules: []\noverrides: []\n",
        encoding="utf-8",
    )

    staged_transaction = Transaction(
        booking_date=date(2024, 5, 6),
        description="Salary",
        amount_native=Decimal("100.00"),
        currency="EUR",
        source_file=source_file,
        bank="DummyBank",
        parser="dummy",
        category_source="uncategorized",
    )
    tx_id = compute_transaction_id(staged_transaction)
    settings.transaction_overrides_path.write_text(
        (
            "version: 1\n"
            "overrides:\n"
            f"- transaction_id: {tx_id}\n"
            "  category: Work\n"
            "  subcategory: Salary\n"
        ),
        encoding="utf-8",
    )

    upsert_transactions(settings.master_parquet_path, [staged_transaction])
    write_staged_transactions(settings.staged_transactions_path, [staged_transaction])

    run_transform(settings)

    dataframe = pd.read_csv(settings.export_csv_path)
    row = dataframe.loc[dataframe["transaction_id"] == tx_id].iloc[0]
    assert row["category"] == "Work"
    assert row["subcategory"] == "Salary"
    assert row["category_source"] == "transaction_override"


def test_run_transform_creates_category_rules_backup_and_prunes_to_last_ten(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    settings = replace(_settings(input_dir), category_rules_path=input_dir / "category_rules.yaml")
    settings.category_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")
    backup_dir = settings.category_rules_path.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for index in range(10):
        path = backup_dir / f"category_rules.yaml.20260310-00000{index}.bak"
        path.write_text(f"backup-{index}", encoding="utf-8")

    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.read_staged_transactions",
        lambda _: [],
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.enrich_transactions",
        lambda *_args, **_kwargs: EnrichmentResult(
            transactions=[],
            warnings=[],
            classification_diagnostics=ClassificationDiagnostics(
                categorized_count=0,
                uncategorized_count=0,
                uncategorized_ratio=0.0,
                category_source_counts={},
                top_uncategorized_descriptions=[],
                top_rules_by_hits=[],
            ),
            manual_category_carry_forward_applied_count=0,
            manual_category_carry_forward_ambiguous_skipped_count=0,
            manual_category_carry_forward_unmatched_count=0,
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.apply_review_state",
        lambda transactions, _review_state_path: transactions,
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.transform_stage.persist_and_report",
        lambda **_kwargs: (
            WorkflowResult(
                dashboard_path=settings.output_path,
                parquet_path=settings.master_parquet_path,
                csv_path=settings.export_csv_path,
                json_path=settings.export_json_path,
                summary_path=settings.summary_json_path,
                completeness_path=settings.completeness_json_path,
                files_scanned=0,
                files_failed=0,
                transactions_parsed=0,
                new_rows=0,
                total_rows=0,
                completeness_status="pass",
                completeness_coverage_ratio=1.0,
                missing_source_file_count=0,
                reconciliation_checkable_file_count=0,
                reconciliation_fail_count=0,
                reconciliation_uncheckable_file_count=0,
                reconciliation_pass_ratio=None,
                categorized_count=0,
                uncategorized_count=0,
                categorized_amount_eur_abs=0.0,
                uncategorized_amount_eur_abs=0.0,
                categorized_amount_eur_abs_ratio=0.0,
                uncategorized_amount_eur_abs_ratio=0.0,
                warnings=(),
            ),
            {
                "categorized_count": 0,
                "uncategorized_count": 0,
                "categorized_amount_eur_abs": 0.0,
                "uncategorized_amount_eur_abs": 0.0,
            },
        ),
    )

    run_transform(settings)

    backups = sorted(backup_dir.glob("category_rules.yaml*.bak"))
    assert len(backups) == 10
    assert not (backup_dir / "category_rules.yaml.20260310-000000.bak").exists()


def test_run_update_rejects_conflicting_stage_flags(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    settings = _settings(input_dir)

    try:
        run_update(settings, ingest_only=True, transform_only=True)
    except ValueError as exc:
        assert "mutually exclusive" in str(exc)
    else:
        raise AssertionError("Expected ValueError when both stage flags are set.")

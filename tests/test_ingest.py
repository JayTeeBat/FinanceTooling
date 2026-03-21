from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

from finance_tooling.config import Settings
from finance_tooling.extract import ExtractedPdfText, extract_text_from_pdf
from finance_tooling.models import Transaction
from finance_tooling.parsers.base import ParserOutput, StatementParser
from finance_tooling.parsers.registry import (
    ParserScoreItem,
    ParserSelection,
    select_parser_with_diagnostics,
)
from finance_tooling.workflow import ingest as ingest_module
from finance_tooling.workflow.ingest import ingest_statements


@dataclass
class _DummyParser:
    name: str = "dummy"
    bank: str = "DummyBank"

    def match_score(self, file_path: Path, first_page_text: str) -> int:
        del file_path, first_page_text
        return 3

    def parse(self, file_path: Path, full_text: str) -> ParserOutput:
        del full_text
        tx = Transaction(
            booking_date=date(2025, 1, 1),
            description="Test",
            amount_native=Decimal("10.00"),
            currency="EUR",
            source_file=file_path,
            bank="DummyBank",
            parser="dummy",
        )
        return ParserOutput(transactions=[tx], warnings=[])


def _settings(tmp_path: Path, *, ingest_workers: int) -> Settings:
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        input_path=input_dir,
        output_path=tmp_path / "dashboard.html",
        master_parquet_path=tmp_path / "transactions_master.parquet",
        export_csv_path=tmp_path / "transactions_normalized.csv",
        export_json_path=tmp_path / "transactions_normalized.json",
        staged_transactions_path=tmp_path / "staged_transactions.parquet",
        summary_json_path=tmp_path / "run_summary.json",
        completeness_json_path=tmp_path / "completeness_report.json",
        base_currency="EUR",
        fx_cache_path=tmp_path / "fx_rates_history.parquet",
        fx_auto_fetch=False,
        ingest_workers=ingest_workers,
        ingest_text_cache_enabled=False,
        ingest_text_cache_path=tmp_path / "ingest_text_cache.parquet",
        category_rules_path=tmp_path / "category_rules.yaml",
        project_rules_path=tmp_path / "project_rules.yaml",
        budget_targets_path=tmp_path / "budget_targets.yaml",
        project_overrides_path=Path("config/project_overrides.yaml").resolve(),
        transaction_overrides_path=Path("config/transaction_overrides.yaml").resolve(),
        review_state_path=tmp_path / "review_state.parquet",
        review_export_dark_safe=True,
    )


def _selection_for_dummy(_path: Path, _first_page_text: str) -> ParserSelection:
    return ParserSelection(
        parser=cast(StatementParser, _DummyParser()),
        score=3,
        threshold=2,
        candidates=(
            ParserScoreItem(parser_name="dummy", score=3),
            ParserScoreItem(parser_name="generic", score=0),
        ),
    )


def test_ingest_statements_parallel_prepare_path_collects_parser_timings(
    monkeypatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, ingest_workers=2)
    pdf_path = settings.input_path / "statement_2025-01-01.pdf"
    pdf_path.write_text("fake", encoding="utf-8")

    prepared = ingest_module._PreparedStatement(
        index=0,
        source_file=pdf_path,
        source_document_id="doc-123",
        first_page_text="dummy first page",
        full_text="dummy text",
        selected_parser_name="dummy",
        selected_parser=cast(StatementParser, _DummyParser()),
        selected_score=3,
        threshold=2,
        top_candidates=[{"parser": "dummy", "score": 3}],
        is_low_confidence=False,
        is_ambiguous_tie=False,
        hsbc_statement_date=None,
        hsbc_statement_period=None,
        hsbc_spacing_variant=False,
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest._prepare_statements_parallel",
        lambda files, source_document_ids, max_workers: [prepared],
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest._PARSERS_BY_NAME",
        {"dummy": cast(StatementParser, _DummyParser())},
    )

    result = ingest_statements(
        settings,
        discover_statement_pdfs=lambda _: [pdf_path],
        extract_text_from_pdf=extract_text_from_pdf,
        select_parser_with_diagnostics=select_parser_with_diagnostics,
    )

    assert result.files_failed == 0
    assert len(result.transactions) == 1
    assert result.parser_duration_seconds_by_parser["dummy"] >= 0.0
    assert result.duration_seconds_by_bank["DummyBank"] >= 0.0


def test_ingest_statements_uses_sequential_prepare_for_custom_callables(
    monkeypatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, ingest_workers=4)
    pdf_path = settings.input_path / "statement_2025-01-01.pdf"
    pdf_path.write_text("fake", encoding="utf-8")

    calls = {"sequential": 0}

    def _sequential(*args, **kwargs):
        del args, kwargs
        calls["sequential"] += 1
        return []

    def _parallel(*args, **kwargs):
        del args, kwargs
        raise AssertionError("parallel path should not be used with custom callables")

    monkeypatch.setattr(
        "finance_tooling.workflow.ingest._prepare_statements_sequential",
        _sequential,
    )
    monkeypatch.setattr("finance_tooling.workflow.ingest._prepare_statements_parallel", _parallel)

    result = ingest_statements(
        settings,
        discover_statement_pdfs=lambda _: [pdf_path],
        extract_text_from_pdf=lambda _: ExtractedPdfText(first_page_text="", full_text=""),
        select_parser_with_diagnostics=lambda *_: ParserSelection(
            parser=cast(StatementParser, _DummyParser()),
            score=3,
            threshold=2,
            candidates=(
                ParserScoreItem(parser_name="dummy", score=3),
                ParserScoreItem(parser_name="generic", score=0),
            ),
        ),
    )

    assert calls["sequential"] == 1
    assert len(result.source_files) == 1


def test_ingest_statements_uses_text_cache_hit_without_extraction(
    monkeypatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, ingest_workers=1)
    settings = replace(settings, ingest_text_cache_enabled=True)
    pdf_path = settings.input_path / "statement_2025-01-01.pdf"
    pdf_path.write_text("fake", encoding="utf-8")

    key = ingest_module.build_cache_key(pdf_path)
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest.load_text_cache",
        lambda _: ({key: ExtractedPdfText(first_page_text="cached", full_text="cached full")}, []),
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.ingest.upsert_text_cache",
        lambda *_: (0, []),
    )

    result = ingest_statements(
        settings,
        discover_statement_pdfs=lambda _: [pdf_path],
        extract_text_from_pdf=lambda _: (_ for _ in ()).throw(
            AssertionError("extract should not run")
        ),
        select_parser_with_diagnostics=_selection_for_dummy,
    )

    assert result.text_cache_enabled is True
    assert result.text_cache_hits == 1
    assert result.text_cache_misses == 0
    assert result.text_cache_write_count == 0


def test_ingest_statements_writes_text_cache_on_miss(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path, ingest_workers=1)
    settings = replace(settings, ingest_text_cache_enabled=True)
    pdf_path = settings.input_path / "statement_2025-01-01.pdf"
    pdf_path.write_text("fake", encoding="utf-8")

    captured: dict[str, object] = {}
    monkeypatch.setattr("finance_tooling.workflow.ingest.load_text_cache", lambda _: ({}, []))

    def _capture_upsert(path: Path, rows):
        captured["path"] = path
        captured["rows"] = rows
        return len(rows), []

    monkeypatch.setattr("finance_tooling.workflow.ingest.upsert_text_cache", _capture_upsert)

    result = ingest_statements(
        settings,
        discover_statement_pdfs=lambda _: [pdf_path],
        extract_text_from_pdf=lambda _: ExtractedPdfText(first_page_text="fp", full_text="full"),
        select_parser_with_diagnostics=_selection_for_dummy,
    )

    assert captured["path"] == settings.ingest_text_cache_path
    rows = cast(list[object], captured["rows"])
    assert len(rows) == 1
    assert result.text_cache_enabled is True
    assert result.text_cache_hits == 0
    assert result.text_cache_misses == 1
    assert result.text_cache_write_count == 1

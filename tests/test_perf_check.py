from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.classify import ClassificationDiagnostics
from finance_tooling.config import Settings
from finance_tooling.models import Transaction, WorkflowResult
from finance_tooling.perf_check import assert_isolated_processed_path, run_perf_check
from finance_tooling.workflow.types import EnrichmentResult, HsbcMergeResult, IngestResult


def _settings(tmp_path: Path, processed_dir: Path) -> Settings:
    return Settings(
        input_path=tmp_path / "input",
        output_path=processed_dir / "finance_dashboard.html",
        master_parquet_path=processed_dir / "transactions_master.parquet",
        export_csv_path=processed_dir / "transactions_normalized.csv",
        export_json_path=processed_dir / "transactions_normalized.json",
        staged_transactions_path=processed_dir / "staged_transactions.parquet",
        summary_json_path=processed_dir / "run_summary.json",
        completeness_json_path=processed_dir / "completeness_report.json",
        base_currency="EUR",
        fx_cache_path=processed_dir / "fx_rates_history.parquet",
        fx_auto_fetch=False,
        ingest_workers=1,
        ingest_text_cache_enabled=False,
        ingest_text_cache_path=processed_dir / "ingest_text_cache.parquet",
        category_rules_path=processed_dir / "category_rules.yaml",
        project_rules_path=processed_dir / "project_rules.yaml",
        budget_targets_path=processed_dir / "budget_targets.yaml",
        project_overrides_path=Path("config/project_overrides.yaml").resolve(),
        transaction_overrides_path=Path("config/transaction_overrides.yaml").resolve(),
        review_state_path=processed_dir / "review_state.parquet",
        review_export_dark_safe=True,
    )


def test_run_perf_check_writes_performance_summary_and_stage_timings(
    monkeypatch, tmp_path: Path
) -> None:
    processed_dir = tmp_path / "processed_perf"
    settings = _settings(tmp_path, processed_dir)
    settings.input_path.mkdir(parents=True, exist_ok=True)

    tx = Transaction(
        booking_date=date(2024, 1, 1),
        description="Salary",
        amount_native=Decimal("100.00"),
        currency="EUR",
        source_file=settings.input_path / "statement_2024-01-01.pdf",
        bank="DummyBank",
        parser="dummy",
    )
    ingest_result = IngestResult(
        source_files=[tx.source_file],
        raw_file_count=1,
        duplicate_raw_file_count=0,
        source_inventory_path=processed_dir / "source_inventory.json",
        transactions=[tx],
        validations=[],
        warnings=[],
        files_failed=0,
        parser_selection_diagnostics=[],
        parser_low_confidence_file_count=0,
        hsbc_statement_periods_by_date={},
        hsbc_period_parse_variant_match_count=0,
        hsbc_boundary_metrics={
            "table_start_count": 0,
            "table_end_count": 0,
            "rows_seen_in_table": 0,
            "rows_rejected_outside_table": 0,
            "rows_rejected_after_table": 0,
            "transition_anomaly_count": 0,
        },
        hsbc_boundary_diagnostics=[],
        hsbc_sign_metrics={
            "sign_from_running_balance_count": 0,
            "sign_from_column_position_count": 0,
            "sign_from_token_marker_count": 0,
            "sign_from_description_marker_count": 0,
            "sign_from_fallback_hint_count": 0,
            "sign_default_debit_count": 0,
            "sign_conflict_running_vs_marker_count": 0,
            "sign_unresolved_ambiguous_count": 0,
        },
        hsbc_sign_diagnostics=[],
        hsbc_csv_files_scanned=0,
        parser_duration_seconds_by_parser={"dummy": 1.5},
        duration_seconds_by_bank={"DummyBank": 1.5},
        text_cache_enabled=False,
        text_cache_hits=0,
        text_cache_misses=0,
        text_cache_write_count=0,
    )
    hsbc_merge_result = HsbcMergeResult(
        transactions=[tx],
        validations=[],
        warnings=[],
        metrics={
            "hsbc_csv_statement_replaced_count": 0,
            "hsbc_pdf_fallback_statement_count": 0,
            "hsbc_csv_only_statement_count": 0,
            "hsbc_pdf_balance_validated_count": 0,
            "hsbc_pdf_balance_validation_fail_count": 0,
            "hsbc_adaptive_source_switch_count": 0,
            "hsbc_selected_csv_month_count": 0,
            "hsbc_selected_pdf_month_count": 0,
            "hsbc_period_remap_applied_month_count": 0,
            "hsbc_period_remap_reassigned_tx_count": 0,
            "hsbc_period_remap_unassigned_csv_tx_count": 0,
        },
        selection_diagnostics=[],
    )
    enrichment_result = EnrichmentResult(
        transactions=[tx],
        warnings=[],
        classification_diagnostics=ClassificationDiagnostics(
            categorized_count=1,
            uncategorized_count=0,
            uncategorized_ratio=0.0,
            category_source_counts={"rule": 1},
            top_uncategorized_descriptions=[],
            top_rules_by_hits=[],
        ),
        manual_category_carry_forward_applied_count=0,
        manual_category_carry_forward_ambiguous_skipped_count=0,
        manual_category_carry_forward_unmatched_count=1,
    )
    workflow_result = WorkflowResult(
        dashboard_path=settings.output_path,
        parquet_path=settings.master_parquet_path,
        csv_path=settings.export_csv_path,
        json_path=settings.export_json_path,
        summary_path=settings.summary_json_path,
        completeness_path=settings.completeness_json_path,
        files_scanned=1,
        files_failed=0,
        transactions_parsed=1,
        new_rows=1,
        total_rows=1,
        completeness_status="pass",
        completeness_coverage_ratio=1.0,
        missing_source_file_count=0,
        reconciliation_checkable_file_count=1,
        reconciliation_fail_count=0,
        reconciliation_uncheckable_file_count=0,
        reconciliation_pass_ratio=1.0,
        categorized_count=1,
        uncategorized_count=0,
        categorized_amount_eur_abs=100.0,
        uncategorized_amount_eur_abs=0.0,
        categorized_amount_eur_abs_ratio=1.0,
        uncategorized_amount_eur_abs_ratio=0.0,
        categorized_count_delta=None,
        uncategorized_count_delta=None,
        categorized_amount_eur_abs_delta=None,
        uncategorized_amount_eur_abs_delta=None,
        warnings=(),
    )

    clock = iter([0.0, 1.0, 3.5, 4.0, 4.5, 5.0, 7.0, 8.0, 9.25, 10.0])
    monkeypatch.setattr("finance_tooling.perf_check.perf_counter", lambda: next(clock))
    monkeypatch.setattr(
        "finance_tooling.perf_check.ingest_statements",
        lambda *args, **kwargs: ingest_result,
    )
    monkeypatch.setattr(
        "finance_tooling.perf_check.merge_hsbc_sources",
        lambda *args, **kwargs: hsbc_merge_result,
    )
    monkeypatch.setattr(
        "finance_tooling.perf_check.enrich_transactions",
        lambda *args, **kwargs: enrichment_result,
    )

    def _persist(*args, **kwargs):
        del args, kwargs
        return workflow_result, {
            "parser_low_confidence_file_count": 2,
            "uncategorized_ratio": 0.1,
            "ingest_parser_duration_seconds_by_parser": {"dummy": 1.5},
            "ingest_duration_seconds_by_bank": {"DummyBank": 1.5},
            "ingest_text_cache_enabled": False,
            "ingest_text_cache_hits": 0,
            "ingest_text_cache_misses": 0,
            "ingest_text_cache_write_count": 0,
        }

    monkeypatch.setattr("finance_tooling.perf_check.persist_and_report", _persist)

    result = run_perf_check(settings)

    payload = (processed_dir / "performance_summary.json").read_text(encoding="utf-8")
    assert result.performance_summary_path == processed_dir / "performance_summary.json"
    assert result.total_duration_seconds == 10.0
    assert result.stage_durations_seconds == {
        "ingest": 2.5,
        "hsbc_merge": 0.5,
        "enrichment": 2.0,
        "reporting": 1.25,
    }
    assert '"files_scanned": 1' in payload
    assert '"parser_low_confidence_file_count": 2' in payload
    assert '"uncategorized_ratio": 0.1' in payload
    assert '"ingest_parser_duration_seconds_by_parser"' in payload
    assert '"ingest_duration_seconds_by_bank"' in payload
    assert '"ingest_text_cache_enabled": false' in payload
    assert '"ingest_text_cache_hits": 0' in payload


def test_assert_isolated_processed_path_blocks_dotenv_processed_dir(
    monkeypatch, tmp_path: Path
) -> None:
    standard_dir = tmp_path / "processed"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(f"FINANCE_PROCESSED_PATH={standard_dir}\n", encoding="utf-8")
    monkeypatch.setattr("finance_tooling.perf_check.DOTENV_PATH", dotenv_path)

    settings = _settings(tmp_path, standard_dir)

    try:
        assert_isolated_processed_path(settings)
    except ValueError as exc:
        assert "matches .env FINANCE_PROCESSED_PATH" in str(exc)
    else:
        raise AssertionError("Expected a ValueError for in-place performance path")


def test_assert_isolated_processed_path_allows_override(monkeypatch, tmp_path: Path) -> None:
    standard_dir = tmp_path / "processed"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(f"FINANCE_PROCESSED_PATH={standard_dir}\n", encoding="utf-8")
    monkeypatch.setattr("finance_tooling.perf_check.DOTENV_PATH", dotenv_path)
    monkeypatch.setenv("FINANCE_PERF_ALLOW_IN_PLACE", "true")

    settings = _settings(tmp_path, standard_dir)
    assert_isolated_processed_path(settings)

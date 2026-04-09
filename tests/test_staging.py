from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from finance_tooling.core.config import Settings
from finance_tooling.core.models import Transaction
from finance_tooling.workflow.staging import (
    read_staged_transactions,
    resolve_staged_transactions_path,
    write_staged_transactions,
)


def _settings(tmp_path: Path) -> Settings:
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    input_dir.mkdir()
    (processed_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (processed_dir / "state").mkdir(parents=True, exist_ok=True)
    return Settings(
        input_path=input_dir,
        processed_path=processed_dir,
        output_path=processed_dir / "outputs" / "transform_dashboard.html",
        master_parquet_path=processed_dir / "outputs" / "transform_transactions.parquet",
        export_csv_path=processed_dir / "outputs" / "transform_transactions.csv",
        export_json_path=processed_dir / "outputs" / "transform_transactions.json",
        staged_transactions_path=processed_dir / "state" / "ingest_staged_transactions.parquet",
        summary_json_path=processed_dir / "outputs" / "transform_run_summary.json",
        completeness_json_path=processed_dir / "state" / "transform_completeness_report.json",
        base_currency="EUR",
        fx_cache_path=processed_dir / "state" / "workflow_fx_rates_history.parquet",
        fx_auto_fetch=False,
        ingest_workers=1,
        ingest_text_cache_enabled=False,
        ingest_text_cache_path=processed_dir / "state" / "ingest_text_cache.parquet",
        category_rules_path=processed_dir / "category_rules.yaml",
        project_rules_path=processed_dir / "project_rules.yaml",
        budget_targets_path=processed_dir / "budget_targets.yaml",
        account_rules_path=processed_dir / "account_rules.yaml",
        project_overrides_path=processed_dir / "project_overrides.yaml",
        transaction_overrides_path=processed_dir / "transaction_overrides.yaml",
        review_state_path=processed_dir / "state" / "workflow_review_state.parquet",
        review_export_dark_safe=True,
    )


def test_staging_roundtrip_preserves_transaction_fields(tmp_path: Path) -> None:
    staged_path = tmp_path / "staged_transactions.parquet"
    source_file = tmp_path / "statement.pdf"
    source_file.write_text("fake", encoding="utf-8")

    transaction = Transaction(
        booking_date=date(2024, 5, 6),
        description="Card payment",
        amount_native=Decimal("-10.25"),
        currency="EUR",
        source_file=source_file,
        bank="DummyBank",
        parser="dummy",
        category="Food",
        subcategory="Groceries",
        category_confidence=0.9,
        category_source="rule",
        category_rule_id="food_rule",
        project="ProjectAtlas",
        project_tags=("ProjectAtlas", "Family"),
        project_source="project_rule",
        account_label="Main",
        fx_rate_to_eur=Decimal("1.0"),
        fx_rate_date=date(2024, 5, 6),
        fx_source="BASE",
        amount_eur=Decimal("-10.25"),
        source_record_index=7,
        source_file_mtime=datetime.fromisoformat("2024-05-06T12:34:56+00:00"),
    )

    write_staged_transactions(staged_path, [transaction])
    loaded = read_staged_transactions(staged_path)

    assert len(loaded) == 1
    assert loaded[0] == transaction


def test_read_staged_transactions_validates_required_columns(tmp_path: Path) -> None:
    staged_path = tmp_path / "staged_transactions.parquet"
    dataframe = pd.DataFrame(
        [
            {
                "booking_date": "2024-05-06",
                "description": "Card payment",
                "amount_native": "-10.25",
                "currency": "EUR",
                "source_file": str(tmp_path / "statement.pdf"),
                "bank": "DummyBank",
            }
        ]
    )
    dataframe.to_parquet(staged_path, index=False)

    try:
        read_staged_transactions(staged_path)
    except ValueError as exc:
        message = str(exc)
        assert "missing columns" in message
        assert "parser" in message
    else:
        raise AssertionError("Expected ValueError for missing staged columns.")


def test_resolve_staged_transactions_path_supports_legacy_outputs_location(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    legacy_path = settings.summary_json_path.parent / "staged_transactions.parquet"
    legacy_path.write_text("placeholder", encoding="utf-8")

    with pytest.warns(FutureWarning, match="legacy staged transactions path"):
        assert resolve_staged_transactions_path(settings) == legacy_path


def test_read_staged_transactions_backfills_legacy_identity_columns(tmp_path: Path) -> None:
    staged_path = tmp_path / "staged_transactions.parquet"
    source_file = tmp_path / "statement.pdf"
    source_file.write_text("fake", encoding="utf-8")
    dataframe = pd.DataFrame(
        [
            {
                "booking_date": "2024-05-06",
                "description": "Card payment",
                "amount_native": "-10.25",
                "currency": "EUR",
                "source_file": str(source_file),
                "bank": "DummyBank",
                "parser": "dummy",
                "category": "Uncategorized",
                "subcategory": None,
                "category_confidence": None,
                "category_source": None,
                "category_rule_id": None,
                "project": None,
                "project_tags": None,
                "project_source": None,
                "account_label": None,
                "fx_rate_to_eur": None,
                "fx_rate_date": None,
                "fx_source": None,
                "amount_eur": None,
                "source_file_mtime": None,
            },
            {
                "booking_date": "2024-05-07",
                "description": "Card payment",
                "amount_native": "-2.00",
                "currency": "EUR",
                "source_file": str(source_file),
                "bank": "DummyBank",
                "parser": "dummy",
                "category": "Uncategorized",
                "subcategory": None,
                "category_confidence": None,
                "category_source": None,
                "category_rule_id": None,
                "project": None,
                "project_tags": None,
                "project_source": None,
                "account_label": None,
                "fx_rate_to_eur": None,
                "fx_rate_date": None,
                "fx_source": None,
                "amount_eur": None,
                "source_file_mtime": None,
            },
        ]
    )
    dataframe.to_parquet(staged_path, index=False)

    loaded = read_staged_transactions(staged_path)

    assert [tx.source_record_index for tx in loaded] == [0, 1]
    assert loaded[0].source_document_id is not None
    assert loaded[0].source_document_id == loaded[1].source_document_id


def test_read_staged_transactions_skips_legacy_backfill_for_modern_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    staged_path = tmp_path / "staged_transactions.parquet"
    source_file = tmp_path / "statement.pdf"
    source_file.write_text("fake", encoding="utf-8")

    transaction = Transaction(
        booking_date=date(2024, 5, 6),
        description="Card payment",
        amount_native=Decimal("-10.25"),
        currency="EUR",
        source_file=source_file,
        bank="DummyBank",
        parser="dummy",
        category="Food",
        subcategory="Groceries",
        category_confidence=0.9,
        category_source="rule",
        category_rule_id="food_rule",
        project="ProjectAtlas",
        project_tags=("ProjectAtlas", "Family"),
        project_source="project_rule",
        account_label="Main",
        fx_rate_to_eur=Decimal("1.0"),
        fx_rate_date=date(2024, 5, 6),
        fx_source="BASE",
        amount_eur=Decimal("-10.25"),
        source_record_index=7,
        source_document_id="doc-1",
        source_file_mtime=datetime.fromisoformat("2024-05-06T12:34:56+00:00"),
    )

    write_staged_transactions(staged_path, [transaction])

    def fail_compute_source_document_id(_: Path) -> str:
        raise AssertionError("legacy backfill should not run for modern staged files")

    monkeypatch.setattr(
        "finance_tooling.workflow.staging.compute_source_document_id",
        fail_compute_source_document_id,
    )

    loaded = read_staged_transactions(staged_path)

    assert loaded == [transaction]

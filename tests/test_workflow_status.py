from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from finance_tooling.config import Settings
from finance_tooling.workflow_status import build_pipeline_state

HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None
pytestmark = pytest.mark.skipif(not HAS_PYARROW, reason="pyarrow is required")


def _settings(tmp_path: Path) -> Settings:
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    input_dir.mkdir()
    processed_dir.mkdir()
    return Settings(
        input_path=input_dir,
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
        project_overrides_path=processed_dir / "project_overrides.yaml",
        transaction_overrides_path=processed_dir / "transaction_overrides.yaml",
        review_state_path=processed_dir / "review_state.parquet",
        review_export_dark_safe=True,
    )


def test_build_pipeline_state_reports_duplicate_raw_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = settings.input_path / "statement_a.pdf"
    duplicate = settings.input_path / "statement_b.pdf"
    first.write_bytes(b"same-content")
    duplicate.write_bytes(b"same-content")

    payload, output_path = build_pipeline_state(settings)

    assert output_path.exists()
    assert payload["status"] == "warn"
    raw_state = payload["raw_source_state"]
    assert raw_state["raw_file_count"] == 2
    assert raw_state["ignored_duplicate_file_count"] == 1
    findings = payload["findings"]
    assert any(item["code"] == "duplicate_raw_sources" for item in findings)


def test_build_pipeline_state_reports_staged_newer_than_transform(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = settings.input_path / "statement.pdf"
    source.write_bytes(b"content")

    pd.DataFrame(
        [
            {
                "transaction_id": "tx-1",
                "booking_date": "2026-01-01",
            }
        ]
    ).to_parquet(settings.master_parquet_path, index=False)
    settings.summary_json_path.write_text(
        json.dumps({"generated_at": "2026-03-21T12:00:00+00:00"}),
        encoding="utf-8",
    )
    settings.completeness_json_path.write_text("{}", encoding="utf-8")
    settings.staged_transactions_path.write_text("pending", encoding="utf-8")

    payload, _ = build_pipeline_state(settings)

    findings = payload["findings"]
    assert any(item["code"] == "staged_newer_than_transform" for item in findings)

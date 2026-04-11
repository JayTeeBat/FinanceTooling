from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from finance_tooling.core.config import Settings
from finance_tooling.core.source_inventory import build_source_inventory
from finance_tooling.reporting.workflow_status import build_pipeline_state
from finance_tooling.workflow.incremental_state import (
    build_incremental_selection_plan,
    compute_rule_config_fingerprint,
    compute_transform_input_fingerprint,
    resolve_staged_batch_manifest_path,
    resolve_staged_transactions_path,
    source_registry_path,
    update_source_registry,
    write_source_registry,
)

HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None
pytestmark = pytest.mark.skipif(not HAS_PYARROW, reason="pyarrow is required")


def _settings(tmp_path: Path) -> Settings:
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    input_dir.mkdir()
    processed_dir.mkdir()
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
    settings.staged_transactions_path.parent.mkdir(parents=True, exist_ok=True)
    settings.staged_transactions_path.write_text("pending", encoding="utf-8")

    payload, _ = build_pipeline_state(settings)

    findings = payload["findings"]
    assert any(item["code"] == "staged_newer_than_transform" for item in findings)


def test_build_pipeline_state_exposes_review_queue_summary(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.summary_json_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-11T12:00:00+00:00",
                "unreviewed_uncategorized_count": 5,
                "needs_rule_count": 2,
                "top_review_groups": [
                    {"review_group_key": "merchant alpha | REVOLUT | Main", "count": 3}
                ],
            }
        ),
        encoding="utf-8",
    )
    settings.completeness_json_path.write_text("{}", encoding="utf-8")

    payload, _ = build_pipeline_state(settings)

    assert payload["review_queue"]["unreviewed_uncategorized_count"] == 5
    assert payload["review_queue"]["needs_rule_count"] == 2
    assert payload["review_queue"]["top_review_groups"][0]["count"] == 3


def test_bootstrap_incremental_registry_does_not_report_config_drift(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = settings.input_path / "statement.pdf"
    source.write_bytes(b"content")

    inventory = build_source_inventory([source])
    selection_plan = build_incremental_selection_plan(
        settings=settings,
        run_mode="incremental",
        current_inventory=inventory,
        registry=None,
    )
    registry = update_source_registry(
        existing=None,
        selection_plan=selection_plan,
        processed_source_files=[source],
        validations=[],
        transactions=[],
    )
    write_source_registry(source_registry_path(settings), registry)

    payload, _ = build_pipeline_state(settings)

    assert payload["drift_state"]["dataset_stale"] is False
    assert payload["drift_state"]["full_refresh_risk"] == "low"
    assert payload["committed_state"]["config_drift_since_last_full_refresh"] is False


def test_incremental_state_prefers_legacy_outputs_registry_and_staged_artifacts(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    legacy_registry = settings.summary_json_path.parent / "source_registry.json"
    legacy_registry.write_text("{}", encoding="utf-8")
    legacy_manifest = settings.summary_json_path.parent / "staged_batch_manifest.json"
    legacy_manifest.write_text("{}", encoding="utf-8")
    legacy_staged = settings.summary_json_path.parent / "staged_transactions.parquet"
    legacy_staged.write_text("placeholder", encoding="utf-8")

    with pytest.warns(FutureWarning, match="legacy source registry path"):
        assert source_registry_path(settings) == legacy_registry
    with pytest.warns(FutureWarning, match="legacy staged batch manifest path"):
        assert resolve_staged_batch_manifest_path(settings) == legacy_manifest
    with pytest.warns(FutureWarning, match="legacy staged transactions path"):
        assert resolve_staged_transactions_path(settings) == legacy_staged


def test_transaction_override_changes_do_not_report_config_drift(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = settings.input_path / "statement.pdf"
    source.write_bytes(b"content")
    settings.category_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")
    settings.project_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")
    settings.project_overrides_path.write_text(
        "version: 1\nrules: []\noverrides: []\n",
        encoding="utf-8",
    )
    settings.transaction_overrides_path.write_text("version: 1\noverrides: []\n", encoding="utf-8")

    inventory = build_source_inventory([source])
    selection_plan = build_incremental_selection_plan(
        settings=settings,
        run_mode="incremental",
        current_inventory=inventory,
        registry=None,
    )
    registry = update_source_registry(
        existing=None,
        selection_plan=selection_plan,
        processed_source_files=[source],
        validations=[],
        transactions=[],
    )
    write_source_registry(source_registry_path(settings), registry)

    settings.transaction_overrides_path.write_text(
        "version: 1\noverrides:\n- transaction_id: tx-1\n  category: Groceries\n",
        encoding="utf-8",
    )

    payload, _ = build_pipeline_state(settings)

    assert payload["drift_state"]["dataset_stale"] is False
    assert payload["committed_state"]["config_drift_since_last_full_refresh"] is False
    assert not any(
        item["code"] == "config_changed_since_last_full_refresh"
        for item in payload["findings"]
    )


def test_rule_changes_report_config_drift(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = settings.input_path / "statement.pdf"
    source.write_bytes(b"content")
    settings.category_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")
    settings.project_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")

    inventory = build_source_inventory([source])
    selection_plan = build_incremental_selection_plan(
        settings=settings,
        run_mode="full_refresh",
        current_inventory=inventory,
        registry=None,
    )
    registry = update_source_registry(
        existing=None,
        selection_plan=selection_plan,
        processed_source_files=[source],
        validations=[],
        transactions=[],
    )
    write_source_registry(source_registry_path(settings), registry)

    assert (
        registry.last_full_refresh_config_fingerprint
        == compute_rule_config_fingerprint(settings)
    )

    settings.category_rules_path.write_text(
        "version: 1\nrules:\n- id: groceries\n  category: Groceries\n",
        encoding="utf-8",
    )

    payload, _ = build_pipeline_state(settings)

    assert payload["drift_state"]["dataset_stale"] is True
    assert payload["committed_state"]["config_drift_since_last_full_refresh"] is True
    assert any(
        item["code"] == "config_changed_since_last_full_refresh"
        for item in payload["findings"]
    )


def test_legacy_full_refresh_fingerprint_ignores_override_only_drift(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = settings.input_path / "statement.pdf"
    source.write_bytes(b"content")
    settings.category_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")
    settings.project_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")
    settings.project_overrides_path.write_text(
        "version: 1\nrules: []\noverrides: []\n",
        encoding="utf-8",
    )
    settings.transaction_overrides_path.write_text("version: 1\noverrides: []\n", encoding="utf-8")

    inventory = build_source_inventory([source])
    selection_plan = build_incremental_selection_plan(
        settings=settings,
        run_mode="full_refresh",
        current_inventory=inventory,
        registry=None,
    )
    registry = update_source_registry(
        existing=None,
        selection_plan=selection_plan,
        processed_source_files=[source],
        validations=[],
        transactions=[],
    )

    last_full_refresh_at = registry.last_full_refresh_at
    assert last_full_refresh_at is not None
    registry = registry.__class__(
        generated_at=registry.generated_at,
        last_run_mode=registry.last_run_mode,
        last_full_refresh_at="2026-03-21T12:00:00+00:00",
        last_full_refresh_config_fingerprint=compute_transform_input_fingerprint(settings),
        entries=registry.entries,
    )
    write_source_registry(source_registry_path(settings), registry)

    backup_dir = settings.processed_path.parent / "backup" / "20260321-120000-000000"
    (backup_dir / "config").mkdir(parents=True, exist_ok=True)
    (backup_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "20260321-120000-000000",
                "retention_day_local": "2026-03-21",
                "created_at": "2026-03-21T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (backup_dir / "config" / settings.category_rules_path.name).write_text(
        settings.category_rules_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (backup_dir / "config" / settings.project_rules_path.name).write_text(
        settings.project_rules_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    settings.transaction_overrides_path.write_text(
        "version: 1\noverrides:\n- transaction_id: tx-1\n  category: Groceries\n",
        encoding="utf-8",
    )

    payload, _ = build_pipeline_state(settings)

    assert payload["drift_state"]["dataset_stale"] is False
    assert payload["committed_state"]["config_drift_since_last_full_refresh"] is False
    assert not any(
        item["code"] == "config_changed_since_last_full_refresh"
        for item in payload["findings"]
    )

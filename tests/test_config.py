import os
from pathlib import Path
from typing import cast

from finance_tooling.core.config import (
    BASE_CURRENCY_ENV,
    BUDGET_TARGETS_PATH_ENV,
    CATEGORY_RULES_PATH_ENV,
    EXPORT_CSV_PATH_ENV,
    EXPORT_JSON_PATH_ENV,
    FX_AUTO_FETCH_ENV,
    FX_CACHE_PATH_ENV,
    INGEST_STAGED_TRANSACTIONS_FILENAME,
    INGEST_TEXT_CACHE_ENABLED_ENV,
    INGEST_TEXT_CACHE_PATH_ENV,
    INGEST_WORKERS_ENV,
    INPUT_PATH_ENV,
    MASTER_PARQUET_ENV,
    OUTPUT_PATH_ENV,
    PIPELINE_INGEST_DIRNAME,
    PIPELINE_OUTPUTS_DIRNAME,
    PIPELINE_PLANNING_DIRNAME,
    PIPELINE_STATE_DIRNAME,
    PIPELINE_TRANSFORM_DIRNAME,
    PROCESSED_PATH_ENV,
    PROJECT_OVERRIDES_PATH_ENV,
    PROJECT_RULES_PATH_ENV,
    REVIEW_EXPORT_DARK_SAFE_ENV,
    REVIEW_STATE_PATH_ENV,
    STAGED_TRANSACTIONS_PATH_ENV,
    TRANSACTION_OVERRIDES_PATH_ENV,
    TRANSFORM_COMPLETENESS_FILENAME,
    TRANSFORM_DASHBOARD_FILENAME,
    TRANSFORM_SUMMARY_FILENAME,
    TRANSFORM_TRANSACTIONS_CSV_FILENAME,
    TRANSFORM_TRANSACTIONS_FILENAME,
    TRANSFORM_TRANSACTIONS_JSON_FILENAME,
    WORKFLOW_FX_CACHE_FILENAME,
    WORKFLOW_REVIEW_STATE_FILENAME,
    Settings,
    ingest_root_path,
    load_settings_from_env,
    planning_root_path,
    resolve_ingest_artifact_path,
    resolve_transform_artifact_path,
    transform_root_path,
)


def test_load_settings_defaults_outputs_to_processed_dir(monkeypatch, tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    monkeypatch.setenv(INPUT_PATH_ENV, str(raw_dir))
    monkeypatch.setenv(PROCESSED_PATH_ENV, str(processed_dir))
    monkeypatch.delenv(OUTPUT_PATH_ENV, raising=False)
    monkeypatch.delenv(MASTER_PARQUET_ENV, raising=False)
    monkeypatch.delenv(EXPORT_CSV_PATH_ENV, raising=False)
    monkeypatch.delenv(EXPORT_JSON_PATH_ENV, raising=False)
    monkeypatch.delenv(STAGED_TRANSACTIONS_PATH_ENV, raising=False)
    monkeypatch.delenv(FX_CACHE_PATH_ENV, raising=False)
    monkeypatch.delenv(FX_AUTO_FETCH_ENV, raising=False)
    monkeypatch.delenv(INGEST_WORKERS_ENV, raising=False)
    monkeypatch.delenv(INGEST_TEXT_CACHE_ENABLED_ENV, raising=False)
    monkeypatch.delenv(INGEST_TEXT_CACHE_PATH_ENV, raising=False)
    monkeypatch.delenv(CATEGORY_RULES_PATH_ENV, raising=False)
    monkeypatch.delenv(PROJECT_RULES_PATH_ENV, raising=False)
    monkeypatch.delenv(BUDGET_TARGETS_PATH_ENV, raising=False)
    monkeypatch.delenv(PROJECT_OVERRIDES_PATH_ENV, raising=False)
    monkeypatch.delenv(TRANSACTION_OVERRIDES_PATH_ENV, raising=False)
    monkeypatch.delenv(REVIEW_STATE_PATH_ENV, raising=False)
    monkeypatch.delenv(REVIEW_EXPORT_DARK_SAFE_ENV, raising=False)
    monkeypatch.delenv(BASE_CURRENCY_ENV, raising=False)

    settings = load_settings_from_env()

    assert settings.input_path == raw_dir.resolve()
    assert (
        settings.output_path == (processed_dir / "transform" / "transform_dashboard.html").resolve()
    )
    assert (
        settings.master_parquet_path
        == (processed_dir / "transform" / "transform_transactions.parquet").resolve()
    )
    assert (
        settings.export_csv_path
        == (processed_dir / "transform" / "transform_transactions.csv").resolve()
    )
    assert (
        settings.export_json_path
        == (processed_dir / "transform" / "transform_transactions.json").resolve()
    )
    assert settings.export_json_enabled is False
    assert settings.transform_diagnostics_enabled is False
    assert (
        settings.staged_transactions_path
        == (processed_dir / "ingest" / "ingest_staged_transactions.parquet").resolve()
    )
    assert (
        settings.summary_json_path
        == (processed_dir / "transform" / "transform_run_summary.json").resolve()
    )
    assert (
        settings.completeness_json_path
        == (processed_dir / "transform" / "transform_completeness_report.json").resolve()
    )
    assert (
        settings.fx_cache_path
        == (processed_dir / "transform" / "workflow_fx_rates_history.parquet").resolve()
    )
    config_dir = raw_dir.parent / "config"
    assert settings.category_rules_path == (config_dir / "category_rules.yaml").resolve()
    assert settings.project_rules_path == (config_dir / "project_rules.yaml").resolve()
    assert settings.budget_targets_path == (config_dir / "budget_targets.yaml").resolve()
    assert settings.project_overrides_path == (config_dir / "project_overrides.yaml").resolve()
    assert (
        settings.transaction_overrides_path == (config_dir / "transaction_overrides.yaml").resolve()
    )
    assert (
        settings.review_state_path
        == (processed_dir / "transform" / "workflow_review_state.parquet").resolve()
    )
    assert settings.review_export_dark_safe is True
    assert settings.base_currency == "EUR"
    assert settings.fx_auto_fetch is True
    assert settings.ingest_workers == min(os.cpu_count() or 1, 4)
    assert settings.ingest_text_cache_enabled is False
    assert (
        settings.ingest_text_cache_path
        == (processed_dir / "ingest" / "ingest_text_cache.parquet").resolve()
    )


def test_load_settings_honors_explicit_output_overrides(monkeypatch, tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    custom_dir = tmp_path / "custom_out"
    custom_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    monkeypatch.setenv(INPUT_PATH_ENV, str(raw_dir))
    monkeypatch.setenv(PROCESSED_PATH_ENV, str(processed_dir))
    monkeypatch.setenv(OUTPUT_PATH_ENV, str(custom_dir / "dash.html"))
    monkeypatch.setenv(MASTER_PARQUET_ENV, str(custom_dir / "master.parquet"))
    monkeypatch.setenv(EXPORT_CSV_PATH_ENV, str(custom_dir / "tx.csv"))
    monkeypatch.setenv(EXPORT_JSON_PATH_ENV, str(custom_dir / "tx.json"))
    monkeypatch.setenv(STAGED_TRANSACTIONS_PATH_ENV, str(custom_dir / "staged.parquet"))
    monkeypatch.setenv(FX_CACHE_PATH_ENV, str(custom_dir / "fx.parquet"))
    monkeypatch.setenv(FX_AUTO_FETCH_ENV, "false")
    monkeypatch.setenv(INGEST_WORKERS_ENV, "4")
    monkeypatch.setenv(INGEST_TEXT_CACHE_ENABLED_ENV, "true")
    monkeypatch.setenv(INGEST_TEXT_CACHE_PATH_ENV, str(custom_dir / "ingest_cache.parquet"))
    monkeypatch.setenv(CATEGORY_RULES_PATH_ENV, str(custom_dir / "category_rules.yaml"))
    monkeypatch.setenv(PROJECT_RULES_PATH_ENV, str(custom_dir / "project_rules.yaml"))
    monkeypatch.setenv(BUDGET_TARGETS_PATH_ENV, str(custom_dir / "budget_targets.yaml"))
    monkeypatch.setenv(PROJECT_OVERRIDES_PATH_ENV, str(custom_dir / "project_overrides.yaml"))
    monkeypatch.setenv(
        TRANSACTION_OVERRIDES_PATH_ENV,
        str(custom_dir / "transaction_overrides.yaml"),
    )
    monkeypatch.setenv(REVIEW_STATE_PATH_ENV, str(custom_dir / "review_state.parquet"))
    monkeypatch.setenv(REVIEW_EXPORT_DARK_SAFE_ENV, "false")
    monkeypatch.setenv(BASE_CURRENCY_ENV, "gbp")

    settings = load_settings_from_env()

    assert settings.output_path == (custom_dir / "dash.html").resolve()
    assert settings.master_parquet_path == (custom_dir / "master.parquet").resolve()
    assert settings.export_csv_path == (custom_dir / "tx.csv").resolve()
    assert settings.export_json_path == (custom_dir / "tx.json").resolve()
    assert settings.staged_transactions_path == (custom_dir / "staged.parquet").resolve()
    assert settings.fx_cache_path == (custom_dir / "fx.parquet").resolve()
    assert settings.category_rules_path == (custom_dir / "category_rules.yaml").resolve()
    assert settings.project_rules_path == (custom_dir / "project_rules.yaml").resolve()
    assert settings.budget_targets_path == (custom_dir / "budget_targets.yaml").resolve()
    assert settings.project_overrides_path == (custom_dir / "project_overrides.yaml").resolve()
    assert (
        settings.transaction_overrides_path == (custom_dir / "transaction_overrides.yaml").resolve()
    )
    assert settings.review_state_path == (custom_dir / "review_state.parquet").resolve()
    assert settings.review_export_dark_safe is False
    assert (
        settings.summary_json_path
        == (processed_dir / "transform" / "transform_run_summary.json").resolve()
    )
    assert (
        settings.completeness_json_path
        == (processed_dir / "transform" / "transform_completeness_report.json").resolve()
    )
    assert settings.base_currency == "GBP"
    assert settings.fx_auto_fetch is False
    assert settings.ingest_workers == 4
    assert settings.ingest_text_cache_enabled is True
    assert settings.ingest_text_cache_path == (custom_dir / "ingest_cache.parquet").resolve()


def test_load_settings_requires_input_and_processed_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(INPUT_PATH_ENV, raising=False)
    monkeypatch.delenv(PROCESSED_PATH_ENV, raising=False)

    try:
        load_settings_from_env()
    except ValueError as exc:
        assert INPUT_PATH_ENV in str(exc)
    else:
        raise AssertionError("Expected ValueError when required env vars are missing")


def test_load_settings_reads_required_paths_from_dotenv(monkeypatch, tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                f"{INPUT_PATH_ENV}={raw_dir}",
                f"{PROCESSED_PATH_ENV}={processed_dir}",
                f"{BASE_CURRENCY_ENV}=usd",
                f"{FX_AUTO_FETCH_ENV}=false",
                f"{INGEST_WORKERS_ENV}=2",
                f"{INGEST_TEXT_CACHE_ENABLED_ENV}=true",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(INPUT_PATH_ENV, raising=False)
    monkeypatch.delenv(PROCESSED_PATH_ENV, raising=False)
    monkeypatch.delenv(BASE_CURRENCY_ENV, raising=False)
    monkeypatch.delenv(FX_AUTO_FETCH_ENV, raising=False)
    monkeypatch.delenv(INGEST_WORKERS_ENV, raising=False)
    monkeypatch.delenv(INGEST_TEXT_CACHE_ENABLED_ENV, raising=False)

    settings = load_settings_from_env()

    assert settings.input_path == raw_dir.resolve()
    assert (
        settings.summary_json_path
        == (processed_dir / "transform" / "transform_run_summary.json").resolve()
    )
    assert settings.base_currency == "USD"
    assert settings.fx_auto_fetch is False
    assert settings.ingest_workers == 2
    assert settings.ingest_text_cache_enabled is True
    assert settings.export_json_enabled is False
    assert settings.transform_diagnostics_enabled is False


def test_load_settings_rejects_invalid_ingest_workers(monkeypatch, tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    monkeypatch.setenv(INPUT_PATH_ENV, str(raw_dir))
    monkeypatch.setenv(PROCESSED_PATH_ENV, str(processed_dir))
    monkeypatch.setenv(INGEST_WORKERS_ENV, "0")

    try:
        load_settings_from_env()
    except ValueError as exc:
        assert ">= 1" in str(exc)
    else:
        raise AssertionError("Expected ValueError for ingest_workers < 1")


def test_artifact_constants_match_public_outputs_and_state_contract() -> None:
    assert PIPELINE_INGEST_DIRNAME == "ingest"
    assert PIPELINE_TRANSFORM_DIRNAME == "transform"
    assert PIPELINE_PLANNING_DIRNAME == "planning"
    assert PIPELINE_OUTPUTS_DIRNAME == "outputs"
    assert PIPELINE_STATE_DIRNAME == "state"
    assert TRANSFORM_TRANSACTIONS_FILENAME == "transform_transactions.parquet"
    assert TRANSFORM_TRANSACTIONS_CSV_FILENAME == "transform_transactions.csv"
    assert TRANSFORM_SUMMARY_FILENAME == "transform_run_summary.json"
    assert TRANSFORM_DASHBOARD_FILENAME == "transform_dashboard.html"
    assert TRANSFORM_TRANSACTIONS_JSON_FILENAME == "transform_transactions.json"
    assert INGEST_STAGED_TRANSACTIONS_FILENAME == "ingest_staged_transactions.parquet"
    assert TRANSFORM_COMPLETENESS_FILENAME == "transform_completeness_report.json"
    assert WORKFLOW_FX_CACHE_FILENAME == "workflow_fx_rates_history.parquet"
    assert WORKFLOW_REVIEW_STATE_FILENAME == "workflow_review_state.parquet"


def test_stage_root_helpers_and_legacy_artifact_fallbacks(tmp_path: Path) -> None:
    settings = cast(
        Settings,
        type(
            "SettingsStub",
            (),
            {
                "processed_path": tmp_path / "processed",
            },
        )(),
    )
    transform_path = transform_root_path(settings) / TRANSFORM_TRANSACTIONS_FILENAME
    ingest_path = ingest_root_path(settings) / INGEST_STAGED_TRANSACTIONS_FILENAME
    legacy_transform_path = settings.processed_path / "outputs" / TRANSFORM_TRANSACTIONS_FILENAME
    legacy_ingest_path = settings.processed_path / "state" / INGEST_STAGED_TRANSACTIONS_FILENAME
    legacy_transform_path.parent.mkdir(parents=True)
    legacy_ingest_path.parent.mkdir(parents=True)
    legacy_transform_path.write_text("legacy transform", encoding="utf-8")
    legacy_ingest_path.write_text("legacy ingest", encoding="utf-8")

    assert ingest_root_path(settings) == settings.processed_path / "ingest"
    assert transform_root_path(settings) == settings.processed_path / "transform"
    assert planning_root_path(settings) == settings.processed_path / "planning"
    assert resolve_transform_artifact_path(settings, transform_path) == legacy_transform_path
    assert resolve_ingest_artifact_path(settings, ingest_path) == legacy_ingest_path

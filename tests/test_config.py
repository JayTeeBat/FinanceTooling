from pathlib import Path

from finance_tooling.config import (
    BASE_CURRENCY_ENV,
    CATEGORY_OVERRIDES_PATH_ENV,
    CATEGORY_RULES_PATH_ENV,
    EXPORT_CSV_PATH_ENV,
    EXPORT_JSON_PATH_ENV,
    FX_AUTO_FETCH_ENV,
    FX_CACHE_PATH_ENV,
    HSBC_CSV_PATH_ENV,
    INPUT_PATH_ENV,
    MASTER_PARQUET_ENV,
    OUTPUT_PATH_ENV,
    PROCESSED_PATH_ENV,
    load_settings_from_env,
)


def test_load_settings_defaults_outputs_to_processed_dir(monkeypatch, tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    monkeypatch.setenv(INPUT_PATH_ENV, str(raw_dir))
    monkeypatch.setenv(PROCESSED_PATH_ENV, str(processed_dir))
    monkeypatch.delenv(OUTPUT_PATH_ENV, raising=False)
    monkeypatch.delenv(MASTER_PARQUET_ENV, raising=False)
    monkeypatch.delenv(EXPORT_CSV_PATH_ENV, raising=False)
    monkeypatch.delenv(EXPORT_JSON_PATH_ENV, raising=False)
    monkeypatch.delenv(FX_CACHE_PATH_ENV, raising=False)
    monkeypatch.delenv(FX_AUTO_FETCH_ENV, raising=False)
    monkeypatch.delenv(HSBC_CSV_PATH_ENV, raising=False)
    monkeypatch.delenv(CATEGORY_RULES_PATH_ENV, raising=False)
    monkeypatch.delenv(CATEGORY_OVERRIDES_PATH_ENV, raising=False)
    monkeypatch.delenv(BASE_CURRENCY_ENV, raising=False)

    settings = load_settings_from_env()

    assert settings.input_path == raw_dir.resolve()
    assert settings.output_path == (processed_dir / "finance_dashboard.html").resolve()
    assert settings.master_parquet_path == (processed_dir / "transactions_master.parquet").resolve()
    assert settings.export_csv_path == (processed_dir / "transactions_normalized.csv").resolve()
    assert settings.export_json_path == (processed_dir / "transactions_normalized.json").resolve()
    assert settings.summary_json_path == (processed_dir / "run_summary.json").resolve()
    assert settings.completeness_json_path == (processed_dir / "completeness_report.json").resolve()
    assert settings.fx_cache_path == (processed_dir / "fx_rates_history.parquet").resolve()
    assert settings.category_rules_path == (processed_dir / "category_rules.yaml").resolve()
    assert settings.category_overrides_path == (processed_dir / "category_overrides.yaml").resolve()
    assert settings.base_currency == "EUR"
    assert settings.fx_auto_fetch is True
    assert settings.hsbc_csv_path is None


def test_load_settings_honors_explicit_output_overrides(monkeypatch, tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    custom_dir = tmp_path / "custom_out"
    custom_dir.mkdir()

    monkeypatch.setenv(INPUT_PATH_ENV, str(raw_dir))
    monkeypatch.setenv(PROCESSED_PATH_ENV, str(processed_dir))
    monkeypatch.setenv(OUTPUT_PATH_ENV, str(custom_dir / "dash.html"))
    monkeypatch.setenv(MASTER_PARQUET_ENV, str(custom_dir / "master.parquet"))
    monkeypatch.setenv(EXPORT_CSV_PATH_ENV, str(custom_dir / "tx.csv"))
    monkeypatch.setenv(EXPORT_JSON_PATH_ENV, str(custom_dir / "tx.json"))
    monkeypatch.setenv(FX_CACHE_PATH_ENV, str(custom_dir / "fx.parquet"))
    monkeypatch.setenv(FX_AUTO_FETCH_ENV, "false")
    monkeypatch.setenv(HSBC_CSV_PATH_ENV, str(custom_dir / "hsbc.csv"))
    monkeypatch.setenv(CATEGORY_RULES_PATH_ENV, str(custom_dir / "category_rules.yaml"))
    monkeypatch.setenv(CATEGORY_OVERRIDES_PATH_ENV, str(custom_dir / "category_overrides.yaml"))
    monkeypatch.setenv(BASE_CURRENCY_ENV, "gbp")
    (custom_dir / "hsbc.csv").write_text("Date,Payee,Amount\n", encoding="utf-8")

    settings = load_settings_from_env()

    assert settings.output_path == (custom_dir / "dash.html").resolve()
    assert settings.master_parquet_path == (custom_dir / "master.parquet").resolve()
    assert settings.export_csv_path == (custom_dir / "tx.csv").resolve()
    assert settings.export_json_path == (custom_dir / "tx.json").resolve()
    assert settings.fx_cache_path == (custom_dir / "fx.parquet").resolve()
    assert settings.category_rules_path == (custom_dir / "category_rules.yaml").resolve()
    assert settings.category_overrides_path == (custom_dir / "category_overrides.yaml").resolve()
    assert settings.summary_json_path == (processed_dir / "run_summary.json").resolve()
    assert settings.completeness_json_path == (processed_dir / "completeness_report.json").resolve()
    assert settings.base_currency == "GBP"
    assert settings.fx_auto_fetch is False
    assert settings.hsbc_csv_path == (custom_dir / "hsbc.csv").resolve()


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
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(INPUT_PATH_ENV, raising=False)
    monkeypatch.delenv(PROCESSED_PATH_ENV, raising=False)
    monkeypatch.delenv(BASE_CURRENCY_ENV, raising=False)
    monkeypatch.delenv(FX_AUTO_FETCH_ENV, raising=False)

    settings = load_settings_from_env()

    assert settings.input_path == raw_dir.resolve()
    assert settings.summary_json_path == (processed_dir / "run_summary.json").resolve()
    assert settings.base_currency == "USD"
    assert settings.fx_auto_fetch is False

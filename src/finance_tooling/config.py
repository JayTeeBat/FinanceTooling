"""Configuration loading for finance tooling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

INPUT_PATH_ENV = "FINANCE_STATEMENTS_PATH"
OUTPUT_PATH_ENV = "FINANCE_DASHBOARD_PATH"
MASTER_PARQUET_ENV = "FINANCE_MASTER_PARQUET_PATH"
BASE_CURRENCY_ENV = "FINANCE_BASE_CURRENCY"
EXPORT_CSV_PATH_ENV = "FINANCE_EXPORT_CSV_PATH"
EXPORT_JSON_PATH_ENV = "FINANCE_EXPORT_JSON_PATH"
FX_CACHE_PATH_ENV = "FINANCE_FX_CACHE_PATH"
FX_AUTO_FETCH_ENV = "FINANCE_FX_AUTO_FETCH"

DEFAULT_INPUT_PATH = Path("/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data/raw")


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from environment variables."""

    input_path: Path
    output_path: Path
    master_parquet_path: Path
    export_csv_path: Path
    export_json_path: Path
    summary_json_path: Path
    completeness_json_path: Path
    base_currency: str
    fx_cache_path: Path
    fx_auto_fetch: bool


def _resolve_path_from_env(env_name: str) -> Path | None:
    raw_value = os.environ.get(env_name)
    if not raw_value:
        return None
    return Path(raw_value).expanduser().resolve()


def _parse_bool(raw_value: str | None, *, default: bool) -> bool:
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    raise ValueError(f"Invalid boolean value: {raw_value}")


def load_settings_from_env() -> Settings:
    """Load workflow settings from environment variables."""
    input_path = _resolve_path_from_env(INPUT_PATH_ENV) or DEFAULT_INPUT_PATH
    if not input_path.exists() or not input_path.is_dir():
        raise ValueError(f"Input path does not exist or is not a directory: {input_path}")

    output_path = _resolve_path_from_env(OUTPUT_PATH_ENV) or (input_path / "finance_dashboard.html")
    master_parquet_path = _resolve_path_from_env(MASTER_PARQUET_ENV) or (
        input_path / "transactions_master.parquet"
    )
    export_csv_path = _resolve_path_from_env(EXPORT_CSV_PATH_ENV) or (
        input_path / "transactions_normalized.csv"
    )
    export_json_path = _resolve_path_from_env(EXPORT_JSON_PATH_ENV) or (
        input_path / "transactions_normalized.json"
    )
    summary_json_path = input_path / "run_summary.json"
    completeness_json_path = input_path / "completeness_report.json"

    base_currency = os.environ.get(BASE_CURRENCY_ENV, "EUR").strip().upper() or "EUR"
    fx_cache_path = _resolve_path_from_env(FX_CACHE_PATH_ENV) or (
        input_path / "fx_rates_history.parquet"
    )
    fx_auto_fetch = _parse_bool(os.environ.get(FX_AUTO_FETCH_ENV), default=True)

    return Settings(
        input_path=input_path,
        output_path=output_path,
        master_parquet_path=master_parquet_path,
        export_csv_path=export_csv_path,
        export_json_path=export_json_path,
        summary_json_path=summary_json_path,
        completeness_json_path=completeness_json_path,
        base_currency=base_currency,
        fx_cache_path=fx_cache_path,
        fx_auto_fetch=fx_auto_fetch,
    )

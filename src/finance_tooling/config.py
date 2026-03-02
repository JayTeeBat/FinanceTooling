"""Configuration loading for finance tooling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

INPUT_PATH_ENV = "FINANCE_STATEMENTS_PATH"
PROCESSED_PATH_ENV = "FINANCE_PROCESSED_PATH"
OUTPUT_PATH_ENV = "FINANCE_DASHBOARD_PATH"
MASTER_PARQUET_ENV = "FINANCE_MASTER_PARQUET_PATH"
BASE_CURRENCY_ENV = "FINANCE_BASE_CURRENCY"
EXPORT_CSV_PATH_ENV = "FINANCE_EXPORT_CSV_PATH"
EXPORT_JSON_PATH_ENV = "FINANCE_EXPORT_JSON_PATH"
STAGED_TRANSACTIONS_PATH_ENV = "FINANCE_STAGED_TRANSACTIONS_PATH"
FX_CACHE_PATH_ENV = "FINANCE_FX_CACHE_PATH"
FX_AUTO_FETCH_ENV = "FINANCE_FX_AUTO_FETCH"
INGEST_WORKERS_ENV = "FINANCE_INGEST_WORKERS"
INGEST_TEXT_CACHE_ENABLED_ENV = "FINANCE_INGEST_TEXT_CACHE_ENABLED"
INGEST_TEXT_CACHE_PATH_ENV = "FINANCE_INGEST_TEXT_CACHE_PATH"
CATEGORY_RULES_PATH_ENV = "FINANCE_CATEGORY_RULES_PATH"
CATEGORY_OVERRIDES_PATH_ENV = "FINANCE_CATEGORY_OVERRIDES_PATH"
DOTENV_PATH = Path(".env")


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from environment variables."""

    input_path: Path
    output_path: Path
    master_parquet_path: Path
    export_csv_path: Path
    export_json_path: Path
    staged_transactions_path: Path
    summary_json_path: Path
    completeness_json_path: Path
    base_currency: str
    fx_cache_path: Path
    fx_auto_fetch: bool
    ingest_workers: int
    ingest_text_cache_enabled: bool
    ingest_text_cache_path: Path
    category_rules_path: Path
    category_overrides_path: Path


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


def _parse_int(raw_value: str | None, *, default: int, minimum: int) -> int:
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid integer value: {raw_value}") from exc
    if parsed < minimum:
        raise ValueError(f"Value must be >= {minimum}: {raw_value}")
    return parsed


def _load_dotenv(path: Path = DOTENV_PATH) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_settings_from_env() -> Settings:
    """Load workflow settings from environment variables."""
    _load_dotenv()
    input_path = _resolve_path_from_env(INPUT_PATH_ENV)
    if input_path is None:
        raise ValueError(f"Missing required environment variable: {INPUT_PATH_ENV}")
    if not input_path.exists() or not input_path.is_dir():
        raise ValueError(f"Input path does not exist or is not a directory: {input_path}")

    processed_dir = _resolve_path_from_env(PROCESSED_PATH_ENV)
    if processed_dir is None:
        raise ValueError(f"Missing required environment variable: {PROCESSED_PATH_ENV}")
    output_path = _resolve_path_from_env(OUTPUT_PATH_ENV) or (
        processed_dir / "finance_dashboard.html"
    )
    master_parquet_path = _resolve_path_from_env(MASTER_PARQUET_ENV) or (
        processed_dir / "transactions_master.parquet"
    )
    export_csv_path = _resolve_path_from_env(EXPORT_CSV_PATH_ENV) or (
        processed_dir / "transactions_normalized.csv"
    )
    export_json_path = _resolve_path_from_env(EXPORT_JSON_PATH_ENV) or (
        processed_dir / "transactions_normalized.json"
    )
    staged_transactions_path = _resolve_path_from_env(STAGED_TRANSACTIONS_PATH_ENV) or (
        processed_dir / "staged_transactions.parquet"
    )
    summary_json_path = processed_dir / "run_summary.json"
    completeness_json_path = processed_dir / "completeness_report.json"

    base_currency = os.environ.get(BASE_CURRENCY_ENV, "EUR").strip().upper() or "EUR"
    fx_cache_path = _resolve_path_from_env(FX_CACHE_PATH_ENV) or (
        processed_dir / "fx_rates_history.parquet"
    )
    fx_auto_fetch = _parse_bool(os.environ.get(FX_AUTO_FETCH_ENV), default=True)
    ingest_workers = _parse_int(os.environ.get(INGEST_WORKERS_ENV), default=1, minimum=1)
    ingest_text_cache_enabled = _parse_bool(
        os.environ.get(INGEST_TEXT_CACHE_ENABLED_ENV),
        default=False,
    )
    ingest_text_cache_path = _resolve_path_from_env(INGEST_TEXT_CACHE_PATH_ENV) or (
        input_path.parent / "cache" / "ingest_text_cache.parquet"
    )
    category_rules_path = _resolve_path_from_env(CATEGORY_RULES_PATH_ENV) or (
        processed_dir / "category_rules.yaml"
    )
    category_overrides_path = _resolve_path_from_env(CATEGORY_OVERRIDES_PATH_ENV) or (
        processed_dir / "category_overrides.yaml"
    )

    return Settings(
        input_path=input_path,
        output_path=output_path,
        master_parquet_path=master_parquet_path,
        export_csv_path=export_csv_path,
        export_json_path=export_json_path,
        staged_transactions_path=staged_transactions_path,
        summary_json_path=summary_json_path,
        completeness_json_path=completeness_json_path,
        base_currency=base_currency,
        fx_cache_path=fx_cache_path,
        fx_auto_fetch=fx_auto_fetch,
        ingest_workers=ingest_workers,
        ingest_text_cache_enabled=ingest_text_cache_enabled,
        ingest_text_cache_path=ingest_text_cache_path,
        category_rules_path=category_rules_path,
        category_overrides_path=category_overrides_path,
    )

"""Configuration loading for finance tooling."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

INPUT_PATH_ENV = "FINANCE_STATEMENTS_PATH"
OUTPUT_PATH_ENV = "FINANCE_DASHBOARD_PATH"
MASTER_PARQUET_ENV = "FINANCE_MASTER_PARQUET_PATH"
BASE_CURRENCY_ENV = "FINANCE_BASE_CURRENCY"
FX_RATES_PATH_ENV = "FINANCE_FX_RATES_PATH"
EXPORT_CSV_PATH_ENV = "FINANCE_EXPORT_CSV_PATH"
EXPORT_JSON_PATH_ENV = "FINANCE_EXPORT_JSON_PATH"

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
    base_currency: str
    fx_rates: dict[str, Decimal]


def _parse_decimal(value: object, context: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value for {context}: {value}") from exc


def _load_fx_rates(path: Path | None, base_currency: str) -> dict[str, Decimal]:
    rates: dict[str, Decimal] = {base_currency: Decimal("1")}
    if path is None:
        return rates

    if not path.exists() or not path.is_file():
        raise ValueError(f"FX rates file does not exist: {path}")

    raw = path.read_text(encoding="utf-8").strip()
    parsed: dict[str, object]

    if path.suffix.lower() == ".json":
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in FX rates file: {path}") from exc
        if not isinstance(obj, dict):
            raise ValueError("FX rates JSON must be an object map of currency to rate")
        parsed = obj
    else:
        parsed = {}
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                raise ValueError(f"Invalid FX rates line: {stripped}")
            key, value = stripped.split(":", maxsplit=1)
            parsed[key.strip()] = value.strip()

    for currency, rate in parsed.items():
        code = str(currency).upper()
        rates[code] = _parse_decimal(rate, f"FX rate {code}")

    return rates


def _resolve_path_from_env(env_name: str) -> Path | None:
    raw_value = os.environ.get(env_name)
    if not raw_value:
        return None
    return Path(raw_value).expanduser().resolve()


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

    base_currency = os.environ.get(BASE_CURRENCY_ENV, "EUR").strip().upper() or "EUR"
    fx_rates_path = _resolve_path_from_env(FX_RATES_PATH_ENV)
    fx_rates = _load_fx_rates(fx_rates_path, base_currency)

    return Settings(
        input_path=input_path,
        output_path=output_path,
        master_parquet_path=master_parquet_path,
        export_csv_path=export_csv_path,
        export_json_path=export_json_path,
        summary_json_path=summary_json_path,
        base_currency=base_currency,
        fx_rates=fx_rates,
    )

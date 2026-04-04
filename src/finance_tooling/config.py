"""Configuration loading for finance tooling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

INPUT_PATH_ENV = "FINANCE_STATEMENTS_PATH"
PROCESSED_PATH_ENV = "FINANCE_PROCESSED_PATH"
# Supported advanced override for the primary dashboard output.
OUTPUT_PATH_ENV = "FINANCE_DASHBOARD_PATH"
# Supported advanced override for the canonical parquet output.
MASTER_PARQUET_ENV = "FINANCE_MASTER_PARQUET_PATH"
# Supported advanced runtime knob.
BASE_CURRENCY_ENV = "FINANCE_BASE_CURRENCY"
# Supported advanced override for the canonical CSV export.
EXPORT_CSV_PATH_ENV = "FINANCE_EXPORT_CSV_PATH"
# Compatibility override for an optional JSON export; not part of the primary output contract.
EXPORT_JSON_PATH_ENV = "FINANCE_EXPORT_JSON_PATH"
EXPORT_JSON_ENABLED_ENV = "FINANCE_EXPORT_JSON_ENABLED"
# Compatibility override for low-level stage wiring; most users should rely on defaults.
STAGED_TRANSACTIONS_PATH_ENV = "FINANCE_STAGED_TRANSACTIONS_PATH"
FX_CACHE_PATH_ENV = "FINANCE_FX_CACHE_PATH"
FX_AUTO_FETCH_ENV = "FINANCE_FX_AUTO_FETCH"
TRANSFORM_DIAGNOSTICS_ENABLED_ENV = "FINANCE_TRANSFORM_DIAGNOSTICS_ENABLED"
# Supported advanced runtime knob.
INGEST_WORKERS_ENV = "FINANCE_INGEST_WORKERS"
INGEST_TEXT_CACHE_ENABLED_ENV = "FINANCE_INGEST_TEXT_CACHE_ENABLED"
INGEST_TEXT_CACHE_PATH_ENV = "FINANCE_INGEST_TEXT_CACHE_PATH"
# Supported advanced config overrides for the workflow contract.
CATEGORY_RULES_PATH_ENV = "FINANCE_CATEGORY_RULES_PATH"
PROJECT_RULES_PATH_ENV = "FINANCE_PROJECT_RULES_PATH"
BUDGET_TARGETS_PATH_ENV = "FINANCE_BUDGET_TARGETS_PATH"
PROJECT_OVERRIDES_PATH_ENV = "FINANCE_PROJECT_OVERRIDES_PATH"
TRANSACTION_OVERRIDES_PATH_ENV = "FINANCE_TRANSACTION_OVERRIDES_PATH"
REVIEW_STATE_PATH_ENV = "FINANCE_REVIEW_STATE_PATH"
REVIEW_EXPORT_DARK_SAFE_ENV = "FINANCE_REVIEW_EXPORT_DARK_SAFE"
DOTENV_PATH = Path(".env")
PIPELINE_OUTPUTS_DIRNAME = "outputs"
PIPELINE_STATE_DIRNAME = "state"

# Optional diagnostics/state artifacts.
INGEST_SUMMARY_FILENAME = "ingest_summary.json"
INGEST_STAGED_TRANSACTIONS_FILENAME = "ingest_staged_transactions.parquet"
LEGACY_STAGED_TRANSACTIONS_FILENAME = "staged_transactions.parquet"
INGEST_TEXT_CACHE_FILENAME = "ingest_text_cache.parquet"

# Canonical operator-facing transform outputs.
TRANSFORM_TRANSACTIONS_FILENAME = "transform_transactions.parquet"
TRANSFORM_TRANSACTIONS_CSV_FILENAME = "transform_transactions.csv"

# Compatibility-only optional export. Keep supported, but do not treat as canonical.
TRANSFORM_TRANSACTIONS_JSON_FILENAME = "transform_transactions.json"
TRANSFORM_SUMMARY_FILENAME = "transform_run_summary.json"

# Diagnostics and internal workflow state.
TRANSFORM_COMPLETENESS_FILENAME = "transform_completeness_report.json"
TRANSFORM_DASHBOARD_FILENAME = "transform_dashboard.html"
HOUSEHOLD_HEALTHCHECK_FILENAME = "household_healthcheck.html"
TRANSFORM_SOURCE_REGISTRY_FILENAME = "transform_source_registry.json"
WORKFLOW_REVIEW_STATE_FILENAME = "workflow_review_state.parquet"
WORKFLOW_FX_CACHE_FILENAME = "workflow_fx_rates_history.parquet"


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from environment variables.

    The primary public contract for operators is the workflow CLI plus stable
    files under ``processed/outputs`` and ``processed/state``. Some settings
    fields remain configurable for compatibility or advanced workflows even
    when they are not part of the minimal day-to-day interface.
    """

    input_path: Path
    processed_path: Path
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
    project_rules_path: Path
    budget_targets_path: Path
    project_overrides_path: Path
    transaction_overrides_path: Path
    review_state_path: Path
    review_export_dark_safe: bool
    export_json_enabled: bool = False
    transform_diagnostics_enabled: bool = False


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


def _processed_root_from_settings(settings: Settings) -> Path:
    """Resolve the processed root, tolerating lightweight test doubles."""
    processed_path = getattr(settings, "processed_path", None)
    if processed_path is not None:
        return Path(processed_path)

    for attr in (
        "output_path",
        "master_parquet_path",
        "export_csv_path",
        "export_json_path",
        "summary_json_path",
        "completeness_json_path",
        "review_state_path",
        "fx_cache_path",
        "ingest_text_cache_path",
    ):
        value = getattr(settings, attr, None)
        if value is not None:
            path = Path(value)
            if len(path.parents) >= 2:
                return path.parent.parent
            return path.parent

    raise AttributeError("settings must define processed_path or a derived processed-path field")


def outputs_root_path(settings: Settings) -> Path:
    """Return the root directory for stable operator-facing outputs."""
    return _processed_root_from_settings(settings) / PIPELINE_OUTPUTS_DIRNAME


def state_root_path(settings: Settings) -> Path:
    """Return the root directory for internal state and diagnostics."""
    return _processed_root_from_settings(settings) / PIPELINE_STATE_DIRNAME


def ingest_state_path(settings: Settings) -> Path:
    """Return the ingest-owned state directory under ``processed/state``."""
    return state_root_path(settings)


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
    outputs_dir = processed_dir / PIPELINE_OUTPUTS_DIRNAME
    state_dir = processed_dir / PIPELINE_STATE_DIRNAME
    output_path = _resolve_path_from_env(OUTPUT_PATH_ENV) or (
        outputs_dir / TRANSFORM_DASHBOARD_FILENAME
    )
    master_parquet_path = _resolve_path_from_env(MASTER_PARQUET_ENV) or (
        outputs_dir / TRANSFORM_TRANSACTIONS_FILENAME
    )
    export_csv_path = _resolve_path_from_env(EXPORT_CSV_PATH_ENV) or (
        outputs_dir / TRANSFORM_TRANSACTIONS_CSV_FILENAME
    )
    export_json_path = _resolve_path_from_env(EXPORT_JSON_PATH_ENV) or (
        outputs_dir / TRANSFORM_TRANSACTIONS_JSON_FILENAME
    )
    export_json_enabled = _parse_bool(
        os.environ.get(EXPORT_JSON_ENABLED_ENV),
        default=False,
    )
    transform_diagnostics_enabled = _parse_bool(
        os.environ.get(TRANSFORM_DIAGNOSTICS_ENABLED_ENV),
        default=False,
    )
    staged_transactions_path = _resolve_path_from_env(STAGED_TRANSACTIONS_PATH_ENV) or (
        state_dir / INGEST_STAGED_TRANSACTIONS_FILENAME
    )
    summary_json_path = outputs_dir / TRANSFORM_SUMMARY_FILENAME
    completeness_json_path = state_dir / TRANSFORM_COMPLETENESS_FILENAME

    base_currency = os.environ.get(BASE_CURRENCY_ENV, "EUR").strip().upper() or "EUR"
    fx_cache_path = _resolve_path_from_env(FX_CACHE_PATH_ENV) or (
        state_dir / WORKFLOW_FX_CACHE_FILENAME
    )
    fx_auto_fetch = _parse_bool(os.environ.get(FX_AUTO_FETCH_ENV), default=True)
    ingest_workers = _parse_int(os.environ.get(INGEST_WORKERS_ENV), default=1, minimum=1)
    ingest_text_cache_enabled = _parse_bool(
        os.environ.get(INGEST_TEXT_CACHE_ENABLED_ENV),
        default=False,
    )
    ingest_text_cache_path = _resolve_path_from_env(INGEST_TEXT_CACHE_PATH_ENV) or (
        state_dir / INGEST_TEXT_CACHE_FILENAME
    )
    config_dir = input_path.parent / "config"
    category_rules_path = _resolve_path_from_env(CATEGORY_RULES_PATH_ENV) or (
        config_dir / "category_rules.yaml"
    )
    project_rules_path = _resolve_path_from_env(PROJECT_RULES_PATH_ENV) or (
        config_dir / "project_rules.yaml"
    )
    budget_targets_path = _resolve_path_from_env(BUDGET_TARGETS_PATH_ENV) or (
        config_dir / "budget_targets.yaml"
    )
    project_overrides_path = _resolve_path_from_env(PROJECT_OVERRIDES_PATH_ENV) or (
        config_dir / "project_overrides.yaml"
    )
    transaction_overrides_path = _resolve_path_from_env(TRANSACTION_OVERRIDES_PATH_ENV) or (
        config_dir / "transaction_overrides.yaml"
    )
    review_state_path = _resolve_path_from_env(REVIEW_STATE_PATH_ENV) or (
        state_dir / WORKFLOW_REVIEW_STATE_FILENAME
    )
    review_export_dark_safe = _parse_bool(
        os.environ.get(REVIEW_EXPORT_DARK_SAFE_ENV),
        default=True,
    )

    return Settings(
        input_path=input_path,
        processed_path=processed_dir,
        output_path=output_path,
        master_parquet_path=master_parquet_path,
        export_csv_path=export_csv_path,
        export_json_path=export_json_path,
        export_json_enabled=export_json_enabled,
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
        project_rules_path=project_rules_path,
        budget_targets_path=budget_targets_path,
        project_overrides_path=project_overrides_path,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=review_state_path,
        review_export_dark_safe=review_export_dark_safe,
        transform_diagnostics_enabled=transform_diagnostics_enabled,
    )

"""Classification and FX enrichment stage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from finance_tooling.categorization.account_inference import load_account_inference_config
from finance_tooling.categorization.classify import (
    build_classification_diagnostics,
    classify_transactions_with_diagnostics,
    load_classification_rules,
)
from finance_tooling.categorization.projecting import (
    assign_projects_to_transactions,
    load_project_config,
)
from finance_tooling.categorization.transaction_overrides import (
    apply_transaction_overrides,
    load_transaction_override_store,
)
from finance_tooling.core.config import Settings
from finance_tooling.core.fx import build_fx_lookup_index, ensure_fx_cache, resolve_rate_from_index
from finance_tooling.core.models import Transaction
from finance_tooling.workflow.category_carry_forward import apply_manual_category_carry_forward
from finance_tooling.workflow.types import EnrichmentResult


def apply_fx_and_mtime(
    transactions: list[Transaction], settings: Settings
) -> tuple[list[Transaction], list[str]]:
    """Apply FX conversion and source file mtime enrichment."""
    enriched: list[Transaction] = []
    warnings: list[str] = []

    cache, cache_warnings = ensure_fx_cache(
        settings.fx_cache_path,
        transactions,
        base_currency=settings.base_currency,
        auto_fetch=settings.fx_auto_fetch,
    )
    warnings.extend(cache_warnings)
    fx_lookup_index = build_fx_lookup_index(cache)
    source_file_mtimes: dict[Path, datetime] = {}

    for tx in transactions:
        currency = tx.currency.upper()
        amount_eur: Decimal | None = None
        fx_rate: Decimal | None = None
        fx_rate_date = None
        fx_source = None

        resolution = resolve_rate_from_index(
            fx_lookup_index,
            currency=currency,
            booking_date=tx.booking_date,
            base_currency=settings.base_currency,
        )
        if resolution is None:
            warnings.append(
                "Missing dated FX rate for currency "
                f"{currency} on or before {tx.booking_date} ({tx.source_file.name}); "
                "converted metrics will skip this row"
            )
        else:
            fx_rate = resolution.rate_to_eur
            fx_rate_date = resolution.rate_date
            fx_source = resolution.source
            amount_eur = tx.amount_native * resolution.rate_to_eur

        mtime = source_file_mtimes.get(tx.source_file)
        if mtime is None:
            mtime = datetime.fromtimestamp(tx.source_file.stat().st_mtime, tz=UTC)
            source_file_mtimes[tx.source_file] = mtime
        enriched.append(
            replace(
                tx,
                currency=currency,
                fx_rate_to_eur=fx_rate,
                fx_rate_date=fx_rate_date,
                fx_source=fx_source,
                amount_eur=amount_eur,
                source_file_mtime=mtime,
            )
        )

    return enriched, warnings


def recompute_dataframe_fx(
    dataframe: pd.DataFrame,
    settings: Settings,
) -> tuple[pd.DataFrame, list[str]]:
    """Recompute FX-derived canonical fields for the full merged dataframe."""
    if dataframe.empty:
        return dataframe.copy(), []

    seed_transactions: list[Transaction] = []
    for row in dataframe.to_dict(orient="records"):
        booking_value = row.get("booking_date")
        if not isinstance(booking_value, str | date | datetime | pd.Timestamp):
            continue
        booking_ts = pd.to_datetime(booking_value, errors="coerce")
        if pd.isna(booking_ts):
            continue
        currency = str(row.get("currency") or settings.base_currency).strip().upper()
        seed_transactions.append(
            Transaction(
                booking_date=booking_ts.date(),
                description=str(row.get("description") or ""),
                amount_native=Decimal(str(row.get("amount_native") or "0")),
                currency=currency,
                source_file=Path(str(row.get("source_file") or "unknown")),
                bank=str(row.get("bank") or "UNKNOWN"),
                parser=str(row.get("parser") or "unknown"),
            )
        )

    cache, warnings = ensure_fx_cache(
        settings.fx_cache_path,
        seed_transactions,
        base_currency=settings.base_currency,
        auto_fetch=settings.fx_auto_fetch,
    )
    fx_lookup_index = build_fx_lookup_index(cache)

    recomputed = dataframe.copy()
    fx_rates: list[float | None] = []
    fx_rate_dates: list[str | None] = []
    fx_sources: list[str | None] = []
    amounts_eur: list[float | None] = []

    for row in recomputed.to_dict(orient="records"):
        booking_value = row.get("booking_date")
        if not isinstance(booking_value, str | date | datetime | pd.Timestamp):
            fx_rates.append(None)
            fx_rate_dates.append(None)
            fx_sources.append(None)
            amounts_eur.append(None)
            continue
        booking_ts = pd.to_datetime(booking_value, errors="coerce")
        currency = str(row.get("currency") or settings.base_currency).strip().upper()
        amount_native = Decimal(str(row.get("amount_native") or "0"))
        if pd.isna(booking_ts):
            fx_rates.append(None)
            fx_rate_dates.append(None)
            fx_sources.append(None)
            amounts_eur.append(None)
            continue

        resolution = resolve_rate_from_index(
            fx_lookup_index,
            currency=currency,
            booking_date=booking_ts.date(),
            base_currency=settings.base_currency,
        )
        if resolution is None:
            warnings.append(
                "Missing dated FX rate for currency "
                f"{currency} on or before {booking_ts.date()} "
                f"({Path(str(row.get('source_file') or 'unknown')).name}); "
                "converted metrics will skip this row"
            )
            fx_rates.append(None)
            fx_rate_dates.append(None)
            fx_sources.append(None)
            amounts_eur.append(None)
            continue

        fx_rates.append(float(resolution.rate_to_eur))
        fx_rate_dates.append(resolution.rate_date.isoformat())
        fx_sources.append(resolution.source)
        amounts_eur.append(float(amount_native * resolution.rate_to_eur))

    recomputed["currency"] = (
        recomputed.get("currency", pd.Series(settings.base_currency, index=recomputed.index))
        .astype("string")
        .fillna(settings.base_currency)
        .str.strip()
        .str.upper()
        .astype(object)
    )
    recomputed["fx_rate_to_eur"] = fx_rates
    recomputed["fx_rate_date"] = fx_rate_dates
    recomputed["fx_source"] = fx_sources
    recomputed["amount_eur"] = amounts_eur
    return recomputed, warnings


def enrich_transactions(transactions: list[Transaction], settings: Settings) -> EnrichmentResult:
    """Run classification and FX enrichment stage."""
    warnings: list[str] = []

    category_rules, category_rule_warnings = load_classification_rules(settings.category_rules_path)
    project_config, project_warnings = load_project_config(settings.project_overrides_path)
    transaction_overrides, transaction_override_warnings = load_transaction_override_store(
        settings.transaction_overrides_path
    )
    account_inference_config, account_inference_warnings = load_account_inference_config(
        settings.account_rules_path
    )
    warnings.extend(category_rule_warnings)
    warnings.extend(project_warnings)
    warnings.extend(transaction_override_warnings)
    warnings.extend(account_inference_warnings)

    classified, _classification_diagnostics = classify_transactions_with_diagnostics(
        transactions,
        rules=category_rules,
    )
    projected = assign_projects_to_transactions(classified, project_config)
    overridden = apply_transaction_overrides(
        projected,
        transaction_overrides,
        classification_rules=category_rules,
    )
    carry_forward = apply_manual_category_carry_forward(
        overridden,
        master_parquet_path=settings.master_parquet_path,
    )
    warnings.extend(carry_forward.warnings)
    classification_diagnostics = build_classification_diagnostics(carry_forward.transactions)

    enriched, fx_warnings = apply_fx_and_mtime(carry_forward.transactions, settings)
    warnings.extend(fx_warnings)

    return EnrichmentResult(
        transactions=enriched,
        warnings=warnings,
        classification_diagnostics=classification_diagnostics,
        classification_rules=category_rules,
        transaction_override_store=transaction_overrides,
        account_inference_config=account_inference_config,
        account_inference_warnings=account_inference_warnings,
        manual_category_carry_forward_applied_count=carry_forward.diagnostics.applied_count,
        manual_category_carry_forward_ambiguous_skipped_count=(
            carry_forward.diagnostics.ambiguous_skipped_count
        ),
        manual_category_carry_forward_unmatched_count=carry_forward.diagnostics.unmatched_count,
    )

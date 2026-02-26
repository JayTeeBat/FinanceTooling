"""Classification and FX enrichment stage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from finance_tooling.classify import (
    classify_transactions_with_diagnostics,
    load_classification_rules,
    load_override_store,
)
from finance_tooling.config import Settings
from finance_tooling.fx import ensure_fx_cache, resolve_rate
from finance_tooling.models import Transaction
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

    for tx in transactions:
        currency = tx.currency.upper()
        amount_eur: Decimal | None = None
        fx_rate: Decimal | None = None
        fx_rate_date = None
        fx_source = None

        resolution = resolve_rate(
            cache,
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

        mtime = datetime.fromtimestamp(tx.source_file.stat().st_mtime, tz=UTC)
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


def enrich_transactions(transactions: list[Transaction], settings: Settings) -> EnrichmentResult:
    """Run classification and FX enrichment stage."""
    warnings: list[str] = []

    category_rules, category_rule_warnings = load_classification_rules(settings.category_rules_path)
    category_overrides, category_override_warnings = load_override_store(
        settings.category_overrides_path
    )
    warnings.extend(category_rule_warnings)
    warnings.extend(category_override_warnings)

    classified, classification_diagnostics = classify_transactions_with_diagnostics(
        transactions,
        rules=category_rules,
        overrides=category_overrides,
    )

    enriched, fx_warnings = apply_fx_and_mtime(classified, settings)
    warnings.extend(fx_warnings)

    return EnrichmentResult(
        transactions=enriched,
        warnings=warnings,
        classification_diagnostics=classification_diagnostics,
    )

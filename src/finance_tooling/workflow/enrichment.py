"""Classification and FX enrichment stage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from finance_tooling.classify import (
    build_classification_diagnostics,
    classify_transactions_with_diagnostics,
    load_classification_rules,
)
from finance_tooling.config import Settings
from finance_tooling.fx import build_fx_lookup_index, ensure_fx_cache, resolve_rate_from_index
from finance_tooling.models import Transaction
from finance_tooling.projecting import assign_projects_to_transactions, load_project_config
from finance_tooling.transaction_overrides import (
    apply_transaction_overrides,
    load_transaction_override_store,
)
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


def enrich_transactions(transactions: list[Transaction], settings: Settings) -> EnrichmentResult:
    """Run classification and FX enrichment stage."""
    warnings: list[str] = []

    category_rules, category_rule_warnings = load_classification_rules(settings.category_rules_path)
    project_config, project_warnings = load_project_config(settings.project_overrides_path)
    transaction_overrides, transaction_override_warnings = load_transaction_override_store(
        settings.transaction_overrides_path
    )
    warnings.extend(category_rule_warnings)
    warnings.extend(project_warnings)
    warnings.extend(transaction_override_warnings)

    classified, _classification_diagnostics = classify_transactions_with_diagnostics(
        transactions,
        rules=category_rules,
    )
    projected = assign_projects_to_transactions(classified, project_config)
    overridden = apply_transaction_overrides(projected, transaction_overrides)
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
        manual_category_carry_forward_applied_count=carry_forward.diagnostics.applied_count,
        manual_category_carry_forward_ambiguous_skipped_count=(
            carry_forward.diagnostics.ambiguous_skipped_count
        ),
        manual_category_carry_forward_unmatched_count=carry_forward.diagnostics.unmatched_count,
    )

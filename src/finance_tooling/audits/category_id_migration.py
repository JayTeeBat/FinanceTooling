"""Dry-run audit for migrating the live corpus to durable category IDs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pandas as pd

from finance_tooling.categorization.classify import (
    ClassificationRules,
    _taxonomy_entries_by_id,
    load_classification_rules,
    resolve_category_id_from_labels,
    resolve_reporting_category_id,
    resolve_taxonomy_labels,
)
from finance_tooling.categorization.transaction_overrides import (
    TransactionOverrideEntry,
    TransactionOverrideStore,
    load_transaction_override_store,
)
from finance_tooling.core.config import Settings, load_settings_from_env, outputs_root_path

_AUDIT_FILENAME = "category_id_migration_audit.md"

_LEGACY_LABEL_PAIR_ALIASES: dict[tuple[str, str | None], str] = {
    ("admin", "government fees"): "taxes.government_fees",
    ("cash", "cash withdrawal"): "transfers.cash_withdrawal",
    ("fees", "bank"): "financial.bank_fees",
    ("groceries", "general retail"): "groceries.other_groceries",
    ("groceries", "other"): "groceries.other_groceries",
    ("healthcare", None): "health.other_health",
    ("healthcare", "health insurance"): "insurance.health",
    ("healthcare", "healthcare"): "health.medical_care",
    ("healthcare", "non standard healthcare"): "health.other_health",
    ("house", "cleaning"): "housing.home_services",
    ("house", "mortgage"): "housing.mortgage",
    ("housing", "house improvements"): "housing.home_maintenance",
    ("income", "general retail"): "income.other_income",
    ("insurance", "life insurance"): "insurance.life_disability",
    ("leisure", "accomodation"): "travel.accommodation",
    ("leisure", "activities"): "leisure.other_leisure",
    ("leisure", "dining out"): "dining.dining_out",
    ("leisure", "holiday"): "travel.other_travel",
    ("memberships", "memberships"): "leisure.other_leisure",
    ("mobility", "car"): "transport.vehicle_ownership",
    ("non personal transactions", "apel"): "excluded.non_personal",
    ("non personal transactions", "work"): "excluded.non_personal",
    ("other", "loan"): "financial.debt_service",
    ("shopping", "clothing"): "shopping.apparel",
    ("taxes", "allocations familiales"): "income.benefits",
    ("taxes", "taxes"): "taxes.other_taxes",
    ("travel", "accomodation"): "travel.accommodation",
    ("transfers", "savings"): "transfers.savings_transfer",
    ("transport", "car"): "transport.vehicle_ownership",
    ("transport", "train"): "transport.public_transport",
    ("retirement", "pension contribution"): "financial.retirement_contribution",
    ("work", "expenses"): "excluded.business",
}

_LEGACY_CATEGORY_FALLBACKS: dict[str, str] = {
    "family": "family.other_family",
    "giving": "giving.other_giving",
    "groceries": "groceries.other_groceries",
    "healthcare": "health.other_health",
    "housing": "housing.other_housing",
    "income": "income.other_income",
    "leisure": "leisure.other_leisure",
    "shopping": "shopping.other_shopping",
    "taxes": "taxes.other_taxes",
    "transfers": "transfers.bank_transfer",
    "transport": "transport.other_transport",
    "utilities": "utilities.other_utilities",
}


@dataclass(frozen=True)
class MigrationAuditRow:
    """Single unresolved/interesting row for reporting."""

    kind: str
    identifier: str
    current_category_id: str | None
    category: str | None
    subcategory: str | None
    detail: str


@dataclass(frozen=True)
class CategoryIdMigrationAudit:
    """Dry-run audit payload for category-id migration readiness."""

    canonical_summary: dict[str, object]
    override_summary: dict[str, object]
    taxonomy_summary: dict[str, object]
    unresolved_rows: list[MigrationAuditRow]


def _string_series(
    dataframe: pd.DataFrame,
    column: str,
    *,
    default: str = "",
) -> pd.Series:
    series = dataframe.get(
        column,
        pd.Series(default, index=dataframe.index, dtype="object"),
    )
    return series.astype("string").fillna(default)


def _entry_exists(
    category_id: str | None,
    *,
    rules: ClassificationRules,
) -> bool:
    if category_id is None:
        return False
    category, _subcategory = resolve_taxonomy_labels(category_id, rules=rules)
    return category is not None


def _label_pair_index(rules: ClassificationRules) -> dict[tuple[str, str | None], list[str]]:
    index: dict[tuple[str, str | None], list[str]] = {}
    for category_id, entry in _taxonomy_entries_by_id(rules).items():
        category_label = (entry.category_label or entry.name).strip()
        if not category_label:
            continue
        subcategory_label = entry.subcategory_label.strip() if entry.subcategory_label else None
        key = (
            category_label.casefold(),
            subcategory_label.casefold() if subcategory_label else None,
        )
        index.setdefault(key, []).append(category_id)
    return index


def _resolve_row_category_ids(
    *,
    current_category_id: str | None,
    category: str | None,
    subcategory: str | None,
    rules: ClassificationRules,
) -> tuple[str | None, str | None, str]:
    if current_category_id and _entry_exists(current_category_id, rules=rules):
        return (
            current_category_id,
            resolve_reporting_category_id(current_category_id, rules=rules),
            "existing_category_id",
        )

    category_key = (
        category.strip().casefold()
        if isinstance(category, str) and category.strip()
        else None
    )
    subcategory_key = (
        subcategory.strip().casefold()
        if isinstance(subcategory, str) and subcategory.strip()
        else None
    )

    resolved_category_id = resolve_category_id_from_labels(
        category,
        subcategory,
        rules=rules,
        prefer_active=False,
    )
    if not _entry_exists(resolved_category_id, rules=rules):
        alias_category_id = _LEGACY_LABEL_PAIR_ALIASES.get((category_key or "", subcategory_key))
        if alias_category_id and _entry_exists(alias_category_id, rules=rules):
            return (
                alias_category_id,
                resolve_reporting_category_id(alias_category_id, rules=rules),
                "legacy_alias",
            )

        if category_key is not None:
            family_fallback = _LEGACY_CATEGORY_FALLBACKS.get(category_key)
            if family_fallback and _entry_exists(family_fallback, rules=rules):
                return (
                    family_fallback,
                    resolve_reporting_category_id(family_fallback, rules=rules),
                    "family_fallback",
                )

        return None, None, "unresolved_labels"
    return (
        resolved_category_id,
        resolve_reporting_category_id(resolved_category_id, rules=rules),
        "labels",
    )


def _canonical_summary(
    canonical_transactions: pd.DataFrame,
    *,
    rules: ClassificationRules,
) -> tuple[dict[str, object], list[MigrationAuditRow]]:
    category_ids = _string_series(canonical_transactions, "category_id").str.strip()
    categories = _string_series(canonical_transactions, "category").str.strip()
    subcategories = _string_series(canonical_transactions, "subcategory").str.strip()
    transaction_ids = _string_series(canonical_transactions, "transaction_id").str.strip()

    rows_with_existing_category_id = 0
    rows_backfilled_from_labels = 0
    unresolved_rows: list[MigrationAuditRow] = []
    deprecated_rows = 0

    for index in canonical_transactions.index:
        current_category_id = category_ids.loc[index] or None
        category = categories.loc[index] or None
        subcategory = subcategories.loc[index] or None
        resolved_category_id, reporting_category_id, resolution_source = _resolve_row_category_ids(
            current_category_id=current_category_id,
            category=category,
            subcategory=subcategory,
            rules=rules,
        )
        if resolution_source == "existing_category_id":
            rows_with_existing_category_id += 1
        elif resolution_source in {"labels", "legacy_alias", "family_fallback"}:
            rows_backfilled_from_labels += 1
        else:
            unresolved_rows.append(
                MigrationAuditRow(
                    kind="canonical",
                    identifier=transaction_ids.loc[index] or f"row-{index}",
                    current_category_id=current_category_id,
                    category=category,
                    subcategory=subcategory,
                    detail="Current category/subcategory does not resolve to a taxonomy entry.",
                )
            )
            continue

        if (
            resolved_category_id
            and reporting_category_id
            and resolved_category_id != reporting_category_id
        ):
            deprecated_rows += 1

    return (
        {
            "total_rows": len(canonical_transactions),
            "rows_with_existing_category_id": rows_with_existing_category_id,
            "rows_backfilled_from_labels": rows_backfilled_from_labels,
            "unresolved_row_count": len(unresolved_rows),
            "deprecated_row_count": deprecated_rows,
        },
        unresolved_rows,
    )


def _override_identifier(entry: TransactionOverrideEntry, index: int) -> str:
    if entry.transaction_id:
        return entry.transaction_id
    if entry.override_id:
        return entry.override_id
    return f"override-{index}"


def _override_summary(
    override_store: TransactionOverrideStore,
    *,
    rules: ClassificationRules,
) -> tuple[dict[str, object], list[MigrationAuditRow]]:
    entries_with_existing_category_id = 0
    entries_backfilled_from_labels = 0
    unresolved_entries: list[MigrationAuditRow] = []
    deprecated_entries = 0
    category_entries = 0

    for index, entry in enumerate(override_store.entries):
        if not (
            entry.set_category_id
            or entry.set_category
            or entry.set_subcategory
        ):
            continue
        category_entries += 1
        resolved_category_id, reporting_category_id, resolution_source = _resolve_row_category_ids(
            current_category_id=entry.category_id if entry.set_category_id else None,
            category=entry.category if entry.set_category else None,
            subcategory=entry.subcategory if entry.set_subcategory else None,
            rules=rules,
        )
        if resolution_source == "existing_category_id":
            entries_with_existing_category_id += 1
        elif resolution_source in {"labels", "legacy_alias", "family_fallback"}:
            entries_backfilled_from_labels += 1
        else:
            unresolved_entries.append(
                MigrationAuditRow(
                    kind="override",
                    identifier=_override_identifier(entry, index),
                    current_category_id=entry.category_id if entry.set_category_id else None,
                    category=entry.category if entry.set_category else None,
                    subcategory=entry.subcategory if entry.set_subcategory else None,
                    detail="Override category fields do not resolve to a taxonomy entry.",
                )
            )
            continue

        if (
            resolved_category_id
            and reporting_category_id
            and resolved_category_id != reporting_category_id
        ):
            deprecated_entries += 1

    return (
        {
            "category_override_entries": category_entries,
            "entries_with_existing_category_id": entries_with_existing_category_id,
            "entries_backfilled_from_labels": entries_backfilled_from_labels,
            "unresolved_entry_count": len(unresolved_entries),
            "deprecated_entry_count": deprecated_entries,
        },
        unresolved_entries,
    )


def _taxonomy_summary(rules: ClassificationRules) -> dict[str, object]:
    entries = _taxonomy_entries_by_id(rules)
    label_index = _label_pair_index(rules)
    ambiguous_pairs = [
        {
            "category": category,
            "subcategory": subcategory,
            "category_ids": sorted(category_ids),
        }
        for (category, subcategory), category_ids in label_index.items()
        if len(category_ids) > 1
    ]
    ambiguous_pairs.sort(
        key=lambda item: (
            cast(str, item["category"]),
            cast(str | None, item["subcategory"]) or "",
        )
    )
    deprecated_ids = [
        category_id
        for category_id, entry in entries.items()
        if entry.deprecated_to is not None
    ]
    return {
        "taxonomy_entry_count": len(entries),
        "deprecated_id_count": len(deprecated_ids),
        "ambiguous_label_pair_count": len(ambiguous_pairs),
        "ambiguous_label_pairs": ambiguous_pairs[:20],
    }


def build_category_id_migration_audit(
    *,
    canonical_transactions: pd.DataFrame,
    classification_rules: ClassificationRules,
    transaction_override_store: TransactionOverrideStore,
) -> CategoryIdMigrationAudit:
    """Build the read-only category-id migration readiness audit."""
    canonical_summary, canonical_unresolved = _canonical_summary(
        canonical_transactions,
        rules=classification_rules,
    )
    override_summary, override_unresolved = _override_summary(
        transaction_override_store,
        rules=classification_rules,
    )
    taxonomy_summary = _taxonomy_summary(classification_rules)
    return CategoryIdMigrationAudit(
        canonical_summary=canonical_summary,
        override_summary=override_summary,
        taxonomy_summary=taxonomy_summary,
        unresolved_rows=[*canonical_unresolved, *override_unresolved],
    )


def _markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return "_None_"
    header_line = "| " + " | ".join(headers) + " |"
    divider_line = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join(
        "| " + " | ".join(str(value) for value in row) + " |" for row in rows
    )
    return "\n".join([header_line, divider_line, body])


def render_category_id_migration_audit_markdown(audit: CategoryIdMigrationAudit) -> str:
    """Render a human-readable migration readiness report."""
    unresolved_rows = [
        [
            row.kind,
            row.identifier,
            row.current_category_id or "",
            row.category or "",
            row.subcategory or "",
            row.detail,
        ]
        for row in audit.unresolved_rows[:50]
    ]
    ambiguous_rows = [
        [
            row["category"],
            row["subcategory"] or "",
            ", ".join(cast(list[str], row["category_ids"])),
        ]
        for row in cast(list[dict[str, object]], audit.taxonomy_summary["ambiguous_label_pairs"])
    ]
    return "\n".join(
        [
            "# Category ID Migration Audit",
            "",
            "## Canonical Summary",
            f"- Total canonical rows: {audit.canonical_summary['total_rows']}",
            (
                "- Rows already carrying valid `category_id`: "
                f"{audit.canonical_summary['rows_with_existing_category_id']}"
            ),
            (
                "- Rows backfillable from current labels: "
                f"{audit.canonical_summary['rows_backfilled_from_labels']}"
            ),
            (
                "- Rows resolving through deprecated IDs: "
                f"{audit.canonical_summary['deprecated_row_count']}"
            ),
            (
                "- Unresolved canonical rows: "
                f"{audit.canonical_summary['unresolved_row_count']}"
            ),
            "",
            "## Override Summary",
            (
                "- Category-bearing override entries: "
                f"{audit.override_summary['category_override_entries']}"
            ),
            (
                "- Override entries already carrying valid `category_id`: "
                f"{audit.override_summary['entries_with_existing_category_id']}"
            ),
            (
                "- Override entries backfillable from labels: "
                f"{audit.override_summary['entries_backfilled_from_labels']}"
            ),
            (
                "- Override entries resolving through deprecated IDs: "
                f"{audit.override_summary['deprecated_entry_count']}"
            ),
            (
                "- Unresolved override entries: "
                f"{audit.override_summary['unresolved_entry_count']}"
            ),
            "",
            "## Taxonomy Summary",
            (
                "- Taxonomy entries (including deprecated): "
                f"{audit.taxonomy_summary['taxonomy_entry_count']}"
            ),
            (
                "- Deprecated IDs: "
                f"{audit.taxonomy_summary['deprecated_id_count']}"
            ),
            (
                "- Ambiguous label pairs: "
                f"{audit.taxonomy_summary['ambiguous_label_pair_count']}"
            ),
            "",
            _markdown_table(["Category", "Subcategory", "Category IDs"], ambiguous_rows),
            "",
            "## Unresolved Rows",
            _markdown_table(
                ["Kind", "Identifier", "Current ID", "Category", "Subcategory", "Detail"],
                unresolved_rows,
            ),
            "",
        ]
    )


def run_category_id_migration_audit(settings: Settings) -> Path:
    """Run the live category-id migration audit and write a Markdown report."""
    canonical_transactions = pd.read_parquet(settings.master_parquet_path)
    classification_rules, rule_warnings = load_classification_rules(
        settings.category_rules_path
    )
    transaction_override_store, override_warnings = load_transaction_override_store(
        settings.transaction_overrides_path
    )

    audit = build_category_id_migration_audit(
        canonical_transactions=canonical_transactions,
        classification_rules=classification_rules,
        transaction_override_store=transaction_override_store,
    )
    report = render_category_id_migration_audit_markdown(audit)
    if rule_warnings or override_warnings:
        warning_block = ["## Loader Warnings", ""]
        warning_block.extend(f"- {warning}" for warning in [*rule_warnings, *override_warnings])
        report = "\n".join([report.rstrip(), "", *warning_block, ""])

    output_path = outputs_root_path(settings) / _AUDIT_FILENAME
    output_path.write_text(report, encoding="utf-8")
    return output_path


def main() -> int:
    """Run the live category-id migration audit from current environment settings."""
    settings = load_settings_from_env()
    output_path = run_category_id_migration_audit(settings)
    print(f"Category ID migration audit: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import pandas as pd

from finance_tooling.audits.category_id_migration import (
    build_category_id_migration_audit,
    render_category_id_migration_audit_markdown,
)
from finance_tooling.categorization.classify import ClassificationRules, TaxonomyCategory
from finance_tooling.categorization.transaction_overrides import (
    TransactionOverrideEntry,
    TransactionOverrideStore,
)


def _override_entry(
    *,
    transaction_id: str | None = None,
    category_id: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
) -> TransactionOverrideEntry:
    return TransactionOverrideEntry(
        override_id=None,
        transaction_id=transaction_id,
        fingerprint=None,
        booking_date=None,
        amount_native=None,
        currency=None,
        bank=None,
        account_label=None,
        category_id=category_id,
        set_category_id=category_id is not None,
        category=category,
        set_category=category is not None,
        subcategory=subcategory,
        set_subcategory=subcategory is not None,
    )


def test_build_category_id_migration_audit_counts_backfillable_and_unresolved_rows() -> None:
    canonical = pd.DataFrame(
        [
            {
                "transaction_id": "tx-1",
                "category_id": "income.salary",
                "category": "Income",
                "subcategory": "Salary",
            },
            {
                "transaction_id": "tx-2",
                "category": "Dining",
                "subcategory": "Restaurants",
            },
            {
                "transaction_id": "tx-3",
                "category": "Mystery",
                "subcategory": "Thing",
            },
        ]
    )
    rules = ClassificationRules(
        rules=(),
        taxonomy={
            "income.salary": TaxonomyCategory(
                name="income.salary",
                subcategories=(),
                cashflow_type="in",
                economic_role="income",
                category_label="Income",
                subcategory_label="Salary",
            ),
            "dining.restaurants": TaxonomyCategory(
                name="dining.restaurants",
                subcategories=(),
                cashflow_type="out",
                economic_role="expense",
                category_label="Dining",
                subcategory_label="Restaurants",
                deprecated_to="dining.dining_out",
                status="deprecated",
            ),
            "dining.dining_out": TaxonomyCategory(
                name="dining.dining_out",
                subcategories=(),
                cashflow_type="out",
                economic_role="expense",
                category_label="Dining",
                subcategory_label="Dining out",
            ),
        },
    )
    overrides = TransactionOverrideStore(
        entries=(
            _override_entry(transaction_id="tx-1", category_id="income.salary"),
            _override_entry(transaction_id="tx-2", category="Dining", subcategory="Restaurants"),
            _override_entry(transaction_id="tx-3", category="Mystery", subcategory="Thing"),
        )
    )

    audit = build_category_id_migration_audit(
        canonical_transactions=canonical,
        classification_rules=rules,
        transaction_override_store=overrides,
    )

    assert audit.canonical_summary["total_rows"] == 3
    assert audit.canonical_summary["rows_with_existing_category_id"] == 1
    assert audit.canonical_summary["rows_backfilled_from_labels"] == 1
    assert audit.canonical_summary["deprecated_row_count"] == 1
    assert audit.canonical_summary["unresolved_row_count"] == 1
    assert audit.override_summary["entries_with_existing_category_id"] == 1
    assert audit.override_summary["entries_backfilled_from_labels"] == 1
    assert audit.override_summary["deprecated_entry_count"] == 1
    assert audit.override_summary["unresolved_entry_count"] == 1
    assert [row.identifier for row in audit.unresolved_rows] == ["tx-3", "tx-3"]


def test_build_category_id_migration_audit_applies_legacy_aliases_and_family_fallbacks() -> None:
    canonical = pd.DataFrame(
        [
            {"transaction_id": "tx-1", "category": "Shopping", "subcategory": "Clothing"},
            {"transaction_id": "tx-2", "category": "Utilities", "subcategory": None},
            {"transaction_id": "tx-3", "category": "Mystery", "subcategory": None},
        ]
    )
    rules = ClassificationRules(
        rules=(),
        taxonomy={
            "shopping.apparel": TaxonomyCategory(
                name="shopping.apparel",
                subcategories=(),
                cashflow_type="out",
                economic_role="expense",
                category_label="Shopping",
                subcategory_label="Apparel",
            ),
            "utilities.other_utilities": TaxonomyCategory(
                name="utilities.other_utilities",
                subcategories=(),
                cashflow_type="out",
                economic_role="expense",
                category_label="Utilities",
                subcategory_label="Other Utilities",
            ),
        },
    )
    overrides = TransactionOverrideStore(
        entries=(
            _override_entry(transaction_id="tx-1", category="Shopping", subcategory="Clothing"),
            _override_entry(transaction_id="tx-2", category="Utilities"),
        )
    )

    audit = build_category_id_migration_audit(
        canonical_transactions=canonical,
        classification_rules=rules,
        transaction_override_store=overrides,
    )

    assert audit.canonical_summary["rows_backfilled_from_labels"] == 2
    assert audit.canonical_summary["unresolved_row_count"] == 1
    assert audit.override_summary["entries_backfilled_from_labels"] == 2
    assert audit.override_summary["unresolved_entry_count"] == 0


def test_build_category_id_migration_audit_flags_ambiguous_taxonomy_labels() -> None:
    canonical = pd.DataFrame(columns=["transaction_id", "category", "subcategory"])
    rules = ClassificationRules(
        rules=(),
        taxonomy={
            "shopping.general_goods": TaxonomyCategory(
                name="shopping.general_goods",
                subcategories=(),
                cashflow_type="out",
                economic_role="expense",
                category_label="Shopping",
                subcategory_label="General goods",
            ),
            "shopping.general_retail": TaxonomyCategory(
                name="shopping.general_retail",
                subcategories=(),
                cashflow_type="out",
                economic_role="expense",
                category_label="Shopping",
                subcategory_label="General goods",
                status="deprecated",
                deprecated_to="shopping.general_goods",
            ),
        },
    )
    overrides = TransactionOverrideStore(entries=())

    audit = build_category_id_migration_audit(
        canonical_transactions=canonical,
        classification_rules=rules,
        transaction_override_store=overrides,
    )

    assert audit.taxonomy_summary["ambiguous_label_pair_count"] == 1
    ambiguous = audit.taxonomy_summary["ambiguous_label_pairs"][0]
    assert ambiguous["category"] == "shopping"
    assert ambiguous["subcategory"] == "general goods"


def test_render_category_id_migration_audit_markdown_includes_sections() -> None:
    canonical = pd.DataFrame(
        [{"transaction_id": "tx-1", "category_id": "income.salary", "category": "Income"}]
    )
    rules = ClassificationRules(
        rules=(),
        taxonomy={
            "income.salary": TaxonomyCategory(
                name="income.salary",
                subcategories=(),
                cashflow_type="in",
                economic_role="income",
                category_label="Income",
                subcategory_label="Salary",
            )
        },
    )
    overrides = TransactionOverrideStore(entries=())

    audit = build_category_id_migration_audit(
        canonical_transactions=canonical,
        classification_rules=rules,
        transaction_override_store=overrides,
    )
    report = render_category_id_migration_audit_markdown(audit)

    assert "# Category ID Migration Audit" in report
    assert "## Canonical Summary" in report
    assert "## Override Summary" in report
    assert "## Taxonomy Summary" in report
    assert "## Unresolved Rows" in report

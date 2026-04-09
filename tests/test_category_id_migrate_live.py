from __future__ import annotations

import pandas as pd

from finance_tooling.categorization.classify import ClassificationRules, TaxonomyCategory
from finance_tooling.categorization.transaction_overrides import (
    TransactionOverrideEntry,
    TransactionOverrideStore,
)
from finance_tooling.maintenance.category_id_migrate_live import (
    migrate_canonical_dataframe,
    migrate_override_store,
)


def _rules() -> ClassificationRules:
    return ClassificationRules(
        rules=(),
        taxonomy={
            "shopping.clothing": TaxonomyCategory(
                name="shopping.clothing",
                subcategories=(),
                cashflow_type=None,
                economic_role="expense",
                category_label="Shopping",
                subcategory_label="Clothing",
            ),
            "shopping.apparel": TaxonomyCategory(
                name="shopping.apparel",
                subcategories=(),
                cashflow_type=None,
                economic_role="expense",
                category_label="Shopping",
                subcategory_label="Apparel",
                deprecated_to="shopping.clothing",
            ),
            "utilities.other_utilities": TaxonomyCategory(
                name="utilities.other_utilities",
                subcategories=(),
                cashflow_type=None,
                economic_role="expense",
                category_label="Utilities",
                subcategory_label="Other Utilities",
            ),
        },
    )


def test_migrate_canonical_dataframe_backfills_category_ids_and_labels() -> None:
    dataframe = pd.DataFrame(
        [
            {"transaction_id": "tx-1", "category": "Shopping", "subcategory": "Clothing"},
            {"transaction_id": "tx-2", "category": "Utilities", "subcategory": None},
            {"transaction_id": "tx-3", "category": "Uncategorized", "subcategory": None},
        ]
    )

    migrated, updated_rows = migrate_canonical_dataframe(dataframe, rules=_rules())

    assert updated_rows == 2
    assert migrated.loc[0, "category_id"] == "shopping.clothing"
    assert migrated.loc[0, "reporting_category_id"] == "shopping.clothing"
    assert migrated.loc[0, "category"] == "Shopping"
    assert migrated.loc[0, "subcategory"] == "Clothing"
    assert migrated.loc[1, "category_id"] == "utilities.other_utilities"
    assert pd.isna(migrated.loc[2, "category_id"])


def test_migrate_override_store_rewrites_entries_to_category_id_only() -> None:
    store = TransactionOverrideStore(
        entries=(
            TransactionOverrideEntry(
                override_id=None,
                transaction_id="tx-1",
                fingerprint=None,
                booking_date=None,
                amount_native=None,
                currency=None,
                bank=None,
                account_label=None,
                category="Shopping",
                set_category=True,
                subcategory="Clothing",
                set_subcategory=True,
            ),
        )
    )

    migrated, updated_entries = migrate_override_store(store, rules=_rules())

    assert updated_entries == 1
    entry = migrated.entries[0]
    assert entry.category_id == "shopping.clothing"
    assert entry.set_category_id is True
    assert entry.category is None
    assert entry.set_category is False
    assert entry.subcategory is None
    assert entry.set_subcategory is False

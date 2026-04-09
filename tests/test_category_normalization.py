from __future__ import annotations

from datetime import date

import pandas as pd

from finance_tooling.categorization.category_normalization import (
    build_categorization_consolidation_delta,
    normalize_categories_for_dataframe,
)
from finance_tooling.categorization.classify import ClassificationRules, TaxonomyCategory


def _rules() -> ClassificationRules:
    return ClassificationRules(
        rules=(),
        taxonomy={
            "housing": TaxonomyCategory(
                name="Housing",
                subcategories=("Mortgage", "Cleaning"),
                cashflow_type="out",
            ),
            "transport": TaxonomyCategory(
                name="Transport",
                subcategories=("Car", "Bikes"),
                cashflow_type="out",
            ),
            "non personal transactions": TaxonomyCategory(
                name="Non Personal Transactions",
                subcategories=("Work", "APEL", "Other"),
                cashflow_type="exclude",
            ),
            "leisure": TaxonomyCategory(
                name="Leisure",
                subcategories=("Dining out", "Sports"),
                cashflow_type="out",
            ),
            "transfers": TaxonomyCategory(
                name="Transfers",
                subcategories=("Bank Transfer", "Wallet Transfer", "Savings Transfer"),
                cashflow_type="transfer",
            ),
            "taxes": TaxonomyCategory(
                name="Taxes",
                subcategories=("Penalties",),
                cashflow_type="out",
            ),
        },
    )


def test_normalize_categories_for_dataframe_maps_legacy_aliases() -> None:
    dataframe = pd.DataFrame(
        [
            {"category": "House", "subcategory": "Mortgage"},
            {"category": "Mobility", "subcategory": "Car"},
            {"category": "Work", "subcategory": "Expenses"},
            {"category": "Leisure", "subcategory": "Dining Out"},
            {"category": "Transfers", "subcategory": "Bank Transfers"},
            {"category": "Transport", "subcategory": "Bike"},
            {"category": "Taxes", "subcategory": "Penalties"},
        ]
    )

    result = normalize_categories_for_dataframe(dataframe, rules=_rules())

    assert result.changed_row_count == 6
    assert result.dataframe["category"].tolist() == [
        "Housing",
        "Transport",
        "Non Personal Transactions",
        "Leisure",
        "Transfers",
        "Transport",
        "Taxes",
    ]
    assert result.dataframe["subcategory"].astype("string").fillna("").tolist() == [
        "Mortgage",
        "Car",
        "Work",
        "Dining out",
        "Bank Transfer",
        "Bikes",
        "Penalties",
    ]


def test_build_categorization_consolidation_delta_groups_changes() -> None:
    reference = pd.DataFrame(
        [
            {
                "booking_date": date(2024, 1, 2),
                "description": "Cafe Nero",
                "amount_native": -12.5,
                "currency": "EUR",
                "bank": "HSBC",
                "category": "Dining",
                "subcategory": "Restaurants",
                "category_source": "rule",
                "amount_eur": -12.5,
            },
            {
                "booking_date": date(2024, 1, 3),
                "description": "Old transfer",
                "amount_native": -100.0,
                "currency": "EUR",
                "bank": "HSBC",
                "category": "Transfers",
                "subcategory": "Bank Transfers",
                "category_source": "transaction_override",
                "amount_eur": -100.0,
            },
        ]
    )
    current = pd.DataFrame(
        [
            {
                "booking_date": date(2024, 1, 2),
                "description": "Cafe Nero",
                "amount_native": -12.5,
                "currency": "EUR",
                "bank": "HSBC",
                "category": "Leisure",
                "subcategory": "Dining out",
                "category_source": "rule",
                "amount_eur": -12.5,
            },
            {
                "booking_date": date(2024, 1, 3),
                "description": "Old transfer",
                "amount_native": -100.0,
                "currency": "EUR",
                "bank": "HSBC",
                "category": "Transfers",
                "subcategory": "Bank Transfer",
                "category_source": "transaction_override",
                "amount_eur": -100.0,
            },
        ]
    )

    delta = build_categorization_consolidation_delta(
        current,
        reference_dataframe=reference,
    )

    assert len(delta) == 2
    assert set(delta["proposed_action"]) == {"merge_to_current_target"}
    assert {
        (row.before_category, row.before_subcategory, row.after_category, row.after_subcategory)
        for row in delta.itertuples()
    } == {
        ("Dining", "Restaurants", "Leisure", "Dining out"),
        ("Transfers", "Bank Transfers", "Transfers", "Bank Transfer"),
    }

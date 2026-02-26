import json
from pathlib import Path

import pandas as pd

from finance_tooling.categorization_review import (
    export_fallback_review_rows,
    import_review_into_overrides,
)
from finance_tooling.classify import OverrideEntry, OverrideStore, load_override_store


def test_export_fallback_review_rows_filters_and_deduplicates(tmp_path: Path) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
            },
            {
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
            },
            {
                "description": "CARD UBER",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Transport",
                "subcategory": "Mobility",
                "category_source": "rule",
            },
        ]
    ).to_csv(normalized_path, index=False)

    exported = export_fallback_review_rows(normalized_path, output_path)

    assert exported == 1
    exported_df = pd.read_csv(output_path)
    assert exported_df.columns.tolist() == [
        "description",
        "bank",
        "account_label",
        "category",
        "subcategory",
        "category_source",
    ]
    assert exported_df.loc[0, "description"] == "UNKNOWN MERCHANT 123"
    assert exported_df.loc[0, "category_source"] == "fallback"


def test_import_review_into_overrides_upserts_default_scope(tmp_path: Path) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    pd.DataFrame(
        [
            {
                "description": "UNKNOWN MERCHANT 123",
                "bank": "revolut",
                "account_label": "Main",
                "category": "Shopping",
                "subcategory": "General Retail",
                "category_source": "fallback",
            }
        ]
    ).to_csv(review_path, index=False)

    existing = OverrideStore(
        entries=(
            OverrideEntry(
                fingerprint="unknown merchant 123",
                category="Old Category",
                subcategory="Old Subcategory",
                bank="REVOLUT",
                account_label=None,
                hit_count=4,
            ),
        )
    )

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=existing,
        include_account_label_scope=False,
    )

    assert result.rows_read == 1
    assert result.overrides_upserted == 1
    assert result.overrides_updated == 1
    assert result.overrides_inserted == 0
    assert result.rows_skipped == 0

    overrides, warnings = load_override_store(overrides_path)
    assert warnings == []
    assert len(overrides.entries) == 1
    assert overrides.entries[0].fingerprint == "unknown merchant 123"
    assert overrides.entries[0].category == "Shopping"
    assert overrides.entries[0].subcategory == "General Retail"
    assert overrides.entries[0].bank == "REVOLUT"
    assert overrides.entries[0].account_label is None
    assert overrides.entries[0].hit_count == 4


def test_import_review_into_overrides_supports_account_label_scope(tmp_path: Path) -> None:
    review_path = tmp_path / "review.json"
    overrides_path = tmp_path / "category_overrides.json"
    review_path.write_text(
        json.dumps(
            [
                {
                    "description": "UNKNOWN MERCHANT 123",
                    "bank": "REVOLUT",
                    "account_label": "Main",
                    "category": "Shopping",
                    "subcategory": "General Retail",
                    "category_source": "fallback",
                }
            ]
        ),
        encoding="utf-8",
    )

    existing = OverrideStore(
        entries=(
            OverrideEntry(
                fingerprint="unknown merchant 123",
                category="Old Category",
                subcategory=None,
                bank="REVOLUT",
                account_label=None,
                hit_count=0,
            ),
        )
    )

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=existing,
        include_account_label_scope=True,
    )

    assert result.overrides_updated == 0
    assert result.overrides_inserted == 1

    overrides, warnings = load_override_store(overrides_path)
    assert warnings == []
    assert len(overrides.entries) == 2
    scoped_entry = next(
        entry
        for entry in overrides.entries
        if entry.account_label == "MAIN" and entry.bank == "REVOLUT"
    )
    assert scoped_entry.category == "Shopping"
    assert scoped_entry.subcategory == "General Retail"

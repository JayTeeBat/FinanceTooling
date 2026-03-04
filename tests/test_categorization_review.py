import json
from pathlib import Path

import pandas as pd
import pytest

from finance_tooling.categorization_review import (
    export_fallback_review_rows,
    import_review_into_overrides,
)
from finance_tooling.classify import OverrideEntry, OverrideStore, load_override_store
from finance_tooling.transaction_overrides import (
    TransactionOverrideStore,
    load_transaction_override_store,
)


def test_export_fallback_review_rows_filters_and_keeps_full_detail(tmp_path: Path) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    normalized_df = pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "UNKNOWN MERCHANT 123",
                "amount_native": -10.5,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
                "project_tags": "OldTagA|OldTagB",
                "source_file": "a.pdf",
            },
            {
                "transaction_id": "tx_2",
                "booking_date": "2026-01-02",
                "description": "UNKNOWN MERCHANT 123",
                "amount_native": -12.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
                "project_tags": None,
                "source_file": "b.pdf",
            },
            {
                "transaction_id": "tx_3",
                "booking_date": "2026-01-03",
                "description": "CARD UBER",
                "amount_native": -20.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Transport",
                "subcategory": "Mobility",
                "category_source": "rule",
                "project_tags": "Commuting",
                "source_file": "c.pdf",
            },
        ]
    )
    normalized_df.to_csv(normalized_path, index=False)

    exported = export_fallback_review_rows(normalized_path, output_path)

    assert exported == 2
    exported_df = pd.read_csv(output_path)
    assert "existing_project_tags" in exported_df.columns
    assert "project_tags" in exported_df.columns
    assert "override_level" in exported_df.columns
    assert exported_df["transaction_id"].tolist() == ["tx_1", "tx_2"]
    assert exported_df["booking_date"].tolist() == ["2026-01-01", "2026-01-02"]
    assert exported_df.loc[0, "description"] == "UNKNOWN MERCHANT 123"
    assert exported_df.loc[0, "category_source"] == "fallback"
    assert exported_df.loc[0, "existing_project_tags"] == "OldTagA|OldTagB"
    assert pd.isna(exported_df.loc[1, "existing_project_tags"])
    assert exported_df["project_tags"].isna().all()
    assert exported_df["override_level"].isna().all()


def test_export_fallback_review_rows_accepts_whitespace_and_case_variants(tmp_path: Path) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "description": "UNKNOWN MERCHANT 999",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "Fallback ",
            }
        ]
    ).to_csv(normalized_path, index=False)

    exported = export_fallback_review_rows(normalized_path, output_path)

    assert exported == 1
    exported_df = pd.read_csv(output_path)
    assert exported_df.loc[0, "description"] == "UNKNOWN MERCHANT 999"


def test_export_fallback_review_rows_places_override_level_after_project_source(
    tmp_path: Path,
) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
                "project_source": "project_fallback",
            }
        ]
    ).to_csv(normalized_path, index=False)

    exported = export_fallback_review_rows(normalized_path, output_path)

    assert exported == 1
    exported_df = pd.read_csv(output_path)
    columns = exported_df.columns.tolist()
    assert columns.index("override_level") == columns.index("project_source") + 1


def test_export_fallback_review_rows_include_categorized_option_includes_non_fallback(
    tmp_path: Path,
) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
            },
            {
                "transaction_id": "tx_2",
                "booking_date": "2026-01-02",
                "description": "CARD UBER",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Transport",
                "subcategory": "Mobility",
                "category_source": "rule",
            },
        ]
    ).to_csv(normalized_path, index=False)

    exported = export_fallback_review_rows(
        normalized_path,
        output_path,
        include_categorized=True,
    )

    assert exported == 2
    exported_df = pd.read_csv(output_path)
    assert exported_df["transaction_id"].tolist() == ["tx_1", "tx_2"]


def test_export_fallback_review_rows_booking_date_filters_are_inclusive(tmp_path: Path) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_early",
                "booking_date": "2025-12-31",
                "description": "UNKNOWN EARLY",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
            },
            {
                "transaction_id": "tx_start",
                "booking_date": "2026-01-01",
                "description": "UNKNOWN START",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
            },
            {
                "transaction_id": "tx_end",
                "booking_date": "2026-01-02",
                "description": "UNKNOWN END",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
            },
            {
                "transaction_id": "tx_late",
                "booking_date": "2026-01-03",
                "description": "UNKNOWN LATE",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
            },
        ]
    ).to_csv(normalized_path, index=False)

    exported = export_fallback_review_rows(
        normalized_path,
        output_path,
        start_date="2026-01-01",
        end_date="2026-01-02",
    )

    assert exported == 2
    exported_df = pd.read_csv(output_path)
    assert exported_df["transaction_id"].tolist() == ["tx_start", "tx_end"]


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        ("bad-date", None),
        (None, "bad-date"),
    ],
)
def test_export_fallback_review_rows_invalid_date_filters_raise_value_error(
    tmp_path: Path,
    start_date: str | None,
    end_date: str | None,
) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
            }
        ]
    ).to_csv(normalized_path, index=False)

    with pytest.raises(ValueError):
        export_fallback_review_rows(
            normalized_path,
            output_path,
            start_date=start_date,
            end_date=end_date,
        )


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
    assert result.rows_skipped_non_fallback == 0
    assert result.rows_skipped_invalid == 0
    assert result.backup_path is None

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


def test_import_review_into_overrides_skips_non_fallback_rows_by_default(tmp_path: Path) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    pd.DataFrame(
        [
            {
                "description": "CARD UBER",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Transport",
                "subcategory": "Mobility",
                "category_source": "rule",
            }
        ]
    ).to_csv(review_path, index=False)

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=OverrideStore(entries=()),
        include_account_label_scope=False,
    )

    assert result.rows_read == 1
    assert result.overrides_upserted == 0
    assert result.rows_skipped == 1
    assert result.rows_skipped_non_fallback == 1
    assert result.rows_skipped_invalid == 0

    overrides, warnings = load_override_store(overrides_path)
    assert warnings == []
    assert overrides.entries == ()


def test_import_review_into_overrides_allows_non_fallback_when_enabled(tmp_path: Path) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    pd.DataFrame(
        [
            {
                "description": "CARD UBER",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Transport",
                "subcategory": "Mobility",
                "category_source": "rule",
            }
        ]
    ).to_csv(review_path, index=False)

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=OverrideStore(entries=()),
        include_account_label_scope=False,
        allow_non_fallback_import=True,
    )

    assert result.overrides_upserted == 1
    assert result.rows_skipped_non_fallback == 0


def test_import_review_into_overrides_dry_run_does_not_write(tmp_path: Path) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    pd.DataFrame(
        [
            {
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Shopping",
                "subcategory": "General Retail",
                "category_source": "fallback",
            }
        ]
    ).to_csv(review_path, index=False)
    original_content = "version: 1\noverrides: []\n"
    overrides_path.write_text(original_content, encoding="utf-8")

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=OverrideStore(entries=()),
        include_account_label_scope=False,
        dry_run=True,
        backup=True,
    )

    assert result.overrides_upserted == 1
    assert result.backup_path is None
    assert overrides_path.read_text(encoding="utf-8") == original_content


def test_import_review_into_overrides_creates_backup_when_writing(tmp_path: Path) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    backup_path = tmp_path / "manual_backup.yaml"
    pd.DataFrame(
        [
            {
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Shopping",
                "subcategory": "General Retail",
                "category_source": "fallback",
            }
        ]
    ).to_csv(review_path, index=False)
    original_content = "version: 1\noverrides: []\n"
    overrides_path.write_text(original_content, encoding="utf-8")

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=OverrideStore(entries=()),
        include_account_label_scope=False,
        backup=True,
        backup_path=backup_path,
    )

    assert result.backup_path == backup_path
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == original_content


def test_import_review_into_overrides_defaults_to_transaction_override_in_v2(
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    transaction_overrides_path = tmp_path / "transaction_overrides.yaml"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_123",
                "booking_date": "2026-02-01",
                "description": "UNKNOWN MERCHANT 123",
                "amount_native": -42.5,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": "Main",
                "category": "Shopping",
                "subcategory": "General Retail",
                "category_source": "fallback",
                "override_level": None,
            }
        ]
    ).to_csv(review_path, index=False)

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=OverrideStore(entries=()),
        transaction_overrides_path=transaction_overrides_path,
        existing_transaction_store=TransactionOverrideStore(entries=()),
        include_account_label_scope=False,
    )

    assert result.overrides_upserted == 0
    assert result.transaction_overrides_upserted == 1
    assert result.transaction_overrides_updated == 0
    assert result.transaction_overrides_inserted == 1
    assert result.rows_skipped_invalid_category == 0

    overrides, warnings = load_transaction_override_store(transaction_overrides_path)
    assert warnings == []
    assert len(overrides.entries) == 1
    entry = overrides.entries[0]
    assert entry.transaction_id == "tx_123"
    assert entry.category == "Shopping"
    assert entry.subcategory == "General Retail"
    assert entry.set_category is True
    assert entry.set_subcategory is True


def test_import_review_into_overrides_routes_category_override_level_to_category_store(
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    pd.DataFrame(
        [
            {
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": "Main",
                "category": "Shopping",
                "subcategory": "General Retail",
                "category_source": "fallback",
                "override_level": "category_override",
            }
        ]
    ).to_csv(review_path, index=False)

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=OverrideStore(entries=()),
        include_account_label_scope=False,
    )

    assert result.overrides_upserted == 1
    assert result.transaction_overrides_upserted == 0
    overrides, warnings = load_override_store(overrides_path)
    assert warnings == []
    assert len(overrides.entries) == 1
    assert overrides.entries[0].category == "Shopping"


def test_import_review_into_overrides_applies_project_tags_as_transaction_override(
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    transaction_overrides_path = tmp_path / "transaction_overrides.yaml"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_project_1",
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": "Main",
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
                "override_level": "skip",
                "project_tags": "ProjectAtlas|Family",
            }
        ]
    ).to_csv(review_path, index=False)

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=OverrideStore(entries=()),
        transaction_overrides_path=transaction_overrides_path,
        existing_transaction_store=TransactionOverrideStore(entries=()),
        include_account_label_scope=False,
    )

    assert result.overrides_upserted == 0
    assert result.transaction_overrides_upserted == 1
    assert result.project_tags_applied == 1
    assert result.rows_skipped_invalid_project_tags == 0

    transaction_overrides, warnings = load_transaction_override_store(transaction_overrides_path)
    assert warnings == []
    assert len(transaction_overrides.entries) == 1
    entry = transaction_overrides.entries[0]
    assert entry.transaction_id == "tx_project_1"
    assert entry.project_tags == ("ProjectAtlas", "Family")
    assert entry.set_project_tags is True


def test_import_review_into_overrides_rejects_project_tags_without_transaction_id(
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    pd.DataFrame(
        [
            {
                "description": "UNKNOWN MERCHANT 123",
                "bank": "REVOLUT",
                "account_label": "Main",
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "fallback",
                "override_level": "skip",
                "project_tags": "ProjectAtlas|Family",
            }
        ]
    ).to_csv(review_path, index=False)

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=OverrideStore(entries=()),
        include_account_label_scope=False,
    )

    assert result.transaction_overrides_upserted == 0
    assert result.rows_skipped_invalid == 1
    assert result.rows_skipped_invalid_project_tags == 1


def test_import_review_into_overrides_skips_non_fallback_project_tags_by_default(
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.csv"
    overrides_path = tmp_path / "category_overrides.yaml"
    transaction_overrides_path = tmp_path / "transaction_overrides.yaml"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_non_fallback_1",
                "description": "CARD UBER",
                "bank": "REVOLUT",
                "account_label": "Main",
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "rule",
                "override_level": "skip",
                "project_tags": "ProjectAtlas",
            }
        ]
    ).to_csv(review_path, index=False)

    result = import_review_into_overrides(
        review_path=review_path,
        overrides_path=overrides_path,
        existing_store=OverrideStore(entries=()),
        transaction_overrides_path=transaction_overrides_path,
        existing_transaction_store=TransactionOverrideStore(entries=()),
        include_account_label_scope=False,
    )

    assert result.transaction_overrides_upserted == 0
    assert result.rows_skipped == 1
    assert result.rows_skipped_non_fallback == 1

    transaction_overrides, warnings = load_transaction_override_store(transaction_overrides_path)
    assert warnings == []
    assert transaction_overrides.entries == ()

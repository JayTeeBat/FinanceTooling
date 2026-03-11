import json
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from finance_tooling.migrate_category_overrides import migrate_category_overrides_to_rules
from finance_tooling.review_export import export_review_rows
from finance_tooling.review_import import import_review_into_overrides
from finance_tooling.review_state import load_review_state
from finance_tooling.transaction_overrides import load_transaction_override_store


def test_export_review_rows_filters_and_keeps_full_detail(tmp_path: Path) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.xlsx"
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
                "category_source": "uncategorized",
                "project_tags": "OldTagA|OldTagB",
                "source_file": "a.pdf",
            },
            {
                "transaction_id": "tx_2",
                "booking_date": "2026-01-02",
                "description": "CARD UBER",
                "amount_native": -12.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Transport",
                "subcategory": "Mobility",
                "category_source": "rule",
                "project_tags": None,
                "source_file": "b.pdf",
            },
        ]
    )
    normalized_df.to_csv(normalized_path, index=False)

    exported = export_review_rows(normalized_path, output_path)

    assert exported == 1
    exported_df = pd.read_excel(output_path, engine="openpyxl")
    assert exported_df.columns[:11].tolist() == [
        "transaction_id",
        "booking_date",
        "description",
        "amount_native",
        "currency",
        "bank",
        "category",
        "subcategory",
        "original_category",
        "original_subcategory",
        "project_tags",
    ]
    assert exported_df.loc[0, "original_category"] == "Uncategorized"
    assert pd.isna(exported_df.loc[0, "original_subcategory"])
    assert "normalized_description" in exported_df.columns
    assert "fingerprint" not in exported_df.columns
    assert "category_source" not in exported_df.columns
    assert "override_level" not in exported_df.columns
    assert exported_df.loc[0, "existing_project_tags"] == "OldTagA|OldTagB"
    workbook = load_workbook(output_path)
    worksheet = workbook["review"]
    assert worksheet["A1"].font.name == "Calibri"
    assert worksheet["A2"].fill.fgColor.rgb == "FF1E1E1E"


def test_export_review_rows_include_categorized_option_includes_all_sources(
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
                "amount_native": -10.5,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "uncategorized",
            },
            {
                "transaction_id": "tx_2",
                "booking_date": "2026-01-02",
                "description": "CARD UBER",
                "amount_native": -12.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Transport",
                "subcategory": "Mobility",
                "category_source": "rule",
            },
        ]
    ).to_csv(normalized_path, index=False)

    exported = export_review_rows(normalized_path, output_path, include_categorized=True)

    assert exported == 2
    exported_df = pd.read_csv(output_path)
    assert exported_df["transaction_id"].tolist() == ["tx_1", "tx_2"]


def test_export_review_rows_includes_legacy_fallback_uncategorized_rows(
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
                "amount_native": -10.5,
                "currency": "EUR",
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
                "amount_native": -12.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Transport",
                "subcategory": "Mobility",
                "category_source": "rule",
            },
        ]
    ).to_csv(normalized_path, index=False)

    exported = export_review_rows(normalized_path, output_path)

    assert exported == 1
    exported_df = pd.read_csv(output_path)
    assert exported_df["transaction_id"].tolist() == ["tx_1"]


def test_export_review_rows_applies_review_state_and_only_unreviewed(tmp_path: Path) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.xlsx"
    review_state_path = tmp_path / "review_state.parquet"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "Merchant Alpha",
                "amount_native": -10.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "uncategorized",
            },
            {
                "transaction_id": "tx_2",
                "booking_date": "2026-01-02",
                "description": "Merchant Beta",
                "amount_native": -12.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "uncategorized",
            },
        ]
    ).to_csv(normalized_path, index=False)
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "reviewed": True,
                "review_comment": "checked",
                "updated_at": "2026-03-07T10:00:00+00:00",
            }
        ]
    ).to_parquet(review_state_path, index=False)

    exported = export_review_rows(
        normalized_path,
        output_path,
        review_state_path=review_state_path,
        only_unreviewed=True,
    )

    assert exported == 1
    exported_df = pd.read_excel(output_path, engine="openpyxl")
    assert exported_df["transaction_id"].tolist() == ["tx_2"]


def test_export_review_rows_invalid_date_filters_raise_value_error(tmp_path: Path) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "UNKNOWN",
                "amount_native": -10.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "uncategorized",
            }
        ]
    ).to_csv(normalized_path, index=False)

    with pytest.raises(ValueError, match="start_date must be <= end_date"):
        export_review_rows(
            normalized_path,
            output_path,
            start_date="2026-02-01",
            end_date="2026-01-01",
        )


def test_export_review_rows_filters_by_absolute_amount_bounds(tmp_path: Path) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_small",
                "booking_date": "2026-01-01",
                "description": "Small expense",
                "amount_native": -9.99,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "uncategorized",
            },
            {
                "transaction_id": "tx_mid",
                "booking_date": "2026-01-02",
                "description": "Mid expense",
                "amount_native": -100.00,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "uncategorized",
            },
            {
                "transaction_id": "tx_large",
                "booking_date": "2026-01-03",
                "description": "Large refund",
                "amount_native": 250.00,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "uncategorized",
            },
        ]
    ).to_csv(normalized_path, index=False)

    exported = export_review_rows(
        normalized_path,
        output_path,
        min_abs_amount="50",
        max_abs_amount="200",
    )

    assert exported == 1
    exported_df = pd.read_csv(output_path)
    assert exported_df["transaction_id"].tolist() == ["tx_mid"]


def test_export_review_rows_rejects_invalid_absolute_amount_bounds(tmp_path: Path) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    output_path = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "UNKNOWN",
                "amount_native": -10.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "uncategorized",
            }
        ]
    ).to_csv(normalized_path, index=False)

    with pytest.raises(ValueError, match="min_abs_amount must be <= max_abs_amount"):
        export_review_rows(
            normalized_path,
            output_path,
            min_abs_amount="200",
            max_abs_amount="100",
        )

    with pytest.raises(ValueError, match="min_abs_amount must be a valid decimal value"):
        export_review_rows(
            normalized_path,
            output_path,
            min_abs_amount="abc",
        )


def test_import_review_into_overrides_writes_transaction_overrides_and_review_state(
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "transactions_review.xlsx"
    transaction_overrides_path = tmp_path / "transaction_overrides.yaml"
    review_state_path = tmp_path / "review_state.parquet"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "UNKNOWN MERCHANT 123",
                "amount_native": -10.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Shopping",
                "subcategory": "General Retail",
                "original_category": "Uncategorized",
                "original_subcategory": None,
                "project_tags": "Family|Shared",
                "reviewed": True,
                "review_comment": "done",
            }
        ]
    ).to_excel(review_path, index=False, engine="openpyxl")

    result = import_review_into_overrides(
        review_path=review_path,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=review_state_path,
    )

    assert result.transaction_overrides_upserted == 1
    assert result.project_tags_applied == 1
    transaction_overrides, warnings = load_transaction_override_store(transaction_overrides_path)
    assert warnings == []
    assert len(transaction_overrides.entries) == 1
    assert transaction_overrides.entries[0].transaction_id == "tx_1"
    assert transaction_overrides.entries[0].category == "Shopping"
    assert transaction_overrides.entries[0].subcategory == "General Retail"
    assert transaction_overrides.entries[0].project_tags == ("Family", "Shared")
    review_state = load_review_state(review_state_path)
    assert review_state.loc[0, "transaction_id"] == "tx_1"
    assert bool(review_state.loc[0, "reviewed"]) is True
    assert review_state.loc[0, "review_comment"] == "done"


def test_import_review_into_overrides_skips_unchanged_categorized_rows(tmp_path: Path) -> None:
    review_path = tmp_path / "transactions_review.xlsx"
    transaction_overrides_path = tmp_path / "transaction_overrides.yaml"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "CARD UBER",
                "amount_native": -10.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Transport",
                "subcategory": "Mobility",
                "original_category": "Transport",
                "original_subcategory": "Mobility",
                "project_tags": None,
                "reviewed": True,
                "review_comment": "checked",
            }
        ]
    ).to_excel(review_path, index=False, engine="openpyxl")

    result = import_review_into_overrides(
        review_path=review_path,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=None,
        dry_run=False,
    )

    assert result.transaction_overrides_upserted == 0
    assert not transaction_overrides_path.exists()


def test_import_review_into_overrides_creates_override_when_category_changes_from_baseline(
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "transactions_review.xlsx"
    transaction_overrides_path = tmp_path / "transaction_overrides.yaml"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "CARD UBER",
                "amount_native": -10.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Shopping",
                "subcategory": "General Retail",
                "original_category": "Transport",
                "original_subcategory": "Mobility",
                "project_tags": None,
                "reviewed": False,
                "review_comment": None,
            }
        ]
    ).to_excel(review_path, index=False, engine="openpyxl")

    result = import_review_into_overrides(
        review_path=review_path,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=None,
        dry_run=False,
    )

    assert result.transaction_overrides_upserted == 1
    store, warnings = load_transaction_override_store(transaction_overrides_path)
    assert warnings == []
    assert len(store.entries) == 1
    assert store.entries[0].category == "Shopping"
    assert store.entries[0].subcategory == "General Retail"


def test_import_review_into_overrides_rejects_subcategory_without_category(tmp_path: Path) -> None:
    review_path = tmp_path / "transactions_review.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "UNKNOWN MERCHANT 123",
                "amount_native": -10.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": None,
                "subcategory": "General Retail",
                "project_tags": None,
                "reviewed": False,
                "review_comment": None,
            }
        ]
    ).to_csv(review_path, index=False)

    result = import_review_into_overrides(review_path=review_path, dry_run=True)

    assert result.transaction_overrides_upserted == 0
    assert result.rows_skipped == 1
    assert result.rows_skipped_invalid_category == 1


def test_import_review_into_overrides_requires_transaction_id_for_category_edits(
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "transactions_review.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": None,
                "booking_date": "2026-01-01",
                "description": "UNKNOWN MERCHANT 123",
                "amount_native": -10.0,
                "currency": "EUR",
                "bank": "REVOLUT",
                "account_label": None,
                "category": "Shopping",
                "subcategory": "General Retail",
                "project_tags": None,
                "reviewed": False,
                "review_comment": None,
            }
        ]
    ).to_csv(review_path, index=False)

    result = import_review_into_overrides(review_path=review_path, dry_run=True)

    assert result.transaction_overrides_upserted == 0
    assert result.rows_skipped_invalid_category == 1


def test_migrate_category_overrides_to_rules_converts_entries(tmp_path: Path) -> None:
    overrides_path = tmp_path / "category_overrides.yaml"
    rules_path = tmp_path / "category_rules.yaml"
    report_path = tmp_path / "migration_report.json"
    overrides_path.write_text(
        "\n".join(
            [
                "version: 1",
                "overrides:",
                "  - fingerprint: paypal payment",
                "    category: Transfers",
                "    subcategory: Wallet Transfer",
                "    bank: REVOLUT",
            ]
        ),
        encoding="utf-8",
    )
    rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")

    result = migrate_category_overrides_to_rules(
        overrides_path=overrides_path,
        rules_path=rules_path,
        report_path=report_path,
    )

    assert result.migrated_count == 1
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["conflict_count"] == 0
    rules = rules_path.read_text(encoding="utf-8")
    assert "migrated.override.revolut.paypal_payment.1" in rules
    assert "match: exact" in rules
    assert "- paypal payment" in rules

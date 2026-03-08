from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.config import Settings
from finance_tooling.models import Transaction
from finance_tooling.workflow.enrichment import enrich_transactions


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        input_path=tmp_path / "input",
        output_path=tmp_path / "finance_dashboard.html",
        master_parquet_path=tmp_path / "transactions_master.parquet",
        export_csv_path=tmp_path / "transactions_normalized.csv",
        export_json_path=tmp_path / "transactions_normalized.json",
        staged_transactions_path=tmp_path / "staged_transactions.parquet",
        summary_json_path=tmp_path / "run_summary.json",
        completeness_json_path=tmp_path / "completeness_report.json",
        base_currency="EUR",
        fx_cache_path=tmp_path / "fx_rates_history.parquet",
        fx_auto_fetch=False,
        ingest_workers=1,
        ingest_text_cache_enabled=False,
        ingest_text_cache_path=tmp_path / "ingest_text_cache.parquet",
        category_rules_path=tmp_path / "category_rules.yaml",
        category_overrides_path=tmp_path / "category_overrides.yaml",
        project_rules_path=tmp_path / "project_rules.yaml",
        budget_targets_path=tmp_path / "budget_targets.yaml",
        project_overrides_path=tmp_path / "project_overrides.yaml",
        transaction_overrides_path=tmp_path / "transaction_overrides.yaml",
        review_state_path=tmp_path / "review_state.parquet",
        review_export_dark_safe=True,
    )


def test_enrich_transactions_applies_transaction_overrides_and_project_tags(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.input_path.mkdir(parents=True, exist_ok=True)

    settings.category_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")
    settings.category_overrides_path.write_text("version: 1\noverrides: []\n", encoding="utf-8")
    settings.project_overrides_path.write_text(
        "version: 1\nrules: []\noverrides: []\n",
        encoding="utf-8",
    )
    settings.transaction_overrides_path.write_text(
        "\n".join(
            [
                "version: 1",
                "overrides:",
                "  - fingerprint: zzzzq merchant",
                "    category: Shopping",
                "    subcategory: General Retail",
                "    project_tags: [ProjectAtlas, Family]",
            ]
        ),
        encoding="utf-8",
    )

    source_file = settings.input_path / "statement_2026-02-01.pdf"
    source_file.write_text("fake", encoding="utf-8")
    tx = Transaction(
        booking_date=date(2026, 2, 1),
        description="ZZZZQ Merchant 12345",
        amount_native=Decimal("-12.34"),
        currency="EUR",
        source_file=source_file,
        bank="REVOLUT",
        parser="revolut",
        account_label="Main",
    )

    result = enrich_transactions([tx], settings)

    assert result.warnings == []
    assert len(result.transactions) == 1
    enriched = result.transactions[0]
    assert enriched.category == "Shopping"
    assert enriched.subcategory == "General Retail"
    assert enriched.category_source == "transaction_override"
    assert enriched.category_confidence == 1.0
    assert enriched.project == "ProjectAtlas"
    assert enriched.project_tags == ("ProjectAtlas", "Family")
    assert enriched.project_source == "transaction_override"
    assert result.classification_diagnostics.categorized_count == 1
    assert result.classification_diagnostics.uncategorized_count == 0
    assert result.classification_diagnostics.category_source_counts == {"transaction_override": 1}

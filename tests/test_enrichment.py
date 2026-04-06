from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from finance_tooling.config import Settings
from finance_tooling.models import Transaction
from finance_tooling.workflow.enrichment import (
    apply_fx_and_mtime,
    enrich_transactions,
    recompute_dataframe_fx,
)


def _settings(tmp_path: Path) -> Settings:
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    return Settings(
        input_path=tmp_path / "input",
        processed_path=tmp_path,
        output_path=tmp_path / "outputs" / "transform_dashboard.html",
        master_parquet_path=tmp_path / "outputs" / "transform_transactions.parquet",
        export_csv_path=tmp_path / "outputs" / "transform_transactions.csv",
        export_json_path=tmp_path / "outputs" / "transform_transactions.json",
        staged_transactions_path=tmp_path / "state" / "ingest_staged_transactions.parquet",
        summary_json_path=tmp_path / "outputs" / "transform_run_summary.json",
        completeness_json_path=tmp_path / "state" / "transform_completeness_report.json",
        base_currency="EUR",
        fx_cache_path=tmp_path / "state" / "workflow_fx_rates_history.parquet",
        fx_auto_fetch=False,
        ingest_workers=1,
        ingest_text_cache_enabled=False,
        ingest_text_cache_path=tmp_path / "state" / "ingest_text_cache.parquet",
        category_rules_path=tmp_path / "category_rules.yaml",
        project_rules_path=tmp_path / "project_rules.yaml",
        budget_targets_path=tmp_path / "budget_targets.yaml",
        account_rules_path=tmp_path / "account_rules.yaml",
        project_overrides_path=tmp_path / "project_overrides.yaml",
        transaction_overrides_path=tmp_path / "transaction_overrides.yaml",
        review_state_path=tmp_path / "state" / "workflow_review_state.parquet",
        review_export_dark_safe=True,
    )


def test_enrich_transactions_applies_transaction_overrides_and_project_tags(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.input_path.mkdir(parents=True, exist_ok=True)

    settings.category_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")
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


def test_apply_fx_and_mtime_memoizes_source_file_mtime_stats(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings.input_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "finance_tooling.workflow.enrichment.ensure_fx_cache",
        lambda *_args, **_kwargs: (pd.DataFrame(), []),
    )

    source_file = settings.input_path / "statement_2026-02-01.pdf"
    source_file.write_text("fake", encoding="utf-8")
    stat_calls = 0
    original_stat = Path.stat

    def counting_stat(path: Path, *, follow_symlinks: bool = True):
        nonlocal stat_calls
        stat_calls += 1
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", counting_stat)

    transactions = [
        Transaction(
            booking_date=date(2026, 2, 1),
            description=f"Purchase {index}",
            amount_native=Decimal("-12.34"),
            currency="EUR",
            source_file=source_file,
            bank="REVOLUT",
            parser="revolut",
            account_label="Main",
        )
        for index in range(2)
    ]

    result, warnings = apply_fx_and_mtime(transactions, settings)

    assert warnings == []
    assert len(result) == 2
    assert stat_calls == 1


def test_recompute_dataframe_fx_repairs_existing_gbp_rows(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    cache = pd.DataFrame(
        [
            {
                "currency": "GBP",
                "rate_date": date(2017, 1, 27),
                "rate_to_eur": 1 / 0.8517,
                "source": "ECB_SDW",
                "fetched_at": "2026-04-06T00:00:00+00:00",
                "rate_semantics_version": 2,
            }
        ]
    )
    monkeypatch.setattr(
        "finance_tooling.workflow.enrichment.ensure_fx_cache",
        lambda *_args, **_kwargs: (cache, []),
    )

    dataframe = pd.DataFrame(
        [
            {
                "booking_date": "2017-01-27",
                "description": "Salary",
                "amount_native": 4357.95,
                "currency": "GBP",
                "amount_eur": 3711.66,
                "fx_rate_to_eur": 0.8517,
                "fx_rate_date": "2017-01-27",
                "fx_source": "ECB_SDW",
                "source_file": str(tmp_path / "statement.pdf"),
                "bank": "HSBC",
                "parser": "hsbc",
            }
        ]
    )

    recomputed, warnings = recompute_dataframe_fx(dataframe, settings)

    assert warnings == []
    assert recomputed.loc[0, "fx_rate_to_eur"] == pytest.approx(1 / 0.8517, rel=1e-9)
    assert recomputed.loc[0, "amount_eur"] == pytest.approx(4357.95 / 0.8517, rel=1e-9)

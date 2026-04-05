import csv
import json
from pathlib import Path

from finance_tooling.metrics_log import (
    build_bank_snapshots,
    build_snapshot,
    upsert_bank_snapshots,
    upsert_snapshot,
)


def test_build_snapshot_computes_percentage_metrics(tmp_path: Path) -> None:
    summary_path = tmp_path / "run_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "files_scanned": 100,
                "files_failed": 5,
                "transactions_parsed": 1000,
                "categorized_count": 620,
                "uncategorized_count": 380,
                "categorized_amount_eur_abs": 6200.0,
                "uncategorized_amount_eur_abs": 3800.0,
                "total_amount_eur_abs": 10000.0,
                "total_income_eur": 2000.0,
                "file_coverage_ratio": 0.97,
                "statement_reconciliation_pass_ratio": 0.81,
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_snapshot(summary_path, commit="abc1234", branch="feature/x")

    assert snapshot.commit == "abc1234"
    assert snapshot.branch == "feature/x"
    assert snapshot.parsing_success_pct == 95.0
    assert snapshot.completeness_coverage_pct == 97.0
    assert snapshot.categorized_pct == 62.0
    assert snapshot.uncategorized_pct == 38.0
    assert snapshot.categorized_amount_eur_abs == 6200.0
    assert snapshot.uncategorized_amount_eur_abs == 3800.0
    assert snapshot.categorized_amount_eur_abs_pct == 310.0
    assert snapshot.uncategorized_amount_eur_abs_pct == 190.0
    assert snapshot.reconciliation_pass_pct == 81.0


def test_upsert_snapshot_replaces_existing_commit_row(tmp_path: Path) -> None:
    summary_path = tmp_path / "run_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "files_scanned": 10,
                "files_failed": 0,
                "transactions_parsed": 100,
                "categorized_count": 50,
                "uncategorized_count": 50,
                "categorized_amount_eur_abs": 500.0,
                "uncategorized_amount_eur_abs": 500.0,
                "total_amount_eur_abs": 1000.0,
                "total_income_eur": 400.0,
                "file_coverage_ratio": 1.0,
                "statement_reconciliation_pass_ratio": 0.5,
            }
        ),
        encoding="utf-8",
    )
    log_path = tmp_path / "metrics_commit_log.csv"

    first = build_snapshot(summary_path, commit="abc1234", branch="feature/x")
    rows_count, replaced = upsert_snapshot(log_path, first)
    assert rows_count == 1
    assert replaced == 0

    summary_path.write_text(
        json.dumps(
            {
                "files_scanned": 10,
                "files_failed": 1,
                "transactions_parsed": 100,
                "categorized_count": 90,
                "uncategorized_count": 10,
                "categorized_amount_eur_abs": 900.0,
                "uncategorized_amount_eur_abs": 100.0,
                "total_amount_eur_abs": 1000.0,
                "total_income_eur": 300.0,
                "file_coverage_ratio": 0.9,
                "statement_reconciliation_pass_ratio": 0.8,
            }
        ),
        encoding="utf-8",
    )
    second = build_snapshot(summary_path, commit="abc1234", branch="feature/x")
    rows_count, replaced = upsert_snapshot(log_path, second)
    assert rows_count == 1
    assert replaced == 1

    with log_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["commit"] == "abc1234"
    assert rows[0]["categorized_pct"] == "90.0000"
    assert rows[0]["uncategorized_pct"] == "10.0000"
    assert rows[0]["categorized_amount_eur_abs"] == "900.0000"
    assert rows[0]["uncategorized_amount_eur_abs"] == "100.0000"
    assert rows[0]["categorized_amount_eur_abs_pct"] == "300.0000"
    assert rows[0]["uncategorized_amount_eur_abs_pct"] == "33.3333"


def test_build_bank_snapshots_and_upsert(tmp_path: Path) -> None:
    summary_path = tmp_path / "run_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "category_metrics_by_bank": [
                    {
                        "bank": "HSBC",
                        "transactions_count": 3,
                        "categorized_count": 2,
                        "uncategorized_count": 1,
                        "categorized_pct": 66.6667,
                        "uncategorized_pct": 33.3333,
                        "income_amount_eur": 100.0,
                        "categorized_amount_eur_abs": 120.0,
                        "uncategorized_amount_eur_abs": 30.0,
                        "categorized_amount_eur_abs_ratio": 120.0,
                        "uncategorized_amount_eur_abs_ratio": 30.0,
                    },
                    {
                        "bank": "Revolut",
                        "transactions_count": 2,
                        "categorized_count": 0,
                        "uncategorized_count": 2,
                        "categorized_pct": 0.0,
                        "uncategorized_pct": 100.0,
                        "income_amount_eur": 50.0,
                        "categorized_amount_eur_abs": 0.0,
                        "uncategorized_amount_eur_abs": 75.0,
                        "categorized_amount_eur_abs_ratio": 0.0,
                        "uncategorized_amount_eur_abs_ratio": 150.0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    snapshots = build_bank_snapshots(summary_path, commit="abc1234", branch="feature/x")

    assert len(snapshots) == 2
    hsbc = next(item for item in snapshots if item.bank == "HSBC")
    assert hsbc.transactions_count == 3
    assert hsbc.categorized_count == 2
    assert hsbc.uncategorized_count == 1
    assert hsbc.categorized_pct == 66.6667
    assert hsbc.categorized_amount_eur_abs == 120.0
    assert hsbc.uncategorized_amount_eur_abs == 30.0
    assert hsbc.categorized_amount_eur_abs_pct == 120.0
    revolut = next(item for item in snapshots if item.bank == "Revolut")
    assert revolut.transactions_count == 2
    assert revolut.categorized_count == 0
    assert revolut.uncategorized_count == 2
    assert revolut.uncategorized_pct == 100.0
    assert revolut.uncategorized_amount_eur_abs == 75.0
    assert revolut.uncategorized_amount_eur_abs_pct == 150.0

    by_bank_path = tmp_path / "metrics_commit_log_by_bank.csv"
    bank_rows, replaced = upsert_bank_snapshots(by_bank_path, snapshots)
    assert bank_rows == 2
    assert replaced == 0

    with by_bank_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {row["bank"] for row in rows} == {"HSBC", "Revolut"}

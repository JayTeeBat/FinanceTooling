from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from finance_tooling.completeness import build_completeness_report
from finance_tooling.models import Transaction


def _tx(source_file: Path, bank: str) -> Transaction:
    return Transaction(
        booking_date=date(2024, 1, 15),
        description="sample",
        amount_native=Decimal("10.00"),
        currency="EUR",
        source_file=source_file,
        bank=bank,
        parser=bank.lower(),
    )


def test_build_completeness_report_tracks_missing_files_and_groupings() -> None:
    source_files = [
        Path("/data/Boursobank_statement_2018.pdf"),
        Path("/data/Revolut_account-statement_2021.pdf"),
        Path("/data/HSBC_2017_statement.pdf"),
    ]

    parsed = [
        _tx(source_files[0], "Boursobank"),
        _tx(source_files[0], "Boursobank"),
        _tx(source_files[1], "Revolut"),
    ]

    report = build_completeness_report(source_files, parsed)

    assert report["source_pdf_count"] == 3
    assert report["parsed_unique_source_file_count"] == 2
    assert report["file_coverage_ratio"] == 2 / 3
    assert report["status"] == "fail"
    assert report["missing_source_file_count"] == 1
    assert report["missing_source_files"] == ["/data/HSBC_2017_statement.pdf"]
    assert report["counts_by_year"] == {
        "2017": {"source_files": 1, "parsed_source_files": 0},
        "2018": {"source_files": 1, "parsed_source_files": 1},
        "2021": {"source_files": 1, "parsed_source_files": 1},
    }
    assert report["source_counts_by_bank_guess"] == {
        "Boursobank": 1,
        "HSBC": 1,
        "Revolut": 1,
    }
    assert report["parsed_transaction_counts_by_bank"] == {"Boursobank": 2, "Revolut": 1}
    assert report["parsed_source_file_counts_by_bank_guess"] == {"Boursobank": 1, "Revolut": 1}

    missing = cast(dict[str, Any], report["missing_grouped_summaries"])
    assert missing["by_year"] == {"2017": 1}
    assert missing["by_bank_guess"] == {"HSBC": 1}
    assert missing["by_year_and_bank_guess"] == [{"year": "2017", "bank_guess": "HSBC", "count": 1}]


def test_build_completeness_report_can_warn_between_thresholds() -> None:
    source_files = [
        Path("/data/a_2024.pdf"),
        Path("/data/b_2024.pdf"),
        Path("/data/c_2024.pdf"),
        Path("/data/d_2024.pdf"),
    ]
    parsed = [
        _tx(source_files[0], "Unknown"),
        _tx(source_files[1], "Unknown"),
        _tx(source_files[2], "Unknown"),
    ]

    report = build_completeness_report(
        source_files,
        parsed,
        warn_coverage_ratio=0.9,
        fail_coverage_ratio=0.7,
    )

    assert report["file_coverage_ratio"] == 0.75
    assert report["status"] == "warn"

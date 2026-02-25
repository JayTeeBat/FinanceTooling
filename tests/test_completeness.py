from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from finance_tooling.completeness import build_completeness_report, classify_statement_type
from finance_tooling.models import Transaction
from finance_tooling.parsers.base import StatementValidation


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
        Path("/data/LaBanquePostale Relevé de frais_2024.pdf"),
    ]

    parsed = [
        _tx(source_files[0], "Boursobank"),
        _tx(source_files[0], "Boursobank"),
        _tx(source_files[1], "Revolut"),
    ]

    report = build_completeness_report(source_files, parsed)

    assert report["source_pdf_count"] == 4
    assert report["source_statement_pdf_count"] == 3
    assert report["source_non_statement_pdf_count"] == 1
    assert report["parsed_unique_source_file_count"] == 2
    assert report["parsed_unique_statement_source_file_count"] == 2
    assert report["parsed_unique_non_statement_source_file_count"] == 0
    assert report["file_coverage_ratio"] == 2 / 3
    assert report["overall_file_coverage_ratio"] == 0.5
    assert report["status"] == "fail"
    assert report["missing_source_file_count"] == 1
    assert report["missing_source_file_count_all"] == 2
    assert report["missing_non_statement_source_file_count"] == 1
    assert report["missing_source_files"] == ["/data/HSBC_2017_statement.pdf"]
    assert report["missing_non_statement_source_files"] == [
        "/data/LaBanquePostale Relevé de frais_2024.pdf"
    ]
    assert report["counts_by_year"] == {
        "2017": {"source_files": 1, "parsed_source_files": 0},
        "2018": {"source_files": 1, "parsed_source_files": 1},
        "2021": {"source_files": 1, "parsed_source_files": 1},
        "2024": {"source_files": 1, "parsed_source_files": 0},
    }
    assert report["source_counts_by_bank_guess"] == {
        "Boursobank": 1,
        "HSBC": 1,
        "LaBanquePostale": 1,
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


def test_classify_statement_type_detects_non_statement_documents() -> None:
    assert (
        classify_statement_type(Path("/data/Boursobank Jacques COM-20-01-2025.pdf"))
        == "non_statement"
    )
    assert classify_statement_type(Path("/data/LaBanquePostale Relevé de frais_20231231.pdf")) == (
        "non_statement"
    )
    assert (
        classify_statement_type(Path("/data/HSBC Jacques 2024-01-31_Statement.pdf")) == "statement"
    )


def test_build_completeness_report_includes_reconciliation_kpis() -> None:
    source_file = Path("/data/HSBC_2024_statement.pdf")
    parsed = [_tx(source_file, "HSBC")]
    validations = [
        StatementValidation(
            source_file=source_file,
            bank="HSBC",
            parser="hsbc",
            statement_type="statement",
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("90.00"),
            transaction_sum=Decimal("-9.00"),
            expected_closing_balance=Decimal("91.00"),
            difference=Decimal("1.00"),
            status="fail",
            reason="balance_mismatch",
            severity="warning",
        ),
        StatementValidation(
            source_file=Path("/data/HSBC_2023_statement.pdf"),
            bank="HSBC",
            parser="hsbc",
            statement_type="statement",
            opening_balance=None,
            closing_balance=None,
            transaction_sum=Decimal("0.00"),
            expected_closing_balance=None,
            difference=None,
            status="uncheckable",
            reason="missing_opening_or_closing",
            severity="info",
        ),
    ]

    report = build_completeness_report(
        source_files=[source_file],
        parsed_transactions=parsed,
        validations=validations,
    )
    reconciliation = cast(dict[str, Any], report["statement_reconciliation"])

    assert reconciliation["files_with_validation_record_count"] == 2
    assert reconciliation["checkable_file_count"] == 1
    assert reconciliation["fail_count"] == 1
    assert reconciliation["uncheckable_file_count"] == 1
    assert reconciliation["counts_by_severity"] == {"info": 1, "warning": 1}
    assert len(reconciliation["warning_items"]) == 1
    assert len(reconciliation["info_items"]) == 1
    assert reconciliation["abs_difference_buckets"] == {
        "le_0_01": 0,
        "gt_0_01_le_10": 1,
        "gt_10_le_100": 0,
        "gt_100_le_1000": 0,
        "gt_1000": 0,
    }
    assert reconciliation["median_abs_difference"] == 1.0
    assert reconciliation["mean_abs_difference"] == 1.0
    bank_rows = cast(list[dict[str, Any]], reconciliation["by_bank_abs_difference"])
    assert bank_rows == [
        {
            "bank": "HSBC",
            "checkable_count": 1,
            "median_abs_difference": 1.0,
            "mean_abs_difference": 1.0,
            "abs_difference_buckets": {
                "le_0_01": 0,
                "gt_0_01_le_10": 1,
                "gt_10_le_100": 0,
                "gt_100_le_1000": 0,
                "gt_1000": 0,
            },
        }
    ]


def test_build_completeness_report_excludes_files_without_validation_record() -> None:
    source_files = [
        Path("/data/LaBanquePostale releve_CCP_20241224.pdf"),
        Path("/data/LaBanquePostale Relevé de frais_20250102.pdf"),
    ]
    parsed = [_tx(source_files[0], "LaBanquePostale")]
    validations = [
        StatementValidation(
            source_file=source_files[0],
            bank="LaBanquePostale",
            parser="labanquepostale",
            statement_type="statement",
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("110.00"),
            transaction_sum=Decimal("10.00"),
            expected_closing_balance=Decimal("110.00"),
            difference=Decimal("0.00"),
            status="pass",
            reason=None,
            severity="none",
        )
    ]

    report = build_completeness_report(
        source_files=source_files,
        parsed_transactions=parsed,
        validations=validations,
    )
    reconciliation = cast(dict[str, Any], report["statement_reconciliation"])

    assert reconciliation["files_with_validation_record_count"] == 1
    assert reconciliation["checkable_file_count"] == 1
    assert reconciliation["pass_count"] == 1
    assert reconciliation["uncheckable_file_count"] == 0

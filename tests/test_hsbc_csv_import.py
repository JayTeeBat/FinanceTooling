from decimal import Decimal
from pathlib import Path

from finance_tooling.importers.hsbc_csv import load_hsbc_csv_transactions


def test_load_hsbc_csv_transactions_parses_rows_and_skips_zero_amount(tmp_path: Path) -> None:
    csv_path = tmp_path / "hsbc.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Payee,Memo,Amount,Account number",
                "21/03/2022,Salary,Monthly payroll,1200.00,40-22-30 31492861",
                "22/03/2022,Opening  this month,,0,40-22-30 31492861",
                "23/03/2022,Card Payment,, -12.34,40-22-30 31492861",
            ]
        ),
        encoding="utf-8",
    )

    result = load_hsbc_csv_transactions([csv_path])

    assert result.files_scanned == 1
    assert result.warnings == []
    assert len(result.transactions) == 2

    first = result.transactions[0]
    assert first.bank == "HSBC"
    assert first.parser == "hsbc_csv"
    assert first.currency == "GBP"
    assert first.description == "Salary Monthly payroll"
    assert first.amount_native == Decimal("1200.00")
    assert first.account_label == "40-22-30 31492861"

    second = result.transactions[1]
    assert second.description == "Card Payment"
    assert second.amount_native == Decimal("-12.34")


def test_load_hsbc_csv_transactions_warns_for_missing_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "hsbc_bad.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Payee,Memo",
                "21/03/2022,Salary,Monthly payroll",
            ]
        ),
        encoding="utf-8",
    )

    result = load_hsbc_csv_transactions([csv_path])

    assert result.transactions == []
    assert len(result.warnings) == 1
    assert "missing required columns" in result.warnings[0]

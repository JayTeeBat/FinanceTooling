"""HSBC CSV importer."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from finance_tooling.models import Transaction

_DATE_FORMAT = "%d/%m/%Y"
_REQUIRED_COLUMNS = ("Date", "Payee", "Amount")


@dataclass(frozen=True)
class HsbcCsvImportResult:
    """Import result with transactions and non-fatal warnings."""

    transactions: list[Transaction]
    warnings: list[str]
    files_scanned: int


def _compose_description(payee: str, memo: str) -> str:
    parts = [payee.strip(), memo.strip()]
    return " ".join(part for part in parts if part).strip()


def _parse_row(
    *,
    row: dict[str, str],
    source_file: Path,
    row_number: int,
) -> tuple[Transaction | None, str | None]:
    date_raw = (row.get("Date") or "").strip()
    payee_raw = (row.get("Payee") or "").strip()
    memo_raw = (row.get("Memo") or "").strip()
    amount_raw = (row.get("Amount") or "").strip()
    account_raw = (row.get("Account number") or "").strip() or None

    try:
        booking_date = datetime.strptime(date_raw, _DATE_FORMAT).date()
    except ValueError:
        return None, (
            f"HSBC CSV parse warning ({source_file.name}:{row_number}): invalid date {date_raw!r}"
        )

    try:
        amount_native = Decimal(amount_raw)
    except InvalidOperation:
        return None, (
            f"HSBC CSV parse warning ({source_file.name}:{row_number}): invalid amount "
            f"{amount_raw!r}"
        )

    if amount_native == Decimal("0"):
        return None, None

    description = _compose_description(payee_raw, memo_raw)
    if not description:
        return None, (f"HSBC CSV parse warning ({source_file.name}:{row_number}): empty payee/memo")

    return (
        Transaction(
            booking_date=booking_date,
            description=description,
            amount_native=amount_native,
            currency="GBP",
            source_file=source_file,
            bank="HSBC",
            parser="hsbc_csv",
            account_label=account_raw,
        ),
        None,
    )


def load_hsbc_csv_transactions(csv_files: list[Path]) -> HsbcCsvImportResult:
    """Load normalized HSBC transactions from CSV files."""
    warnings: list[str] = []
    transactions: list[Transaction] = []

    for csv_path in csv_files:
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = tuple(reader.fieldnames or ())
                if any(column not in headers for column in _REQUIRED_COLUMNS):
                    warnings.append(
                        f"HSBC CSV parse warning ({csv_path.name}): missing required columns "
                        f"{_REQUIRED_COLUMNS}"
                    )
                    continue

                for row_index, row in enumerate(reader, start=2):
                    transaction, warning = _parse_row(
                        row=row,
                        source_file=csv_path,
                        row_number=row_index,
                    )
                    if warning is not None:
                        warnings.append(warning)
                    if transaction is not None:
                        transactions.append(transaction)
        except Exception as exc:
            warnings.append(f"Failed to process HSBC CSV {csv_path}: {exc}")

    return HsbcCsvImportResult(
        transactions=transactions,
        warnings=warnings,
        files_scanned=len(csv_files),
    )

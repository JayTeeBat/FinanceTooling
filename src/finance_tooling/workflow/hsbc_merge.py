"""HSBC merge stage for PDF-only source selection and validation."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.workflow.ingest import extract_statement_date
from finance_tooling.workflow.types import HsbcMergeResult, HsbcSelectionDiagnostic


def hsbc_pdf_paths_by_date(source_files: list[Path]) -> dict[str, Path]:
    """Map HSBC PDF statement date to canonical source path."""
    paths_by_date: dict[str, Path] = {}
    for source_file in sorted(source_files):
        if "hsbc" not in source_file.name.lower():
            continue
        statement_date = extract_statement_date(source_file)
        if statement_date is None:
            continue
        paths_by_date.setdefault(statement_date, source_file)
    return paths_by_date


def hsbc_pdf_validations_by_date(
    validations: list[StatementValidation],
) -> dict[str, StatementValidation]:
    """Map HSBC validation records by statement date token."""
    by_date: dict[str, StatementValidation] = {}
    for validation in validations:
        if validation.bank.strip().upper() != "HSBC":
            continue
        statement_date = extract_statement_date(validation.source_file)
        if statement_date is None:
            continue
        by_date[statement_date] = validation
    return by_date


def hsbc_balance_warning(
    *,
    source_file: Path,
    opening_balance: Decimal,
    transaction_sum: Decimal,
    expected_closing_balance: Decimal,
    closing_balance: Decimal,
    difference: Decimal,
    pdf_abs_difference: Decimal | None = None,
) -> str:
    """Build balance mismatch warning for PDF-only HSBC mode."""
    suffix = ""
    if pdf_abs_difference is not None:
        suffix = f"; pdf_abs_diff={pdf_abs_difference}"
    return (
        f"{source_file.name}: HSBC hsbc reconciliation mismatch opening "
        f"{opening_balance} + selected transactions {transaction_sum} = "
        f"{expected_closing_balance} but closing is {closing_balance} (diff {difference}{suffix})"
    )


def merge_hsbc_sources(
    transactions: list[Transaction],
    validations: list[StatementValidation],
    source_files: list[Path],
    hsbc_statement_periods_by_date: dict[str, tuple[date, date]],
) -> HsbcMergeResult:
    """Validate HSBC data in PDF-only mode and emit diagnostics/metrics."""
    merged: list[Transaction] = []
    warnings: list[str] = []
    selection_diagnostics: list[HsbcSelectionDiagnostic] = []

    # Keep legacy metric keys for summary compatibility; CSV-related counters remain zero.
    metrics: dict[str, int] = {
        "hsbc_csv_statement_replaced_count": 0,
        "hsbc_pdf_fallback_statement_count": 0,
        "hsbc_csv_only_statement_count": 0,
        "hsbc_pdf_balance_validated_count": 0,
        "hsbc_pdf_balance_validation_fail_count": 0,
        "hsbc_adaptive_source_switch_count": 0,
        "hsbc_selected_csv_month_count": 0,
        "hsbc_selected_pdf_month_count": 0,
        "hsbc_period_remap_applied_month_count": 0,
        "hsbc_period_remap_reassigned_tx_count": 0,
        "hsbc_period_remap_unassigned_csv_tx_count": 0,
    }

    hsbc_rows_by_date: dict[str, list[Transaction]] = defaultdict(list)
    hsbc_undated_transactions: list[Transaction] = []
    csv_tagged_transaction_count = 0

    for transaction in transactions:
        if transaction.bank.strip().upper() != "HSBC":
            merged.append(transaction)
            continue

        if transaction.parser == "hsbc_csv":
            csv_tagged_transaction_count += 1

        statement_date = extract_statement_date(transaction.source_file)
        if statement_date is None:
            hsbc_undated_transactions.append(transaction)
            continue
        hsbc_rows_by_date[statement_date].append(transaction)

    if csv_tagged_transaction_count > 0:
        warnings.append(
            "HSBC PDF-only mode warning: "
            f"{csv_tagged_transaction_count} transaction(s) tagged hsbc_csv were retained "
            "without CSV source selection"
        )

    hsbc_pdf_paths = hsbc_pdf_paths_by_date(source_files)
    hsbc_pdf_validations = hsbc_pdf_validations_by_date(validations)
    all_hsbc_statement_dates = sorted(set(hsbc_rows_by_date) | set(hsbc_pdf_validations))

    for statement_date in all_hsbc_statement_dates:
        selected_rows = hsbc_rows_by_date.get(statement_date, [])
        if selected_rows:
            merged.extend(selected_rows)
            metrics["hsbc_pdf_fallback_statement_count"] += 1
            metrics["hsbc_selected_pdf_month_count"] += 1

        selected_sum = sum((row.amount_native for row in selected_rows), start=Decimal("0"))
        pdf_validation = hsbc_pdf_validations.get(statement_date)
        has_pdf_balance_validation = (
            pdf_validation is not None
            and pdf_validation.opening_balance is not None
            and pdf_validation.closing_balance is not None
        )
        pdf_abs_difference: Decimal | None = None
        if has_pdf_balance_validation and pdf_validation is not None:
            opening = pdf_validation.opening_balance
            closing = pdf_validation.closing_balance
            if opening is not None and closing is not None:
                pdf_abs_difference = abs(opening + selected_sum - closing)

        selection_diagnostics.append(
            {
                "statement_date": statement_date,
                "selected_source": "hsbc",
                "csv_transaction_count": 0,
                "pdf_transaction_count": len(selected_rows),
                "csv_transaction_sum": "0",
                "pdf_transaction_sum": str(selected_sum),
                "selected_transaction_sum": str(selected_sum),
                "csv_abs_difference": None,
                "pdf_abs_difference": (
                    float(pdf_abs_difference) if pdf_abs_difference is not None else None
                ),
                "has_pdf_balance_validation": has_pdf_balance_validation,
                "statement_period_start": (
                    hsbc_statement_periods_by_date[statement_date][0].isoformat()
                    if statement_date in hsbc_statement_periods_by_date
                    else None
                ),
                "statement_period_end": (
                    hsbc_statement_periods_by_date[statement_date][1].isoformat()
                    if statement_date in hsbc_statement_periods_by_date
                    else None
                ),
            }
        )

    if hsbc_undated_transactions:
        merged.extend(hsbc_undated_transactions)
        warnings.append(
            "HSBC source merge warning: "
            f"{len(hsbc_undated_transactions)} transaction(s) had no statement date in source file "
            "name; kept unchanged"
        )

    non_hsbc_validations: list[StatementValidation] = []
    hsbc_undated_validations: list[StatementValidation] = []
    for validation in validations:
        if validation.bank.strip().upper() != "HSBC":
            non_hsbc_validations.append(validation)
            continue
        if extract_statement_date(validation.source_file) is None:
            hsbc_undated_validations.append(validation)

    merged_validations: list[StatementValidation] = [
        *non_hsbc_validations,
        *hsbc_undated_validations,
    ]
    if hsbc_undated_validations:
        warnings.append(
            "HSBC source merge warning: "
            f"{len(hsbc_undated_validations)} validation record(s) had no statement date and were "
            "kept unchanged"
        )

    for statement_date in all_hsbc_statement_dates:
        selected_rows = hsbc_rows_by_date.get(statement_date, [])
        transaction_sum = sum((row.amount_native for row in selected_rows), start=Decimal("0"))
        pdf_validation = hsbc_pdf_validations.get(statement_date)
        fallback_source_file = hsbc_pdf_paths.get(statement_date)
        if fallback_source_file is None and selected_rows:
            fallback_source_file = selected_rows[0].source_file
        if fallback_source_file is None:
            continue

        if (
            pdf_validation is None
            or pdf_validation.opening_balance is None
            or pdf_validation.closing_balance is None
        ):
            reason = (
                "missing_pdf_balance_statement"
                if pdf_validation is None
                else (pdf_validation.reason or "missing_opening_or_closing")
            )
            merged_validations.append(
                StatementValidation(
                    source_file=fallback_source_file,
                    bank="HSBC",
                    parser="hsbc",
                    statement_type="statement",
                    opening_balance=pdf_validation.opening_balance if pdf_validation else None,
                    closing_balance=pdf_validation.closing_balance if pdf_validation else None,
                    transaction_sum=transaction_sum,
                    expected_closing_balance=None,
                    difference=None,
                    status="uncheckable",
                    reason=reason,
                    severity="info",
                )
            )
            continue

        opening_balance = pdf_validation.opening_balance
        closing_balance = pdf_validation.closing_balance
        expected_closing_balance = opening_balance + transaction_sum
        difference = expected_closing_balance - closing_balance
        status = "pass"
        reason: str | None = None
        severity = "none"
        metrics["hsbc_pdf_balance_validated_count"] += 1

        if abs(difference) > Decimal("0.01"):
            status = "fail"
            reason = "balance_mismatch"
            severity = "warning"
            metrics["hsbc_pdf_balance_validation_fail_count"] += 1
            warnings.append(
                hsbc_balance_warning(
                    source_file=pdf_validation.source_file,
                    opening_balance=opening_balance,
                    transaction_sum=transaction_sum,
                    expected_closing_balance=expected_closing_balance,
                    closing_balance=closing_balance,
                    difference=difference,
                    pdf_abs_difference=abs(difference),
                )
            )

        merged_validations.append(
            StatementValidation(
                source_file=pdf_validation.source_file,
                bank="HSBC",
                parser="hsbc",
                statement_type=pdf_validation.statement_type,
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                transaction_sum=transaction_sum,
                expected_closing_balance=expected_closing_balance,
                difference=difference,
                status=status,
                reason=reason,
                severity=severity,
            )
        )

    return HsbcMergeResult(
        transactions=merged,
        validations=merged_validations,
        warnings=warnings,
        metrics=metrics,
        selection_diagnostics=selection_diagnostics,
    )

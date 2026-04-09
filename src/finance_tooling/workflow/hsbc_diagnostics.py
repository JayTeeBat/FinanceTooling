"""HSBC diagnostics derived directly from parser-owned outputs."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from finance_tooling.core.models import Transaction
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.workflow.ingest import extract_statement_date
from finance_tooling.workflow.types import HsbcDiagnosticsResult, HsbcSelectionDiagnostic


def default_hsbc_metrics() -> dict[str, int]:
    """Return the stable HSBC diagnostics metric payload."""
    return {
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


def analyze_hsbc_parser_outputs(
    transactions: list[Transaction],
    validations: list[StatementValidation],
    hsbc_statement_periods_by_date: dict[str, tuple[date, date]],
) -> HsbcDiagnosticsResult:
    """Build HSBC selection/validation diagnostics without a second merge pass."""
    metrics = default_hsbc_metrics()
    warnings: list[str] = []
    selection_diagnostics: list[HsbcSelectionDiagnostic] = []

    hsbc_rows_by_date: dict[str, list[Transaction]] = defaultdict(list)
    hsbc_undated_transactions = 0
    csv_tagged_transaction_count = 0

    for transaction in transactions:
        if transaction.bank.strip().upper() != "HSBC":
            continue
        if transaction.parser == "hsbc_csv":
            csv_tagged_transaction_count += 1
        statement_date = extract_statement_date(transaction.source_file)
        if statement_date is None:
            hsbc_undated_transactions += 1
            continue
        hsbc_rows_by_date[statement_date].append(transaction)

    hsbc_validations_by_date: dict[str, StatementValidation] = {}
    hsbc_undated_validations = 0
    for validation in validations:
        if validation.bank.strip().upper() != "HSBC":
            continue
        statement_date = extract_statement_date(validation.source_file)
        if statement_date is None:
            hsbc_undated_validations += 1
            continue
        hsbc_validations_by_date[statement_date] = validation

    if csv_tagged_transaction_count > 0:
        warnings.append(
            "HSBC diagnostics warning: "
            f"{csv_tagged_transaction_count} transaction(s) tagged hsbc_csv were emitted "
            "by the parser path"
        )
    if hsbc_undated_transactions > 0:
        warnings.append(
            "HSBC diagnostics warning: "
            f"{hsbc_undated_transactions} transaction(s) had no statement date in the source file "
            "name"
        )
    if hsbc_undated_validations > 0:
        warnings.append(
            "HSBC diagnostics warning: "
            f"{hsbc_undated_validations} validation record(s) had no statement date in the "
            "source file name"
        )

    all_statement_dates = sorted(set(hsbc_rows_by_date) | set(hsbc_validations_by_date))
    for statement_date in all_statement_dates:
        selected_rows = hsbc_rows_by_date.get(statement_date, [])
        transaction_sum = sum((row.amount_native for row in selected_rows), start=Decimal("0"))
        validation = hsbc_validations_by_date.get(statement_date)
        if selected_rows:
            metrics["hsbc_pdf_fallback_statement_count"] += 1
            metrics["hsbc_selected_pdf_month_count"] += 1
        if (
            validation is not None
            and validation.opening_balance is not None
            and validation.closing_balance is not None
        ):
            metrics["hsbc_pdf_balance_validated_count"] += 1
            if validation.status == "fail":
                metrics["hsbc_pdf_balance_validation_fail_count"] += 1
        selection_diagnostics.append(
            {
                "statement_date": statement_date,
                "selected_source": "hsbc",
                "csv_transaction_count": 0,
                "pdf_transaction_count": len(selected_rows),
                "csv_transaction_sum": "0",
                "pdf_transaction_sum": str(transaction_sum),
                "selected_transaction_sum": str(transaction_sum),
                "csv_abs_difference": None,
                "pdf_abs_difference": (
                    float(abs(validation.difference))
                    if validation is not None and validation.difference is not None
                    else None
                ),
                "has_pdf_balance_validation": (
                    validation is not None
                    and validation.opening_balance is not None
                    and validation.closing_balance is not None
                ),
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

    return HsbcDiagnosticsResult(
        warnings=warnings,
        metrics=metrics,
        selection_diagnostics=selection_diagnostics,
    )

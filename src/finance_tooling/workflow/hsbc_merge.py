"""HSBC merge stage combining PDF/CVS transaction sources."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
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
    selected_source: str,
    opening_balance: Decimal,
    transaction_sum: Decimal,
    expected_closing_balance: Decimal,
    closing_balance: Decimal,
    difference: Decimal,
    csv_abs_difference: Decimal | None = None,
    pdf_abs_difference: Decimal | None = None,
) -> str:
    """Build balance mismatch warning with source-comparison context."""
    suffix = ""
    if csv_abs_difference is not None and pdf_abs_difference is not None:
        suffix = f"; candidate_abs_diff csv={csv_abs_difference} pdf={pdf_abs_difference}"
    return (
        f"{source_file.name}: HSBC {selected_source} reconciliation mismatch opening "
        f"{opening_balance} + selected transactions {transaction_sum} = "
        f"{expected_closing_balance} but closing is {closing_balance} (diff {difference}{suffix})"
    )


def assign_hsbc_csv_transactions_to_statement_dates(
    csv_transactions: list[Transaction],
    statement_periods_by_date: dict[str, tuple[date, date]],
) -> tuple[dict[str, list[Transaction]], list[Transaction], dict[str, int]]:
    """Assign HSBC CSV rows to statement months using parsed statement periods."""
    assigned: dict[str, list[Transaction]] = defaultdict(list)
    unassigned: list[Transaction] = []
    metrics = {
        "hsbc_period_remap_reassigned_tx_count": 0,
        "hsbc_period_remap_unassigned_csv_tx_count": 0,
    }

    period_items = sorted(statement_periods_by_date.items(), key=lambda item: item[0])
    for transaction in csv_transactions:
        matching_dates: list[str] = []
        for statement_date, (period_start, period_end) in period_items:
            if period_start <= transaction.booking_date <= period_end:
                matching_dates.append(statement_date)

        target_statement_date: str | None = None
        if len(matching_dates) == 1:
            target_statement_date = matching_dates[0]
        elif len(matching_dates) > 1:
            target_statement_date = min(
                matching_dates,
                key=lambda statement_date: abs(
                    (statement_periods_by_date[statement_date][1] - transaction.booking_date).days
                ),
            )

        if target_statement_date is None:
            fallback_statement_date = extract_statement_date(transaction.source_file)
            if fallback_statement_date is not None:
                target_statement_date = fallback_statement_date

        if target_statement_date is None:
            unassigned.append(transaction)
            continue

        if extract_statement_date(transaction.source_file) != target_statement_date:
            metrics["hsbc_period_remap_reassigned_tx_count"] += 1
        assigned[target_statement_date].append(transaction)

    metrics["hsbc_period_remap_unassigned_csv_tx_count"] = len(unassigned)
    return dict(assigned), unassigned, metrics


def merge_hsbc_sources(
    transactions: list[Transaction],
    validations: list[StatementValidation],
    source_files: list[Path],
    hsbc_statement_periods_by_date: dict[str, tuple[date, date]],
) -> HsbcMergeResult:
    """Apply HSBC adaptive source merge and emit updated validations/metrics."""
    merged: list[Transaction] = []
    warnings: list[str] = []
    selection_diagnostics: list[HsbcSelectionDiagnostic] = []

    metrics = {
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

    raw_hsbc_csv_transactions: list[Transaction] = []
    hsbc_pdf_by_date: dict[str, list[Transaction]] = defaultdict(list)
    hsbc_undated_transactions: list[Transaction] = []

    for transaction in transactions:
        if transaction.bank.strip().upper() != "HSBC":
            merged.append(transaction)
            continue

        statement_date = extract_statement_date(transaction.source_file)
        if statement_date is None:
            hsbc_undated_transactions.append(transaction)
            continue

        if transaction.parser == "hsbc_csv":
            raw_hsbc_csv_transactions.append(transaction)
        else:
            hsbc_pdf_by_date[statement_date].append(transaction)

    hsbc_csv_by_date, unassigned_hsbc_csv_transactions, remap_metrics = (
        assign_hsbc_csv_transactions_to_statement_dates(
            raw_hsbc_csv_transactions,
            hsbc_statement_periods_by_date,
        )
    )
    metrics["hsbc_period_remap_applied_month_count"] = len(hsbc_statement_periods_by_date)
    metrics["hsbc_period_remap_reassigned_tx_count"] = remap_metrics[
        "hsbc_period_remap_reassigned_tx_count"
    ]
    metrics["hsbc_period_remap_unassigned_csv_tx_count"] = remap_metrics[
        "hsbc_period_remap_unassigned_csv_tx_count"
    ]

    if unassigned_hsbc_csv_transactions:
        merged.extend(unassigned_hsbc_csv_transactions)
        warnings.append(
            "HSBC period remap warning: "
            f"{len(unassigned_hsbc_csv_transactions)} CSV transaction(s) could not be assigned to "
            "a statement month and were kept unchanged"
        )

    hsbc_pdf_paths = hsbc_pdf_paths_by_date(source_files)
    hsbc_pdf_validations = hsbc_pdf_validations_by_date(validations)

    selected_by_date: dict[str, list[Transaction]] = {}
    selected_source_by_date: dict[str, str] = {}
    all_hsbc_statement_dates = sorted(
        set(hsbc_csv_by_date) | set(hsbc_pdf_by_date) | set(hsbc_pdf_validations)
    )

    for statement_date in all_hsbc_statement_dates:
        csv_rows = hsbc_csv_by_date.get(statement_date, [])
        pdf_rows = hsbc_pdf_by_date.get(statement_date, [])
        pdf_validation = hsbc_pdf_validations.get(statement_date)
        has_pdf_balance_validation = (
            pdf_validation is not None
            and pdf_validation.opening_balance is not None
            and pdf_validation.closing_balance is not None
        )
        csv_sum = sum((row.amount_native for row in csv_rows), start=Decimal("0"))
        pdf_sum = sum((row.amount_native for row in pdf_rows), start=Decimal("0"))
        csv_abs_difference: Decimal | None = None
        pdf_abs_difference: Decimal | None = None
        if has_pdf_balance_validation and pdf_validation is not None:
            opening = pdf_validation.opening_balance
            closing = pdf_validation.closing_balance
            if opening is not None and closing is not None:
                csv_abs_difference = abs(opening + csv_sum - closing)
                pdf_abs_difference = abs(opening + pdf_sum - closing)

        if csv_rows and pdf_rows:
            selected_source = "hsbc_csv"
            if (
                csv_abs_difference is not None
                and pdf_abs_difference is not None
                and pdf_abs_difference < csv_abs_difference
            ):
                selected_source = "hsbc"
                metrics["hsbc_adaptive_source_switch_count"] += 1

            if selected_source == "hsbc_csv":
                source_file = hsbc_pdf_paths.get(statement_date)
                if source_file is None and pdf_validation is not None:
                    source_file = pdf_validation.source_file
                if source_file is None:
                    selected_rows = csv_rows
                else:
                    selected_rows = [
                        replace(transaction, source_file=source_file) for transaction in csv_rows
                    ]
                metrics["hsbc_csv_statement_replaced_count"] += 1
                metrics["hsbc_selected_csv_month_count"] += 1
            else:
                selected_rows = pdf_rows
                metrics["hsbc_selected_pdf_month_count"] += 1
            selected_source_by_date[statement_date] = selected_source
            selected_by_date[statement_date] = selected_rows
            merged.extend(selected_rows)
        elif pdf_rows:
            selected_source_by_date[statement_date] = "hsbc"
            metrics["hsbc_pdf_fallback_statement_count"] += 1
            metrics["hsbc_selected_pdf_month_count"] += 1
            selected_by_date[statement_date] = pdf_rows
            merged.extend(pdf_rows)
        elif csv_rows:
            selected_source_by_date[statement_date] = "hsbc_csv"
            metrics["hsbc_csv_only_statement_count"] += 1
            metrics["hsbc_selected_csv_month_count"] += 1
            selected_by_date[statement_date] = csv_rows
            merged.extend(csv_rows)

        selected_rows_for_diag = selected_by_date.get(statement_date, [])
        selected_sum = sum(
            (row.amount_native for row in selected_rows_for_diag),
            start=Decimal("0"),
        )
        selection_diagnostics.append(
            {
                "statement_date": statement_date,
                "selected_source": selected_source_by_date.get(statement_date, "none"),
                "csv_transaction_count": len(csv_rows),
                "pdf_transaction_count": len(pdf_rows),
                "csv_transaction_sum": str(csv_sum),
                "pdf_transaction_sum": str(pdf_sum),
                "selected_transaction_sum": str(selected_sum),
                "csv_abs_difference": (
                    float(csv_abs_difference) if csv_abs_difference is not None else None
                ),
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

    merged_validations: list[StatementValidation] = list(non_hsbc_validations)
    merged_validations.extend(hsbc_undated_validations)
    if hsbc_undated_validations:
        warnings.append(
            "HSBC source merge warning: "
            f"{len(hsbc_undated_validations)} validation record(s) had no statement date and were "
            "kept unchanged"
        )

    for statement_date in all_hsbc_statement_dates:
        selected_rows = selected_by_date.get(statement_date, [])
        selected_source = selected_source_by_date.get(statement_date, "hsbc")
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
                    parser=selected_source,
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
            csv_rows = hsbc_csv_by_date.get(statement_date, [])
            pdf_rows = hsbc_pdf_by_date.get(statement_date, [])
            csv_sum = sum((row.amount_native for row in csv_rows), start=Decimal("0"))
            pdf_sum = sum((row.amount_native for row in pdf_rows), start=Decimal("0"))
            csv_abs_difference = abs(opening_balance + csv_sum - closing_balance)
            pdf_abs_difference = abs(opening_balance + pdf_sum - closing_balance)
            warnings.append(
                hsbc_balance_warning(
                    source_file=pdf_validation.source_file,
                    selected_source=selected_source,
                    opening_balance=opening_balance,
                    transaction_sum=transaction_sum,
                    expected_closing_balance=expected_closing_balance,
                    closing_balance=closing_balance,
                    difference=difference,
                    csv_abs_difference=csv_abs_difference,
                    pdf_abs_difference=pdf_abs_difference,
                )
            )

        merged_validations.append(
            StatementValidation(
                source_file=pdf_validation.source_file,
                bank="HSBC",
                parser=selected_source,
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

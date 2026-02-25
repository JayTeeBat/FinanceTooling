"""Workflow orchestration for scanning, extracting, classifying, and reporting."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from tqdm import tqdm

from finance_tooling.classify import classify_transactions
from finance_tooling.completeness import build_completeness_report
from finance_tooling.config import Settings
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.extract import extract_text_from_pdf
from finance_tooling.fx import ensure_fx_cache, resolve_rate
from finance_tooling.importers import load_hsbc_csv_transactions
from finance_tooling.models import Transaction, WorkflowResult
from finance_tooling.parsers import select_parser_with_diagnostics
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.scanner import discover_csv_files, discover_statement_pdfs
from finance_tooling.store import upsert_transactions

_HSBC_STATEMENT_DATE_PATTERN = re.compile(r"(?:19|20)\d{2}-\d{2}-\d{2}")
_HSBC_STATEMENT_PERIOD_PATTERN = re.compile(
    r"(?P<start_day>\d{1,2})\s+"
    r"(?P<start_month>[A-Za-z]+)"
    r"(?:\s*(?P<start_year>\d{4}))?"
    r"\s*to\s*"
    r"(?P<end_day>\d{1,2})\s+"
    r"(?P<end_month>[A-Za-z]+)"
    r"\s*(?P<end_year>\d{4})",
    re.IGNORECASE,
)
_HSBC_STATEMENT_PERIOD_VARIANT_PATTERN = re.compile(r"[A-Za-z]+to|[A-Za-z]+\d{4}")


def _apply_fx_and_mtime(
    transactions: list[Transaction], settings: Settings
) -> tuple[list[Transaction], list[str]]:
    enriched: list[Transaction] = []
    warnings: list[str] = []

    cache, cache_warnings = ensure_fx_cache(
        settings.fx_cache_path,
        transactions,
        base_currency=settings.base_currency,
        auto_fetch=settings.fx_auto_fetch,
    )
    warnings.extend(cache_warnings)

    for tx in transactions:
        currency = tx.currency.upper()
        amount_eur: Decimal | None = None
        fx_rate: Decimal | None = None
        fx_rate_date = None
        fx_source = None

        resolution = resolve_rate(
            cache,
            currency=currency,
            booking_date=tx.booking_date,
            base_currency=settings.base_currency,
        )
        if resolution is None:
            warnings.append(
                "Missing dated FX rate for currency "
                f"{currency} on or before {tx.booking_date} ({tx.source_file.name}); "
                "converted metrics will skip this row"
            )
        else:
            fx_rate = resolution.rate_to_eur
            fx_rate_date = resolution.rate_date
            fx_source = resolution.source
            amount_eur = tx.amount_native * resolution.rate_to_eur

        mtime = datetime.fromtimestamp(tx.source_file.stat().st_mtime, tz=UTC)
        enriched.append(
            replace(
                tx,
                currency=currency,
                fx_rate_to_eur=fx_rate,
                fx_rate_date=fx_rate_date,
                fx_source=fx_source,
                amount_eur=amount_eur,
                source_file_mtime=mtime,
            )
        )

    return enriched, warnings


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _extract_statement_date(path: Path) -> str | None:
    match = _HSBC_STATEMENT_DATE_PATTERN.search(path.name)
    if match is None:
        return None
    return match.group(0)


def _parse_hsbc_statement_period(full_text: str) -> tuple[date, date] | None:
    flattened = " ".join(full_text.split())
    match = _HSBC_STATEMENT_PERIOD_PATTERN.search(flattened)
    if match is None:
        return None

    start_day = match.group("start_day")
    start_month = match.group("start_month")
    start_year = match.group("start_year")
    end_day = match.group("end_day")
    end_month = match.group("end_month")
    end_year = int(match.group("end_year"))

    end_date: date | None = None
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            end_date = datetime.strptime(f"{end_day} {end_month} {end_year}", fmt).date()
            break
        except ValueError:
            continue
    if end_date is None:
        return None

    start_date: date | None = None
    candidate_years = [int(start_year)] if start_year is not None else [end_year, end_year - 1]
    for candidate_year in candidate_years:
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                candidate = datetime.strptime(
                    f"{start_day} {start_month} {candidate_year}",
                    fmt,
                ).date()
            except ValueError:
                continue
            if candidate <= end_date:
                start_date = candidate
                break
        if start_date is not None:
            break

    if start_date is None:
        return None
    return start_date, end_date


def _hsbc_statement_period_uses_spacing_variant(full_text: str) -> bool:
    flattened = " ".join(full_text.split())
    return _HSBC_STATEMENT_PERIOD_VARIANT_PATTERN.search(flattened) is not None


def _hsbc_pdf_paths_by_date(source_files: list[Path]) -> dict[str, Path]:
    paths_by_date: dict[str, Path] = {}
    for source_file in sorted(source_files):
        if "hsbc" not in source_file.name.lower():
            continue
        statement_date = _extract_statement_date(source_file)
        if statement_date is None:
            continue
        paths_by_date.setdefault(statement_date, source_file)
    return paths_by_date


def _hsbc_pdf_validations_by_date(
    validations: list[StatementValidation],
) -> dict[str, StatementValidation]:
    by_date: dict[str, StatementValidation] = {}
    for validation in validations:
        if validation.bank.strip().upper() != "HSBC":
            continue
        statement_date = _extract_statement_date(validation.source_file)
        if statement_date is None:
            continue
        by_date[statement_date] = validation
    return by_date


def _hsbc_balance_warning(
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
    suffix = ""
    if csv_abs_difference is not None and pdf_abs_difference is not None:
        suffix = f"; candidate_abs_diff csv={csv_abs_difference} pdf={pdf_abs_difference}"
    return (
        f"{source_file.name}: HSBC {selected_source} reconciliation mismatch opening "
        f"{opening_balance} + selected transactions {transaction_sum} = "
        f"{expected_closing_balance} but closing is {closing_balance} (diff {difference}{suffix})"
    )


def _assign_hsbc_csv_transactions_to_statement_dates(
    csv_transactions: list[Transaction],
    statement_periods_by_date: dict[str, tuple[date, date]],
) -> tuple[dict[str, list[Transaction]], list[Transaction], dict[str, int]]:
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
            fallback_statement_date = _extract_statement_date(transaction.source_file)
            if fallback_statement_date is not None:
                target_statement_date = fallback_statement_date

        if target_statement_date is None:
            unassigned.append(transaction)
            continue

        if _extract_statement_date(transaction.source_file) != target_statement_date:
            metrics["hsbc_period_remap_reassigned_tx_count"] += 1
        assigned[target_statement_date].append(transaction)

    metrics["hsbc_period_remap_unassigned_csv_tx_count"] = len(unassigned)
    return dict(assigned), unassigned, metrics


def _merge_hsbc_sources(
    transactions: list[Transaction],
    validations: list[StatementValidation],
    source_files: list[Path],
    hsbc_statement_periods_by_date: dict[str, tuple[date, date]],
) -> tuple[
    list[Transaction],
    list[StatementValidation],
    list[str],
    dict[str, int],
    list[dict[str, object]],
]:
    merged: list[Transaction] = []
    warnings: list[str] = []
    selection_diagnostics: list[dict[str, object]] = []

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

        statement_date = _extract_statement_date(transaction.source_file)
        if statement_date is None:
            hsbc_undated_transactions.append(transaction)
            continue

        if transaction.parser == "hsbc_csv":
            raw_hsbc_csv_transactions.append(transaction)
        else:
            hsbc_pdf_by_date[statement_date].append(transaction)

    hsbc_csv_by_date, unassigned_hsbc_csv_transactions, remap_metrics = (
        _assign_hsbc_csv_transactions_to_statement_dates(
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

    hsbc_pdf_paths = _hsbc_pdf_paths_by_date(source_files)
    hsbc_pdf_validations = _hsbc_pdf_validations_by_date(validations)

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
            # Types narrowed by has_pdf_balance_validation.
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
        if _extract_statement_date(validation.source_file) is None:
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
                _hsbc_balance_warning(
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

    return merged, merged_validations, warnings, metrics, selection_diagnostics


def run_workflow(settings: Settings) -> WorkflowResult:
    """Execute the full finance statement workflow."""
    warnings: list[str] = []
    files_failed = 0
    extracted: list[Transaction] = []
    validations: list[StatementValidation] = []
    parser_selection_diagnostics: list[dict[str, object]] = []
    parser_low_confidence_file_count = 0
    hsbc_csv_files_scanned = 0
    hsbc_period_parse_variant_match_count = 0
    hsbc_statement_periods_by_date: dict[str, tuple[date, date]] = {}
    hsbc_merge_metrics = {
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
    hsbc_selection_diagnostics: list[dict[str, object]] = []

    files = discover_statement_pdfs(settings.input_path)
    progress = tqdm(
        files,
        desc="Processing statements",
        unit="file",
        disable=not sys.stderr.isatty(),
    )
    for pdf_path in progress:
        try:
            extracted_text = extract_text_from_pdf(pdf_path)
            selection = select_parser_with_diagnostics(pdf_path, extracted_text.first_page_text)
            parser = selection.parser
            top_candidates = [
                {"parser": item.parser_name, "score": item.score}
                for item in selection.candidates[:3]
            ]
            parser_selection_diagnostics.append(
                {
                    "source_file": str(pdf_path),
                    "selected_parser": parser.name,
                    "selected_score": selection.score,
                    "threshold": selection.threshold,
                    "top_candidates": top_candidates,
                }
            )
            is_low_confidence = selection.score <= selection.threshold
            is_ambiguous_tie = (
                len(selection.candidates) > 1
                and selection.candidates[0].score == selection.candidates[1].score
            )
            if is_low_confidence or is_ambiguous_tie:
                parser_low_confidence_file_count += 1
                warnings.append(
                    f"Low-confidence parser selection for {pdf_path.name}: selected "
                    f"{parser.name} (score={selection.score}, threshold={selection.threshold})"
                )
            output = parser.parse(pdf_path, extracted_text.full_text)
            extracted.extend(output.transactions)
            warnings.extend(output.warnings)
            if output.validation is not None:
                validations.append(output.validation)
            if parser.name == "hsbc":
                statement_date = _extract_statement_date(pdf_path)
                statement_period = _parse_hsbc_statement_period(extracted_text.full_text)
                if statement_date is not None and statement_period is not None:
                    hsbc_statement_periods_by_date[statement_date] = statement_period
                    if _hsbc_statement_period_uses_spacing_variant(extracted_text.full_text):
                        hsbc_period_parse_variant_match_count += 1
        except Exception as exc:
            files_failed += 1
            warnings.append(f"Failed to process {pdf_path}: {exc}")

    if settings.hsbc_csv_path is not None:
        hsbc_csv_files = discover_csv_files(settings.hsbc_csv_path)
        csv_import_result = load_hsbc_csv_transactions(hsbc_csv_files)
        hsbc_csv_files_scanned = csv_import_result.files_scanned
        extracted.extend(csv_import_result.transactions)
        warnings.extend(csv_import_result.warnings)

    extracted, validations, hsbc_merge_warnings, hsbc_merge_metrics, hsbc_selection_diagnostics = (
        _merge_hsbc_sources(
            extracted,
            validations,
            files,
            hsbc_statement_periods_by_date,
        )
    )
    warnings.extend(hsbc_merge_warnings)
    classified = classify_transactions(extracted)
    enriched, fx_warnings = _apply_fx_and_mtime(classified, settings)
    warnings.extend(fx_warnings)
    completeness_report = build_completeness_report(files, enriched, validations=validations)
    completeness_status = cast(str, completeness_report["status"])
    completeness_coverage_ratio = cast(float, completeness_report["file_coverage_ratio"])
    missing_source_file_count = cast(int, completeness_report["missing_source_file_count"])
    reconciliation = cast(dict[str, object], completeness_report["statement_reconciliation"])
    reconciliation_checkable_count = cast(int, reconciliation["checkable_file_count"])
    reconciliation_fail_count = cast(int, reconciliation["fail_count"])
    reconciliation_uncheckable_count = cast(int, reconciliation["uncheckable_file_count"])
    reconciliation_pass_ratio = cast(float | None, reconciliation["pass_ratio"])
    reconciliation_median_abs_difference = cast(
        float | None, reconciliation["median_abs_difference"]
    )
    by_bank_abs_difference = cast(list[dict[str, object]], reconciliation["by_bank_abs_difference"])
    hsbc_abs_difference = next(
        (
            cast(float | None, item.get("median_abs_difference"))
            for item in by_bank_abs_difference
            if cast(str, item.get("bank")) == "HSBC"
        ),
        None,
    )
    _write_json(settings.completeness_json_path, completeness_report)

    upsert = upsert_transactions(settings.master_parquet_path, enriched)

    settings.export_csv_path.parent.mkdir(parents=True, exist_ok=True)
    settings.export_json_path.parent.mkdir(parents=True, exist_ok=True)
    upsert.dataframe.to_csv(settings.export_csv_path, index=False)
    upsert.dataframe.to_json(settings.export_json_path, orient="records", indent=2)

    dashboard_path = render_dashboard_html(
        upsert.dataframe,
        settings.output_path,
        base_currency=settings.base_currency,
        files_scanned=len(files),
        files_failed=files_failed,
        new_rows=upsert.new_rows,
    )

    _write_json(
        settings.summary_json_path,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "files_scanned": len(files),
            "files_failed": files_failed,
            "transactions_parsed": len(enriched),
            "new_rows": upsert.new_rows,
            "total_rows": upsert.total_rows,
            "parquet_path": str(upsert.parquet_path),
            "dashboard_path": str(dashboard_path),
            "completeness_report_path": str(settings.completeness_json_path),
            "completeness_status": completeness_status,
            "file_coverage_ratio": completeness_coverage_ratio,
            "missing_source_file_count": missing_source_file_count,
            "statement_reconciliation_checkable_file_count": reconciliation_checkable_count,
            "statement_reconciliation_fail_count": reconciliation_fail_count,
            "statement_reconciliation_uncheckable_file_count": reconciliation_uncheckable_count,
            "statement_reconciliation_pass_ratio": reconciliation_pass_ratio,
            "statement_reconciliation_median_abs_difference": reconciliation_median_abs_difference,
            "statement_reconciliation_hsbc_median_abs_difference": hsbc_abs_difference,
            "parser_low_confidence_file_count": parser_low_confidence_file_count,
            "parser_selection_diagnostics": parser_selection_diagnostics,
            "hsbc_csv_files_scanned": hsbc_csv_files_scanned,
            "hsbc_csv_statement_replaced_count": hsbc_merge_metrics[
                "hsbc_csv_statement_replaced_count"
            ],
            "hsbc_pdf_fallback_statement_count": hsbc_merge_metrics[
                "hsbc_pdf_fallback_statement_count"
            ],
            "hsbc_csv_only_statement_count": hsbc_merge_metrics["hsbc_csv_only_statement_count"],
            "hsbc_pdf_balance_validated_count": hsbc_merge_metrics[
                "hsbc_pdf_balance_validated_count"
            ],
            "hsbc_pdf_balance_validation_fail_count": hsbc_merge_metrics[
                "hsbc_pdf_balance_validation_fail_count"
            ],
            "hsbc_selection_policy": "adaptive_reconciliation",
            "hsbc_adaptive_source_switch_count": hsbc_merge_metrics[
                "hsbc_adaptive_source_switch_count"
            ],
            "hsbc_selected_csv_month_count": hsbc_merge_metrics["hsbc_selected_csv_month_count"],
            "hsbc_selected_pdf_month_count": hsbc_merge_metrics["hsbc_selected_pdf_month_count"],
            "hsbc_period_remap_applied_month_count": hsbc_merge_metrics[
                "hsbc_period_remap_applied_month_count"
            ],
            "hsbc_period_remap_reassigned_tx_count": hsbc_merge_metrics[
                "hsbc_period_remap_reassigned_tx_count"
            ],
            "hsbc_period_remap_unassigned_csv_tx_count": hsbc_merge_metrics[
                "hsbc_period_remap_unassigned_csv_tx_count"
            ],
            "hsbc_period_parse_variant_match_count": hsbc_period_parse_variant_match_count,
            "hsbc_selection_diagnostics": hsbc_selection_diagnostics,
            "fx_cache_path": str(settings.fx_cache_path),
            "warnings": warnings,
        },
    )

    return WorkflowResult(
        dashboard_path=dashboard_path,
        parquet_path=upsert.parquet_path,
        csv_path=settings.export_csv_path,
        json_path=settings.export_json_path,
        summary_path=settings.summary_json_path,
        completeness_path=settings.completeness_json_path,
        files_scanned=len(files),
        files_failed=files_failed,
        transactions_parsed=len(enriched),
        new_rows=upsert.new_rows,
        total_rows=upsert.total_rows,
        completeness_status=completeness_status,
        completeness_coverage_ratio=completeness_coverage_ratio,
        missing_source_file_count=missing_source_file_count,
        reconciliation_checkable_file_count=reconciliation_checkable_count,
        reconciliation_fail_count=reconciliation_fail_count,
        reconciliation_uncheckable_file_count=reconciliation_uncheckable_count,
        reconciliation_pass_ratio=reconciliation_pass_ratio,
        warnings=tuple(warnings),
    )

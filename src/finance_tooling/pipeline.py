"""Workflow orchestration for scanning, extracting, classifying, and reporting."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from difflib import SequenceMatcher
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


def _normalize_description(description: str) -> str:
    normalized = " ".join(description.strip().lower().split())
    return normalized


def _source_priority(transaction: Transaction) -> int:
    # Higher priority wins on cross-source clashes.
    return 2 if transaction.parser == "hsbc_csv" else 1


def _transaction_resolution_key(transaction: Transaction) -> tuple[str, str, str, str, str]:
    account_label = (transaction.account_label or "").strip().lower()
    return (
        transaction.bank.strip().upper(),
        transaction.currency.strip().upper(),
        transaction.booking_date.isoformat(),
        str(transaction.amount_native),
        account_label,
    )


def _descriptions_similar(left: str, right: str) -> bool:
    left_normalized = _normalize_description(left)
    right_normalized = _normalize_description(right)
    if left_normalized == right_normalized:
        return True
    if left_normalized in right_normalized or right_normalized in left_normalized:
        return True
    similarity = SequenceMatcher(a=left_normalized, b=right_normalized).ratio()
    return similarity >= 0.6


def _resolve_cross_source_conflicts(
    transactions: list[Transaction],
) -> tuple[list[Transaction], list[str], dict[str, int]]:
    grouped: dict[tuple[str, str, str, str, str], list[Transaction]] = {}
    for transaction in transactions:
        grouped.setdefault(_transaction_resolution_key(transaction), []).append(transaction)

    kept: list[Transaction] = []
    warnings: list[str] = []
    duplicate_drop_count = 0
    clash_drop_count = 0

    for key in sorted(grouped):
        group = grouped[key]
        csv_rows = [transaction for transaction in group if transaction.parser == "hsbc_csv"]
        non_csv_rows = [transaction for transaction in group if transaction.parser != "hsbc_csv"]

        if not csv_rows or not non_csv_rows:
            kept.extend(group)
            continue

        kept.extend(csv_rows)

        remaining_csv_indices = set(range(len(csv_rows)))
        for transaction in non_csv_rows:
            matched_index: int | None = None
            for csv_index in sorted(remaining_csv_indices):
                if _descriptions_similar(transaction.description, csv_rows[csv_index].description):
                    matched_index = csv_index
                    break

            if matched_index is not None:
                duplicate_drop_count += 1
                continue

            clash_drop_count += 1
            warnings.append(
                "Conflict resolved in favor of HSBC CSV for "
                f"{transaction.booking_date} {transaction.amount_native} "
                f"({transaction.description!r} from {transaction.source_file.name})"
            )

    metrics = {
        "cross_source_duplicate_drop_count": duplicate_drop_count,
        "cross_source_clash_drop_count": clash_drop_count,
    }
    return kept, warnings, metrics


def run_workflow(settings: Settings) -> WorkflowResult:
    """Execute the full finance statement workflow."""
    warnings: list[str] = []
    files_failed = 0
    extracted: list[Transaction] = []
    validations: list[StatementValidation] = []
    parser_selection_diagnostics: list[dict[str, object]] = []
    parser_low_confidence_file_count = 0
    hsbc_csv_files_scanned = 0
    cross_source_metrics = {
        "cross_source_duplicate_drop_count": 0,
        "cross_source_clash_drop_count": 0,
    }

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
        except Exception as exc:
            files_failed += 1
            warnings.append(f"Failed to process {pdf_path}: {exc}")

    if settings.hsbc_csv_path is not None:
        hsbc_csv_files = discover_csv_files(settings.hsbc_csv_path)
        csv_import_result = load_hsbc_csv_transactions(hsbc_csv_files)
        hsbc_csv_files_scanned = csv_import_result.files_scanned
        extracted.extend(csv_import_result.transactions)
        warnings.extend(csv_import_result.warnings)

    extracted, clash_warnings, cross_source_metrics = _resolve_cross_source_conflicts(extracted)
    warnings.extend(clash_warnings)
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
            "cross_source_duplicate_drop_count": cross_source_metrics[
                "cross_source_duplicate_drop_count"
            ],
            "cross_source_clash_drop_count": cross_source_metrics["cross_source_clash_drop_count"],
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

"""Completeness reporting for statement ingestion coverage."""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import cast

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import StatementValidation

_DEFAULT_WARN_COVERAGE_RATIO = 0.90
_DEFAULT_FAIL_COVERAGE_RATIO = 0.70
_YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")
_NON_STATEMENT_HINTS = ("releve de frais", "relevé de frais", "/com-", " com-")


def classify_statement_type(file_path: Path) -> str:
    """Classify a source PDF as statement or non-statement."""
    marker = str(file_path).lower()
    if any(hint in marker for hint in _NON_STATEMENT_HINTS):
        return "non_statement"
    return "statement"


def guess_source_bank(file_path: Path) -> str:
    """Best-effort bank guess from source file path/name."""
    marker = str(file_path).lower()
    if "labanquepostale" in marker or "releve_ccp" in marker or "ccp" in marker:
        return "LaBanquePostale"
    if "boursobank" in marker or "boursorama" in marker:
        return "Boursobank"
    if "revolut" in marker:
        return "Revolut"
    if "hsbc" in marker:
        return "HSBC"
    return "Unknown"


def guess_source_year(file_path: Path) -> str:
    """Best-effort statement year extraction from file path/name."""
    match = _YEAR_PATTERN.search(str(file_path))
    if not match:
        return "unknown"
    return match.group(0)


def _sort_counter(counter: Counter[str]) -> dict[str, int]:
    def key(item: tuple[str, int]) -> tuple[int, str]:
        label = item[0]
        return (1, label) if label == "unknown" else (0, label)

    return {name: count for name, count in sorted(counter.items(), key=key)}


def _group_missing_by_year_and_bank(missing_files: list[Path]) -> list[dict[str, object]]:
    grouped: Counter[tuple[str, str]] = Counter()
    for file_path in missing_files:
        grouped[(guess_source_year(file_path), guess_source_bank(file_path))] += 1

    rows: list[dict[str, object]] = []
    for (year, bank_guess), count in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1])
    ):
        rows.append({"year": year, "bank_guess": bank_guess, "count": count})
    return rows


def build_completeness_report(
    source_files: list[Path],
    parsed_transactions: list[Transaction],
    validations: list[StatementValidation] | None = None,
    *,
    warn_coverage_ratio: float = _DEFAULT_WARN_COVERAGE_RATIO,
    fail_coverage_ratio: float = _DEFAULT_FAIL_COVERAGE_RATIO,
) -> dict[str, object]:
    """Build a machine-readable parsing completeness report."""
    validations_list = validations or []
    source_unique = sorted({Path(str(path)) for path in source_files}, key=lambda path: str(path))
    source_statement_unique = [
        path for path in source_unique if classify_statement_type(path) == "statement"
    ]
    source_non_statement_unique = [
        path for path in source_unique if classify_statement_type(path) == "non_statement"
    ]
    parsed_source_unique = sorted(
        {Path(str(tx.source_file)) for tx in parsed_transactions}, key=lambda path: str(path)
    )
    parsed_statement_source_unique = [
        path for path in parsed_source_unique if classify_statement_type(path) == "statement"
    ]
    parsed_non_statement_source_unique = [
        path for path in parsed_source_unique if classify_statement_type(path) == "non_statement"
    ]

    parsed_source_set = set(parsed_source_unique)
    source_statement_set = set(source_statement_unique)
    validated_statement_source_unique = sorted(
        {
            Path(str(validation.source_file))
            for validation in validations_list
            if validation.statement_type == "statement"
            and Path(str(validation.source_file)) in source_statement_set
        },
        key=lambda path: str(path),
    )
    covered_statement_source_set = set(parsed_statement_source_unique) | set(
        validated_statement_source_unique
    )

    missing_files_all = [path for path in source_unique if path not in parsed_source_set]
    missing_statement_files = [
        path for path in source_statement_unique if path not in covered_statement_source_set
    ]
    missing_non_statement_files = [
        path for path in source_non_statement_unique if path not in parsed_source_set
    ]

    source_count = len(source_unique)
    source_statement_count = len(source_statement_unique)
    source_non_statement_count = len(source_non_statement_unique)
    parsed_unique_count = len(parsed_source_unique)
    parsed_statement_unique_count = len(parsed_statement_source_unique)
    parsed_non_statement_unique_count = len(parsed_non_statement_source_unique)
    coverage_ratio = (
        (len(covered_statement_source_set) / source_statement_count)
        if source_statement_count
        else 1.0
    )
    overall_coverage_ratio = (parsed_unique_count / source_count) if source_count else 1.0

    source_by_year = Counter(guess_source_year(path) for path in source_unique)
    parsed_files_by_year = Counter(guess_source_year(path) for path in parsed_source_unique)
    years = sorted(
        set(source_by_year) | set(parsed_files_by_year), key=lambda y: (y == "unknown", y)
    )
    counts_by_year = {
        year: {
            "source_files": source_by_year.get(year, 0),
            "parsed_source_files": parsed_files_by_year.get(year, 0),
        }
        for year in years
    }

    source_by_bank_guess = Counter(guess_source_bank(path) for path in source_unique)
    parsed_transactions_by_bank = Counter(tx.bank for tx in parsed_transactions)
    parsed_source_files_by_bank_guess = Counter(
        guess_source_bank(path) for path in parsed_source_unique
    )

    missing_by_year = Counter(guess_source_year(path) for path in missing_statement_files)
    missing_by_bank_guess = Counter(guess_source_bank(path) for path in missing_statement_files)

    reasons: list[str] = []
    if source_statement_count == 0:
        status = "pass"
        reasons.append("No statement PDFs discovered")
    elif coverage_ratio < fail_coverage_ratio:
        status = "fail"
        reasons.append(
            "Statement file coverage ratio "
            f"{coverage_ratio:.3f} is below fail threshold {fail_coverage_ratio:.3f}"
        )
    elif coverage_ratio < warn_coverage_ratio:
        status = "warn"
        reasons.append(
            "Statement file coverage ratio "
            f"{coverage_ratio:.3f} is below warn threshold {warn_coverage_ratio:.3f}"
        )
    else:
        status = "pass"

    if missing_statement_files:
        reasons.append(f"{len(missing_statement_files)} statement PDFs have zero parsed rows")

    reconciliation = _build_reconciliation_summary(validations_list)
    reconciliation_fail_count = cast(int, reconciliation["fail_count"])
    reconciliation_uncheckable_count = cast(int, reconciliation["uncheckable_file_count"])
    if reconciliation_fail_count > 0:
        reasons.append(f"{reconciliation_fail_count} statements failed balance reconciliation")
    if reconciliation_uncheckable_count > 0:
        reasons.append(
            "info: "
            f"{reconciliation_uncheckable_count} statements are uncheckable for reconciliation"
        )

    return {
        "status": status,
        "reasons": reasons,
        "thresholds": {
            "warn_below_coverage_ratio": warn_coverage_ratio,
            "fail_below_coverage_ratio": fail_coverage_ratio,
        },
        "source_pdf_count": source_count,
        "source_statement_pdf_count": source_statement_count,
        "source_non_statement_pdf_count": source_non_statement_count,
        "parsed_unique_source_file_count": parsed_unique_count,
        "parsed_unique_statement_source_file_count": parsed_statement_unique_count,
        "parsed_unique_non_statement_source_file_count": parsed_non_statement_unique_count,
        "covered_unique_statement_source_file_count": len(covered_statement_source_set),
        "validation_unique_statement_source_file_count": len(validated_statement_source_unique),
        "file_coverage_ratio": coverage_ratio,
        "overall_file_coverage_ratio": overall_coverage_ratio,
        "missing_source_file_count": len(missing_statement_files),
        "missing_source_file_count_all": len(missing_files_all),
        "missing_non_statement_source_file_count": len(missing_non_statement_files),
        "counts_by_year": counts_by_year,
        "source_counts_by_statement_type": {
            "statement": source_statement_count,
            "non_statement": source_non_statement_count,
        },
        "parsed_source_file_counts_by_statement_type": {
            "statement": parsed_statement_unique_count,
            "non_statement": parsed_non_statement_unique_count,
        },
        "source_counts_by_bank_guess": _sort_counter(source_by_bank_guess),
        "parsed_transaction_counts_by_bank": _sort_counter(parsed_transactions_by_bank),
        "parsed_source_file_counts_by_bank_guess": _sort_counter(parsed_source_files_by_bank_guess),
        "missing_grouped_summaries": {
            "by_year": _sort_counter(missing_by_year),
            "by_bank_guess": _sort_counter(missing_by_bank_guess),
            "by_year_and_bank_guess": _group_missing_by_year_and_bank(missing_statement_files),
        },
        "missing_source_files": [str(path) for path in missing_statement_files],
        "missing_source_files_all": [str(path) for path in missing_files_all],
        "missing_non_statement_source_files": [str(path) for path in missing_non_statement_files],
        "statement_reconciliation": reconciliation,
    }


def _build_reconciliation_summary(validations: list[StatementValidation]) -> dict[str, object]:
    statement_validations = [
        validation for validation in validations if validation.statement_type == "statement"
    ]
    file_validations: dict[str, StatementValidation] = {}
    for validation in statement_validations:
        file_validations[str(validation.source_file)] = validation

    unique_validations = list(file_validations.values())
    checkable = [
        validation
        for validation in unique_validations
        if validation.opening_balance is not None and validation.closing_balance is not None
    ]
    pass_count = sum(1 for validation in checkable if validation.status == "pass")
    fail_count = sum(1 for validation in checkable if validation.status == "fail")
    uncheckable = [
        validation for validation in unique_validations if validation.status == "uncheckable"
    ]

    by_status = Counter(validation.status for validation in unique_validations)
    by_severity = Counter(validation.severity for validation in unique_validations)
    by_bank_status = Counter(
        (validation.bank, validation.status) for validation in unique_validations
    )
    by_year_status = Counter(
        (guess_source_year(validation.source_file), validation.status)
        for validation in unique_validations
    )
    uncheckable_reasons = Counter(
        (validation.reason or "unknown")
        for validation in unique_validations
        if validation.status == "uncheckable"
    )

    warning_items = [
        _validation_item(validation)
        for validation in unique_validations
        if validation.severity == "warning"
    ]
    info_items = [
        _validation_item(validation)
        for validation in unique_validations
        if validation.severity == "info"
    ]
    checkable_count = len(checkable)
    abs_differences = [
        abs(validation.difference) for validation in checkable if validation.difference is not None
    ]
    abs_difference_buckets = _abs_difference_buckets(abs_differences)
    median_abs_difference = _median_decimal(abs_differences)
    mean_abs_difference = (
        (sum(abs_differences, start=Decimal("0")) / Decimal(len(abs_differences)))
        if abs_differences
        else None
    )

    by_bank_abs_difference = _by_bank_abs_difference(checkable)

    return {
        "files_with_validation_record_count": len(unique_validations),
        "checkable_file_count": checkable_count,
        "uncheckable_file_count": len(uncheckable),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_ratio": (pass_count / checkable_count) if checkable_count else None,
        "fail_ratio": (fail_count / checkable_count) if checkable_count else None,
        "counts_by_status": dict(sorted(by_status.items())),
        "counts_by_severity": dict(sorted(by_severity.items())),
        "counts_by_bank_and_status": [
            {"bank": bank, "status": status, "count": count}
            for (bank, status), count in sorted(
                by_bank_status.items(), key=lambda item: (item[0][0], item[0][1])
            )
        ],
        "counts_by_year_and_status": [
            {"year": year, "status": status, "count": count}
            for (year, status), count in sorted(
                by_year_status.items(), key=lambda item: (item[0][0], item[0][1])
            )
        ],
        "warning_items": warning_items,
        "info_items": info_items,
        "uncheckable_reasons": dict(sorted(uncheckable_reasons.items())),
        "abs_difference_buckets": abs_difference_buckets,
        "median_abs_difference": _decimal_or_none(median_abs_difference),
        "mean_abs_difference": _decimal_or_none(mean_abs_difference),
        "by_bank_abs_difference": by_bank_abs_difference,
    }


def _validation_item(validation: StatementValidation) -> dict[str, object]:
    return {
        "source_file": str(validation.source_file),
        "bank": validation.bank,
        "parser": validation.parser,
        "status": validation.status,
        "severity": validation.severity,
        "reason": validation.reason,
        "opening_balance": _decimal_or_none(validation.opening_balance),
        "transaction_sum": _decimal_or_none(validation.transaction_sum),
        "expected_closing_balance": _decimal_or_none(validation.expected_closing_balance),
        "closing_balance": _decimal_or_none(validation.closing_balance),
        "difference": _decimal_or_none(validation.difference),
    }


def _decimal_or_none(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _abs_difference_buckets(differences: list[Decimal]) -> dict[str, int]:
    buckets: Counter[str] = Counter()
    for value in differences:
        abs_value = abs(value)
        if abs_value <= Decimal("0.01"):
            buckets["le_0_01"] += 1
        elif abs_value <= Decimal("10"):
            buckets["gt_0_01_le_10"] += 1
        elif abs_value <= Decimal("100"):
            buckets["gt_10_le_100"] += 1
        elif abs_value <= Decimal("1000"):
            buckets["gt_100_le_1000"] += 1
        else:
            buckets["gt_1000"] += 1

    ordered = (
        "le_0_01",
        "gt_0_01_le_10",
        "gt_10_le_100",
        "gt_100_le_1000",
        "gt_1000",
    )
    return {bucket: buckets.get(bucket, 0) for bucket in ordered}


def _median_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / Decimal("2")


def _by_bank_abs_difference(checkable: list[StatementValidation]) -> list[dict[str, object]]:
    grouped: dict[str, list[Decimal]] = {}
    for validation in checkable:
        if validation.difference is None:
            continue
        grouped.setdefault(validation.bank, []).append(abs(validation.difference))

    rows: list[dict[str, object]] = []
    for bank, differences in sorted(grouped.items()):
        mean_abs_difference = sum(differences, start=Decimal("0")) / Decimal(len(differences))
        rows.append(
            {
                "bank": bank,
                "checkable_count": len(differences),
                "median_abs_difference": _decimal_or_none(_median_decimal(differences)),
                "mean_abs_difference": _decimal_or_none(mean_abs_difference),
                "abs_difference_buckets": _abs_difference_buckets(differences),
            }
        )
    return rows

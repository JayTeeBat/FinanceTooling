"""Completeness reporting for statement ingestion coverage."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from finance_tooling.models import Transaction

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
    *,
    warn_coverage_ratio: float = _DEFAULT_WARN_COVERAGE_RATIO,
    fail_coverage_ratio: float = _DEFAULT_FAIL_COVERAGE_RATIO,
) -> dict[str, object]:
    """Build a machine-readable parsing completeness report."""
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
    missing_files_all = [path for path in source_unique if path not in parsed_source_set]
    missing_statement_files = [
        path for path in source_statement_unique if path not in parsed_source_set
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
        (parsed_statement_unique_count / source_statement_count) if source_statement_count else 1.0
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
    }

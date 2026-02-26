"""Ingestion stage: discover, parse, and collect parser diagnostics."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from tqdm import tqdm

from finance_tooling.config import Settings
from finance_tooling.extract import ExtractedPdfText
from finance_tooling.importers.hsbc_csv import HsbcCsvImportResult
from finance_tooling.models import Transaction
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.parsers.registry import ParserSelection
from finance_tooling.workflow.types import IngestResult, ParserCandidate, ParserSelectionDiagnostic

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


def extract_statement_date(path: Path) -> str | None:
    """Extract statement date token from source filename."""
    match = _HSBC_STATEMENT_DATE_PATTERN.search(path.name)
    if match is None:
        return None
    return match.group(0)


def parse_hsbc_statement_period(full_text: str) -> tuple[date, date] | None:
    """Parse inclusive HSBC statement period from extracted text."""
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


def hsbc_statement_period_uses_spacing_variant(full_text: str) -> bool:
    """Flag known spacing variants to support parser quality diagnostics."""
    flattened = " ".join(full_text.split())
    return _HSBC_STATEMENT_PERIOD_VARIANT_PATTERN.search(flattened) is not None


def ingest_statements(
    settings: Settings,
    *,
    discover_statement_pdfs: Callable[[Path], list[Path]],
    extract_text_from_pdf: Callable[[Path], ExtractedPdfText],
    select_parser_with_diagnostics: Callable[[Path, str], ParserSelection],
    discover_csv_files: Callable[[Path], list[Path]],
    load_hsbc_csv_transactions: Callable[[list[Path]], HsbcCsvImportResult],
) -> IngestResult:
    """Run ingestion stage from raw source discovery through optional CSV import."""
    warnings: list[str] = []
    files_failed = 0
    extracted: list[Transaction] = []
    validations: list[StatementValidation] = []
    parser_selection_diagnostics: list[ParserSelectionDiagnostic] = []
    parser_low_confidence_file_count = 0
    hsbc_csv_files_scanned = 0
    hsbc_period_parse_variant_match_count = 0
    hsbc_statement_periods_by_date: dict[str, tuple[date, date]] = {}

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
            top_candidates: list[ParserCandidate] = [
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
                statement_date = extract_statement_date(pdf_path)
                statement_period = parse_hsbc_statement_period(extracted_text.full_text)
                if statement_date is not None and statement_period is not None:
                    hsbc_statement_periods_by_date[statement_date] = statement_period
                    if hsbc_statement_period_uses_spacing_variant(extracted_text.full_text):
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

    return IngestResult(
        source_files=files,
        transactions=extracted,
        validations=validations,
        warnings=warnings,
        files_failed=files_failed,
        parser_selection_diagnostics=parser_selection_diagnostics,
        parser_low_confidence_file_count=parser_low_confidence_file_count,
        hsbc_statement_periods_by_date=hsbc_statement_periods_by_date,
        hsbc_period_parse_variant_match_count=hsbc_period_parse_variant_match_count,
        hsbc_csv_files_scanned=hsbc_csv_files_scanned,
    )

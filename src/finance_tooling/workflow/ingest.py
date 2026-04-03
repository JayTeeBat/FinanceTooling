"""Ingestion stage: discover, parse, and collect parser diagnostics."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import cast

from tqdm import tqdm

from finance_tooling.config import Settings
from finance_tooling.extract import ExtractedPdfText
from finance_tooling.extract import extract_text_from_pdf as default_extract_text_from_pdf
from finance_tooling.models import Transaction
from finance_tooling.parsers.base import StatementParser, StatementValidation
from finance_tooling.parsers.generic import GenericParser
from finance_tooling.parsers.registry import (
    PARSERS,
    ParserSelection,
)
from finance_tooling.parsers.registry import (
    select_parser_with_diagnostics as default_select_parser_with_diagnostics,
)
from finance_tooling.source_inventory import (
    SourceInventorySnapshot,
    build_source_inventory,
    representative_source_files,
)
from finance_tooling.workflow.ingest_cache import (
    CachedExtractionRow,
    build_cache_key,
    load_text_cache,
    upsert_text_cache,
)
from finance_tooling.workflow.types import (
    HsbcBoundaryDiagnostic,
    HsbcSignDiagnostic,
    IngestResult,
    ParserCandidate,
    ParserSelectionDiagnostic,
)

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
_PARSERS_BY_NAME = {parser.name: parser for parser in PARSERS}


@dataclass(frozen=True)
class _PreparedStatement:
    index: int
    source_file: Path
    source_document_id: str
    first_page_text: str
    full_text: str
    selected_parser_name: str
    selected_parser: StatementParser | None
    selected_score: int
    threshold: int
    top_candidates: list[ParserCandidate]
    is_low_confidence: bool
    is_ambiguous_tie: bool
    hsbc_statement_date: str | None
    hsbc_statement_period: tuple[date, date] | None
    hsbc_spacing_variant: bool
    error: str | None = None


def extract_statement_date(path: Path) -> str | None:
    """Extract statement date token from source filename."""
    match = _HSBC_STATEMENT_DATE_PATTERN.search(path.name)
    if match is None:
        return None
    return match.group(0)


def _flatten_text(full_text: str) -> str:
    return " ".join(full_text.split())


def _parse_hsbc_statement_period_flattened(flattened: str) -> tuple[date, date] | None:
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


def parse_hsbc_statement_period(full_text: str) -> tuple[date, date] | None:
    """Parse inclusive HSBC statement period from extracted text."""
    return _parse_hsbc_statement_period_flattened(_flatten_text(full_text))


def hsbc_statement_period_uses_spacing_variant(full_text: str) -> bool:
    """Flag known spacing variants to support parser quality diagnostics."""
    return _HSBC_STATEMENT_PERIOD_VARIANT_PATTERN.search(_flatten_text(full_text)) is not None


def _prepare_statement(
    index: int,
    pdf_path: Path,
    *,
    source_document_id: str,
    extract_text_from_pdf: Callable[[Path], ExtractedPdfText],
    select_parser_with_diagnostics: Callable[[Path, str], ParserSelection],
) -> _PreparedStatement:
    extracted_text = extract_text_from_pdf(pdf_path)
    return _prepare_statement_from_extracted(
        index,
        pdf_path,
        source_document_id=source_document_id,
        extracted_text=extracted_text,
        select_parser_with_diagnostics=select_parser_with_diagnostics,
    )


def _prepare_statement_from_extracted(
    index: int,
    pdf_path: Path,
    *,
    source_document_id: str,
    extracted_text: ExtractedPdfText,
    select_parser_with_diagnostics: Callable[[Path, str], ParserSelection],
) -> _PreparedStatement:
    selection = select_parser_with_diagnostics(pdf_path, extracted_text.first_page_text)
    top_candidates: list[ParserCandidate] = [
        {"parser": item.parser_name, "score": item.score} for item in selection.candidates[:3]
    ]
    flattened_full_text = _flatten_text(extracted_text.full_text)
    statement_date: str | None = None
    statement_period: tuple[date, date] | None = None
    spacing_variant_match = False
    if selection.parser.name == "hsbc":
        statement_date = extract_statement_date(pdf_path)
        statement_period = _parse_hsbc_statement_period_flattened(flattened_full_text)
        spacing_variant_match = (
            _HSBC_STATEMENT_PERIOD_VARIANT_PATTERN.search(flattened_full_text) is not None
        )
    is_low_confidence = selection.score <= selection.threshold
    is_ambiguous_tie = (
        len(selection.candidates) > 1
        and selection.candidates[0].score == selection.candidates[1].score
    )
    return _PreparedStatement(
        index=index,
        source_file=pdf_path,
        source_document_id=source_document_id,
        first_page_text=extracted_text.first_page_text,
        full_text=extracted_text.full_text,
        selected_parser_name=selection.parser.name,
        selected_parser=selection.parser,
        selected_score=selection.score,
        threshold=selection.threshold,
        top_candidates=top_candidates,
        is_low_confidence=is_low_confidence,
        is_ambiguous_tie=is_ambiguous_tie,
        hsbc_statement_date=statement_date,
        hsbc_statement_period=statement_period,
        hsbc_spacing_variant=spacing_variant_match,
    )


def _prepare_statement_worker(
    index: int,
    pdf_path: Path,
    source_document_id: str,
) -> _PreparedStatement:
    try:
        return _prepare_statement(
            index,
            pdf_path,
            source_document_id=source_document_id,
            extract_text_from_pdf=default_extract_text_from_pdf,
            select_parser_with_diagnostics=default_select_parser_with_diagnostics,
        )
    except Exception as exc:
        return _PreparedStatement(
            index=index,
            source_file=pdf_path,
            source_document_id=source_document_id,
            first_page_text="",
            full_text="",
            selected_parser_name="",
            selected_parser=None,
            selected_score=0,
            threshold=0,
            top_candidates=[],
            is_low_confidence=False,
            is_ambiguous_tie=False,
            hsbc_statement_date=None,
            hsbc_statement_period=None,
            hsbc_spacing_variant=False,
            error=str(exc),
        )


def _prepare_statements_parallel(
    files: list[Path],
    *,
    source_document_ids: dict[Path, str],
    max_workers: int,
) -> list[_PreparedStatement]:
    prepared: list[_PreparedStatement] = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_meta = {
            executor.submit(
                _prepare_statement_worker,
                index,
                pdf_path,
                source_document_ids[pdf_path],
            ): (index, pdf_path)
            for index, pdf_path in enumerate(files)
        }
        for future in as_completed(future_to_meta):
            index, pdf_path = future_to_meta[future]
            try:
                prepared.append(future.result())
            except Exception as exc:
                prepared.append(
                    _PreparedStatement(
                        index=index,
                        source_file=pdf_path,
                        source_document_id=source_document_ids[pdf_path],
                        first_page_text="",
                        full_text="",
                        selected_parser_name="",
                        selected_parser=None,
                        selected_score=0,
                        threshold=0,
                        top_candidates=[],
                        is_low_confidence=False,
                        is_ambiguous_tie=False,
                        hsbc_statement_date=None,
                        hsbc_statement_period=None,
                        hsbc_spacing_variant=False,
                        error=str(exc),
                    )
                )
    return sorted(prepared, key=lambda item: item.index)


def _prepare_statements_sequential(
    files: list[Path],
    *,
    source_document_ids: dict[Path, str],
    extract_text_from_pdf: Callable[[Path], ExtractedPdfText],
    select_parser_with_diagnostics: Callable[[Path, str], ParserSelection],
) -> list[_PreparedStatement]:
    prepared: list[_PreparedStatement] = []
    for index, pdf_path in enumerate(files):
        try:
            prepared.append(
                _prepare_statement(
                    index,
                    pdf_path,
                    source_document_id=source_document_ids[pdf_path],
                    extract_text_from_pdf=extract_text_from_pdf,
                    select_parser_with_diagnostics=select_parser_with_diagnostics,
                )
            )
        except Exception as exc:
            prepared.append(
                _PreparedStatement(
                    index=index,
                    source_file=pdf_path,
                    source_document_id=source_document_ids[pdf_path],
                    first_page_text="",
                    full_text="",
                    selected_parser_name="",
                    selected_parser=None,
                    selected_score=0,
                    threshold=0,
                    top_candidates=[],
                    is_low_confidence=False,
                    is_ambiguous_tie=False,
                    hsbc_statement_date=None,
                    hsbc_statement_period=None,
                    hsbc_spacing_variant=False,
                    error=str(exc),
                )
            )
    return prepared


def _can_use_parallel_prepare(
    *,
    settings: Settings,
    extract_text_from_pdf: Callable[[Path], ExtractedPdfText],
    select_parser_with_diagnostics: Callable[[Path, str], ParserSelection],
) -> bool:
    return (
        settings.ingest_workers > 1
        and extract_text_from_pdf is default_extract_text_from_pdf
        and select_parser_with_diagnostics is default_select_parser_with_diagnostics
    )


def _int_diagnostic_value(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    return 0


def ingest_statements(
    settings: Settings,
    *,
    discover_statement_pdfs: Callable[[Path], list[Path]],
    extract_text_from_pdf: Callable[[Path], ExtractedPdfText],
    select_parser_with_diagnostics: Callable[[Path, str], ParserSelection],
    source_inventory: SourceInventorySnapshot | None = None,
    selected_source_files: list[Path] | None = None,
    run_mode: str = "incremental",
    files_skipped_already_committed: int = 0,
    files_skipped_modified_existing: int = 0,
    files_missing_since_last_commit: int = 0,
    dataset_stale: bool = False,
    stale_reasons: list[str] | None = None,
) -> IngestResult:
    """Run ingestion stage from raw source discovery through PDF parsing."""
    warnings: list[str] = []
    files_failed = 0
    processed_source_files: list[Path] = []
    extracted: list[Transaction] = []
    validations: list[StatementValidation] = []
    parser_selection_diagnostics: list[ParserSelectionDiagnostic] = []
    parser_low_confidence_file_count = 0
    hsbc_csv_files_scanned = 0
    hsbc_period_parse_variant_match_count = 0
    hsbc_boundary_metrics: dict[str, int] = {
        "table_start_count": 0,
        "table_end_count": 0,
        "rows_seen_in_table": 0,
        "rows_rejected_outside_table": 0,
        "rows_rejected_after_table": 0,
        "transition_anomaly_count": 0,
    }
    hsbc_boundary_diagnostics: list[HsbcBoundaryDiagnostic] = []
    hsbc_sign_metrics: dict[str, int] = {
        "sign_from_running_balance_count": 0,
        "sign_from_column_position_count": 0,
        "sign_from_token_marker_count": 0,
        "sign_from_description_marker_count": 0,
        "sign_from_fallback_hint_count": 0,
        "sign_default_debit_count": 0,
        "sign_conflict_running_vs_marker_count": 0,
        "sign_unresolved_ambiguous_count": 0,
    }
    hsbc_sign_diagnostics: list[HsbcSignDiagnostic] = []
    hsbc_statement_periods_by_date: dict[str, tuple[date, date]] = {}
    parser_duration_seconds_by_parser: dict[str, float] = defaultdict(float)
    duration_seconds_by_bank: dict[str, float] = defaultdict(float)
    text_cache_hits = 0
    text_cache_misses = 0
    text_cache_write_count = 0

    discovered_files = discover_statement_pdfs(settings.input_path)
    resolved_inventory = (
        source_inventory
        if source_inventory is not None
        else build_source_inventory(discovered_files)
    )
    representative_files = representative_source_files(resolved_inventory)
    files = selected_source_files if selected_source_files is not None else representative_files
    source_document_ids = {
        Path(entry.source_file): entry.source_document_id
        for entry in resolved_inventory.entries
        if entry.is_representative
    }
    duplicate_groups = resolved_inventory.ignored_duplicate_file_count
    if duplicate_groups > 0:
        warnings.append(
            "Duplicate raw source files detected and ignored: "
            f"{duplicate_groups} duplicate file(s) across "
            f"{resolved_inventory.raw_file_count} discovered file(s)"
        )
    for stale_reason in stale_reasons or []:
        if stale_reason == "raw_source_modified_since_commit":
            warnings.append(
                "Incremental ingest skipped modified previously committed source files; "
                "run --full-refresh to reparse them."
            )
        elif stale_reason == "raw_source_missing_since_commit":
            warnings.append(
                "Incremental ingest detected previously committed source files missing from the "
                "raw corpus; canonical rows are retained until --full-refresh."
            )
        elif stale_reason == "config_changed_since_last_full_refresh":
            warnings.append(
                "Category or project rules changed since the last full refresh; "
                "historical rows may be stale "
                "until --full-refresh."
            )
    prepared_cache_hits: list[_PreparedStatement] = []
    cache_write_rows: list[CachedExtractionRow] = []
    files_for_prepare = files
    index_by_path: dict[Path, int] = {path: index for index, path in enumerate(files)}

    if settings.ingest_text_cache_enabled:
        text_cache, cache_warnings = load_text_cache(settings.ingest_text_cache_path)
        warnings.extend(cache_warnings)
        files_for_prepare = []
        for index, pdf_path in enumerate(files):
            try:
                cache_key = build_cache_key(pdf_path)
            except Exception as exc:
                warnings.append(f"Ingest text cache stat failed for {pdf_path}: {exc}")
                files_for_prepare.append(pdf_path)
                continue
            cached = text_cache.get(cache_key)
            if cached is None:
                files_for_prepare.append(pdf_path)
                text_cache_misses += 1
                continue
            text_cache_hits += 1
            try:
                prepared_cache_hits.append(
                    _prepare_statement_from_extracted(
                        index,
                        pdf_path,
                        source_document_id=source_document_ids[pdf_path],
                        extracted_text=cached,
                        select_parser_with_diagnostics=select_parser_with_diagnostics,
                    )
                )
            except Exception as exc:
                warnings.append(
                    f"Failed to process cached extraction for {pdf_path}: {exc}; falling back"
                )
                files_for_prepare.append(pdf_path)
                text_cache_misses += 1

    if _can_use_parallel_prepare(
        settings=settings,
        extract_text_from_pdf=extract_text_from_pdf,
        select_parser_with_diagnostics=select_parser_with_diagnostics,
    ):
        prepared_files = _prepare_statements_parallel(
            files_for_prepare,
            source_document_ids=source_document_ids,
            max_workers=settings.ingest_workers,
        )
    else:
        prepared_files = _prepare_statements_sequential(
            files_for_prepare,
            source_document_ids=source_document_ids,
            extract_text_from_pdf=extract_text_from_pdf,
            select_parser_with_diagnostics=select_parser_with_diagnostics,
        )

    if settings.ingest_text_cache_enabled:
        for prepared in prepared_files:
            if prepared.error is not None:
                continue
            try:
                cache_key = build_cache_key(prepared.source_file)
            except Exception as exc:
                warnings.append(f"Ingest text cache stat failed for {prepared.source_file}: {exc}")
                continue
            cache_write_rows.append(
                CachedExtractionRow(
                    source_file=cache_key[0],
                    mtime_ns=cache_key[1],
                    file_size=cache_key[2],
                    first_page_text=prepared.first_page_text,
                    full_text=prepared.full_text,
                )
            )
        text_cache_write_count, cache_write_warnings = upsert_text_cache(
            settings.ingest_text_cache_path,
            cache_write_rows,
        )
        warnings.extend(cache_write_warnings)

    prepared_files = sorted(
        [*prepared_cache_hits, *prepared_files],
        key=lambda item: item.index if item.index >= 0 else index_by_path[item.source_file],
    )

    progress = tqdm(
        prepared_files,
        desc="Processing statements",
        unit="file",
        disable=not sys.stderr.isatty(),
    )

    for prepared in progress:
        if prepared.error is not None:
            files_failed += 1
            warnings.append(f"Failed to process {prepared.source_file}: {prepared.error}")
            continue
        try:
            parser = prepared.selected_parser or _PARSERS_BY_NAME.get(
                prepared.selected_parser_name,
                GenericParser(),
            )
            parser_selection_diagnostics.append(
                {
                    "source_file": str(prepared.source_file),
                    "selected_parser": parser.name,
                    "selected_score": prepared.selected_score,
                    "threshold": prepared.threshold,
                    "top_candidates": prepared.top_candidates,
                }
            )
            if prepared.is_low_confidence or prepared.is_ambiguous_tie:
                parser_low_confidence_file_count += 1
                warnings.append(
                    f"Low-confidence parser selection for {prepared.source_file.name}: selected "
                    f"{parser.name} (score={prepared.selected_score}, "
                    f"threshold={prepared.threshold})"
                )

            parser_started_at = perf_counter()
            output = parser.parse(prepared.source_file, prepared.full_text)
            parser_duration = perf_counter() - parser_started_at
            parser_duration_seconds_by_parser[parser.name] += parser_duration
            duration_seconds_by_bank[parser.bank] += parser_duration

            extracted.extend(
                replace(transaction, source_document_id=prepared.source_document_id)
                for transaction in output.transactions
            )
            processed_source_files.append(prepared.source_file)
            warnings.extend(output.warnings)
            if output.validation is not None:
                validations.append(output.validation)
            if parser.name == "hsbc" and output.diagnostics is not None:
                hsbc_boundary = output.diagnostics.get("hsbc_boundary")
                if isinstance(hsbc_boundary, dict):
                    hsbc_boundary_payload = cast(dict[str, object], hsbc_boundary)
                    boundary_row: HsbcBoundaryDiagnostic = {
                        "source_file": str(prepared.source_file),
                        "table_start_count": _int_diagnostic_value(
                            hsbc_boundary_payload,
                            "table_start_count",
                        ),
                        "table_end_count": _int_diagnostic_value(
                            hsbc_boundary_payload,
                            "table_end_count",
                        ),
                        "rows_seen_in_table": _int_diagnostic_value(
                            hsbc_boundary_payload,
                            "rows_seen_in_table",
                        ),
                        "rows_rejected_outside_table": _int_diagnostic_value(
                            hsbc_boundary_payload,
                            "rows_rejected_outside_table",
                        ),
                        "rows_rejected_after_table": _int_diagnostic_value(
                            hsbc_boundary_payload,
                            "rows_rejected_after_table",
                        ),
                        "transition_anomaly_count": _int_diagnostic_value(
                            hsbc_boundary_payload,
                            "transition_anomaly_count",
                        ),
                    }
                    hsbc_boundary_diagnostics.append(boundary_row)
                    hsbc_boundary_metrics["table_start_count"] += boundary_row["table_start_count"]
                    hsbc_boundary_metrics["table_end_count"] += boundary_row["table_end_count"]
                    hsbc_boundary_metrics["rows_seen_in_table"] += boundary_row[
                        "rows_seen_in_table"
                    ]
                    hsbc_boundary_metrics["rows_rejected_outside_table"] += boundary_row[
                        "rows_rejected_outside_table"
                    ]
                    hsbc_boundary_metrics["rows_rejected_after_table"] += boundary_row[
                        "rows_rejected_after_table"
                    ]
                    hsbc_boundary_metrics["transition_anomaly_count"] += boundary_row[
                        "transition_anomaly_count"
                    ]
                hsbc_sign = output.diagnostics.get("hsbc_sign")
                if isinstance(hsbc_sign, dict):
                    hsbc_sign_payload = cast(dict[str, object], hsbc_sign)
                    sign_row: HsbcSignDiagnostic = {
                        "source_file": str(prepared.source_file),
                        "sign_from_running_balance_count": _int_diagnostic_value(
                            hsbc_sign_payload,
                            "sign_from_running_balance_count",
                        ),
                        "sign_from_column_position_count": _int_diagnostic_value(
                            hsbc_sign_payload,
                            "sign_from_column_position_count",
                        ),
                        "sign_from_token_marker_count": _int_diagnostic_value(
                            hsbc_sign_payload,
                            "sign_from_token_marker_count",
                        ),
                        "sign_from_description_marker_count": _int_diagnostic_value(
                            hsbc_sign_payload,
                            "sign_from_description_marker_count",
                        ),
                        "sign_from_fallback_hint_count": _int_diagnostic_value(
                            hsbc_sign_payload,
                            "sign_from_fallback_hint_count",
                        ),
                        "sign_default_debit_count": _int_diagnostic_value(
                            hsbc_sign_payload,
                            "sign_default_debit_count",
                        ),
                        "sign_conflict_running_vs_marker_count": _int_diagnostic_value(
                            hsbc_sign_payload,
                            "sign_conflict_running_vs_marker_count",
                        ),
                        "sign_unresolved_ambiguous_count": _int_diagnostic_value(
                            hsbc_sign_payload,
                            "sign_unresolved_ambiguous_count",
                        ),
                    }
                    hsbc_sign_diagnostics.append(sign_row)
                    hsbc_sign_metrics["sign_from_running_balance_count"] += sign_row[
                        "sign_from_running_balance_count"
                    ]
                    hsbc_sign_metrics["sign_from_column_position_count"] += sign_row[
                        "sign_from_column_position_count"
                    ]
                    hsbc_sign_metrics["sign_from_token_marker_count"] += sign_row[
                        "sign_from_token_marker_count"
                    ]
                    hsbc_sign_metrics["sign_from_description_marker_count"] += sign_row[
                        "sign_from_description_marker_count"
                    ]
                    hsbc_sign_metrics["sign_from_fallback_hint_count"] += sign_row[
                        "sign_from_fallback_hint_count"
                    ]
                    hsbc_sign_metrics["sign_default_debit_count"] += sign_row[
                        "sign_default_debit_count"
                    ]
                    hsbc_sign_metrics["sign_conflict_running_vs_marker_count"] += sign_row[
                        "sign_conflict_running_vs_marker_count"
                    ]
                    hsbc_sign_metrics["sign_unresolved_ambiguous_count"] += sign_row[
                        "sign_unresolved_ambiguous_count"
                    ]
            if (
                parser.name == "hsbc"
                and prepared.hsbc_statement_date is not None
                and prepared.hsbc_statement_period is not None
            ):
                hsbc_statement_periods_by_date[prepared.hsbc_statement_date] = (
                    prepared.hsbc_statement_period
                )
                if prepared.hsbc_spacing_variant:
                    hsbc_period_parse_variant_match_count += 1
        except Exception as exc:
            files_failed += 1
            warnings.append(f"Failed to process {prepared.source_file}: {exc}")

    return IngestResult(
        source_files=representative_files,
        raw_file_count=resolved_inventory.raw_file_count,
        duplicate_raw_file_count=resolved_inventory.ignored_duplicate_file_count,
        all_source_files=representative_files,
        selected_source_files=files,
        transactions=extracted,
        validations=validations,
        warnings=warnings,
        files_failed=files_failed,
        processed_source_files=processed_source_files,
        parser_selection_diagnostics=parser_selection_diagnostics,
        parser_low_confidence_file_count=parser_low_confidence_file_count,
        hsbc_statement_periods_by_date=hsbc_statement_periods_by_date,
        hsbc_period_parse_variant_match_count=hsbc_period_parse_variant_match_count,
        hsbc_boundary_metrics=hsbc_boundary_metrics,
        hsbc_boundary_diagnostics=hsbc_boundary_diagnostics,
        hsbc_sign_metrics=hsbc_sign_metrics,
        hsbc_sign_diagnostics=hsbc_sign_diagnostics,
        hsbc_csv_files_scanned=hsbc_csv_files_scanned,
        parser_duration_seconds_by_parser=dict(parser_duration_seconds_by_parser),
        duration_seconds_by_bank=dict(duration_seconds_by_bank),
        text_cache_enabled=settings.ingest_text_cache_enabled,
        text_cache_hits=text_cache_hits,
        text_cache_misses=text_cache_misses,
        text_cache_write_count=text_cache_write_count,
        source_inventory_path=None,
        run_mode=run_mode,
        files_selected_for_processing=len(files),
        files_skipped_already_committed=files_skipped_already_committed,
        files_skipped_modified_existing=files_skipped_modified_existing,
        files_missing_since_last_commit=files_missing_since_last_commit,
        dataset_stale=dataset_stale,
        stale_reasons=tuple(stale_reasons or []),
    )

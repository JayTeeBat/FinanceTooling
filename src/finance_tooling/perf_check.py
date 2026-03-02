"""Performance-check runner for staged workflow timing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TypedDict

from finance_tooling.config import (
    DOTENV_PATH,
    PROCESSED_PATH_ENV,
    Settings,
    load_settings_from_env,
)
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.extract import extract_text_from_pdf
from finance_tooling.importers import load_hsbc_csv_transactions
from finance_tooling.models import WorkflowResult
from finance_tooling.parsers import select_parser_with_diagnostics
from finance_tooling.scanner import discover_csv_files, discover_statement_pdfs
from finance_tooling.store import upsert_transactions
from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.hsbc_merge import merge_hsbc_sources
from finance_tooling.workflow.ingest import ingest_statements
from finance_tooling.workflow.reporting import persist_and_report

PERFORMANCE_SUMMARY_FILENAME = "performance_summary.json"
PERF_ALLOW_IN_PLACE_ENV = "FINANCE_PERF_ALLOW_IN_PLACE"


class StageDurations(TypedDict):
    """Per-stage wall-clock durations in seconds."""

    ingest: float
    hsbc_merge: float
    enrichment: float
    reporting: float


class PerformanceSummaryPayload(TypedDict):
    """Performance benchmark payload persisted to JSON."""

    generated_at: str
    processed_path: str
    statements_path: str
    fx_auto_fetch: bool
    total_duration_seconds: float
    stage_durations_seconds: StageDurations
    files_scanned: int
    transactions_parsed: int
    files_per_second: float | None
    transactions_per_second: float | None
    summary_path: str
    completeness_path: str
    statement_reconciliation_fail_count: int
    parser_low_confidence_file_count: int
    uncategorized_ratio: float
    ingest_parser_duration_seconds_by_parser: dict[str, float]
    ingest_duration_seconds_by_bank: dict[str, float]
    ingest_text_cache_enabled: bool
    ingest_text_cache_hits: int
    ingest_text_cache_misses: int
    ingest_text_cache_write_count: int


@dataclass(frozen=True)
class PerfCheckResult:
    """Outputs of a staged performance-check run."""

    workflow_result: WorkflowResult
    performance_summary_path: Path
    total_duration_seconds: float
    stage_durations_seconds: StageDurations
    files_per_second: float | None
    transactions_per_second: float | None


def _parse_bool(raw_value: str | None, *, default: bool) -> bool:
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {raw_value}")


def _dotenv_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        env_key, value = line.split("=", maxsplit=1)
        if env_key.strip() != key:
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            return value[1:-1]
        return value
    return None


def assert_isolated_processed_path(settings: Settings) -> None:
    """Guard against running perf checks in the standard processed output path."""
    allow_in_place = _parse_bool(os.environ.get(PERF_ALLOW_IN_PLACE_ENV), default=False)
    if allow_in_place:
        return

    standard_raw = _dotenv_value(DOTENV_PATH, PROCESSED_PATH_ENV)
    if standard_raw is None:
        return

    standard_path = Path(standard_raw).expanduser().resolve()
    active_path = settings.summary_json_path.parent.resolve()
    if active_path == standard_path:
        raise ValueError(
            "Performance check output path matches .env FINANCE_PROCESSED_PATH. "
            "Set FINANCE_PROCESSED_PATH to an isolated directory or set "
            "FINANCE_PERF_ALLOW_IN_PLACE=true to override."
        )


def _write_json(path: Path, payload: PerformanceSummaryPayload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _upsert_adapter(parquet_path: Path, transactions, replace_source_files):
    return upsert_transactions(
        parquet_path,
        transactions,
        replace_source_files=replace_source_files,
    )


def run_perf_check(settings: Settings) -> PerfCheckResult:
    """Run the full workflow while recording stage-level performance timings."""
    total_started_at = perf_counter()

    ingest_started_at = perf_counter()
    ingest = ingest_statements(
        settings,
        discover_statement_pdfs=discover_statement_pdfs,
        extract_text_from_pdf=extract_text_from_pdf,
        select_parser_with_diagnostics=select_parser_with_diagnostics,
        discover_csv_files=discover_csv_files,
        load_hsbc_csv_transactions=load_hsbc_csv_transactions,
    )
    ingest_duration = perf_counter() - ingest_started_at

    hsbc_merge_started_at = perf_counter()
    hsbc_merge = merge_hsbc_sources(
        ingest.transactions,
        ingest.validations,
        ingest.source_files,
        ingest.hsbc_statement_periods_by_date,
    )
    hsbc_merge_duration = perf_counter() - hsbc_merge_started_at

    enrichment_started_at = perf_counter()
    enrichment = enrich_transactions(hsbc_merge.transactions, settings)
    enrichment_duration = perf_counter() - enrichment_started_at

    warnings = [
        *ingest.warnings,
        *hsbc_merge.warnings,
        *enrichment.warnings,
    ]

    reporting_started_at = perf_counter()
    workflow_result, summary_payload = persist_and_report(
        settings=settings,
        source_files=ingest.source_files,
        files_failed=ingest.files_failed,
        transactions=enrichment.transactions,
        validations=hsbc_merge.validations,
        parser_selection_diagnostics=ingest.parser_selection_diagnostics,
        parser_low_confidence_file_count=ingest.parser_low_confidence_file_count,
        hsbc_csv_files_scanned=ingest.hsbc_csv_files_scanned,
        hsbc_merge_metrics=hsbc_merge.metrics,
        hsbc_period_parse_variant_match_count=ingest.hsbc_period_parse_variant_match_count,
        hsbc_boundary_metrics=ingest.hsbc_boundary_metrics,
        hsbc_boundary_diagnostics=ingest.hsbc_boundary_diagnostics,
        hsbc_sign_metrics=ingest.hsbc_sign_metrics,
        hsbc_sign_diagnostics=ingest.hsbc_sign_diagnostics,
        hsbc_selection_diagnostics=hsbc_merge.selection_diagnostics,
        ingest_parser_duration_seconds_by_parser=ingest.parser_duration_seconds_by_parser,
        ingest_duration_seconds_by_bank=ingest.duration_seconds_by_bank,
        ingest_text_cache_enabled=ingest.text_cache_enabled,
        ingest_text_cache_hits=ingest.text_cache_hits,
        ingest_text_cache_misses=ingest.text_cache_misses,
        ingest_text_cache_write_count=ingest.text_cache_write_count,
        classification_diagnostics=enrichment.classification_diagnostics,
        warnings=warnings,
        upsert_transactions_fn=_upsert_adapter,
        render_dashboard_html_fn=render_dashboard_html,
    )
    reporting_duration = perf_counter() - reporting_started_at
    total_duration = perf_counter() - total_started_at

    stage_durations: StageDurations = {
        "ingest": ingest_duration,
        "hsbc_merge": hsbc_merge_duration,
        "enrichment": enrichment_duration,
        "reporting": reporting_duration,
    }

    files_per_second = (
        workflow_result.files_scanned / total_duration if total_duration > 0 else None
    )
    transactions_per_second = (
        workflow_result.transactions_parsed / total_duration if total_duration > 0 else None
    )

    payload: PerformanceSummaryPayload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "processed_path": str(settings.summary_json_path.parent),
        "statements_path": str(settings.input_path),
        "fx_auto_fetch": settings.fx_auto_fetch,
        "total_duration_seconds": total_duration,
        "stage_durations_seconds": stage_durations,
        "files_scanned": workflow_result.files_scanned,
        "transactions_parsed": workflow_result.transactions_parsed,
        "files_per_second": files_per_second,
        "transactions_per_second": transactions_per_second,
        "summary_path": str(workflow_result.summary_path),
        "completeness_path": str(workflow_result.completeness_path),
        "statement_reconciliation_fail_count": workflow_result.reconciliation_fail_count,
        "parser_low_confidence_file_count": summary_payload["parser_low_confidence_file_count"],
        "uncategorized_ratio": summary_payload["uncategorized_ratio"],
        "ingest_parser_duration_seconds_by_parser": summary_payload[
            "ingest_parser_duration_seconds_by_parser"
        ],
        "ingest_duration_seconds_by_bank": summary_payload["ingest_duration_seconds_by_bank"],
        "ingest_text_cache_enabled": summary_payload["ingest_text_cache_enabled"],
        "ingest_text_cache_hits": summary_payload["ingest_text_cache_hits"],
        "ingest_text_cache_misses": summary_payload["ingest_text_cache_misses"],
        "ingest_text_cache_write_count": summary_payload["ingest_text_cache_write_count"],
    }
    performance_summary_path = settings.summary_json_path.parent / PERFORMANCE_SUMMARY_FILENAME
    _write_json(performance_summary_path, payload)

    return PerfCheckResult(
        workflow_result=workflow_result,
        performance_summary_path=performance_summary_path,
        total_duration_seconds=total_duration,
        stage_durations_seconds=stage_durations,
        files_per_second=files_per_second,
        transactions_per_second=transactions_per_second,
    )


def main() -> int:
    """CLI entrypoint for isolated performance-check runs."""
    try:
        settings = load_settings_from_env()
        assert_isolated_processed_path(settings)
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    result = run_perf_check(settings)

    print(f"Processed output path: {settings.summary_json_path.parent}")
    print(f"Total duration (s): {result.total_duration_seconds:.3f}")
    print(f"Ingest duration (s): {result.stage_durations_seconds['ingest']:.3f}")
    print(f"HSBC merge duration (s): {result.stage_durations_seconds['hsbc_merge']:.3f}")
    print(f"Enrichment duration (s): {result.stage_durations_seconds['enrichment']:.3f}")
    print(f"Reporting duration (s): {result.stage_durations_seconds['reporting']:.3f}")
    print(f"Files scanned: {result.workflow_result.files_scanned}")
    print(f"Transactions parsed: {result.workflow_result.transactions_parsed}")
    print(f"Performance summary: {result.performance_summary_path}")
    print(f"Run summary: {result.workflow_result.summary_path}")
    print(f"Completeness report: {result.workflow_result.completeness_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Workflow orchestration for scanning, extracting, classifying, and reporting."""

from __future__ import annotations

from datetime import date

from finance_tooling.config import Settings
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.extract import extract_text_from_pdf
from finance_tooling.importers import load_hsbc_csv_transactions
from finance_tooling.models import Transaction, WorkflowResult
from finance_tooling.parsers import select_parser_with_diagnostics
from finance_tooling.scanner import discover_csv_files, discover_statement_pdfs
from finance_tooling.store import upsert_transactions
from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.hsbc_merge import (
    assign_hsbc_csv_transactions_to_statement_dates,
    merge_hsbc_sources,
)
from finance_tooling.workflow.ingest import ingest_statements as ingest_workflow_stage
from finance_tooling.workflow.ingest import parse_hsbc_statement_period
from finance_tooling.workflow.reporting import persist_and_report


def _parse_hsbc_statement_period(full_text: str) -> tuple[date, date] | None:
    """Compatibility wrapper for HSBC statement period parser."""
    return parse_hsbc_statement_period(full_text)


def _assign_hsbc_csv_transactions_to_statement_dates(
    csv_transactions: list[Transaction],
    statement_periods_by_date: dict[str, tuple[date, date]],
) -> tuple[dict[str, list[Transaction]], list[Transaction], dict[str, int]]:
    """Compatibility wrapper for HSBC CSV month assignment helper."""
    return assign_hsbc_csv_transactions_to_statement_dates(
        csv_transactions,
        statement_periods_by_date,
    )


def run_workflow(settings: Settings) -> WorkflowResult:
    """Execute the full finance statement workflow."""
    ingest = ingest_workflow_stage(
        settings,
        discover_statement_pdfs=discover_statement_pdfs,
        extract_text_from_pdf=extract_text_from_pdf,
        select_parser_with_diagnostics=select_parser_with_diagnostics,
        discover_csv_files=discover_csv_files,
        load_hsbc_csv_transactions=load_hsbc_csv_transactions,
    )

    hsbc_merge = merge_hsbc_sources(
        ingest.transactions,
        ingest.validations,
        ingest.source_files,
        ingest.hsbc_statement_periods_by_date,
    )

    enrichment = enrich_transactions(hsbc_merge.transactions, settings)

    warnings = [
        *ingest.warnings,
        *hsbc_merge.warnings,
        *enrichment.warnings,
    ]

    result, _summary_payload = persist_and_report(
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
        hsbc_selection_diagnostics=hsbc_merge.selection_diagnostics,
        classification_diagnostics=enrichment.classification_diagnostics,
        warnings=warnings,
        upsert_transactions_fn=upsert_transactions,
        render_dashboard_html_fn=render_dashboard_html,
    )
    return result

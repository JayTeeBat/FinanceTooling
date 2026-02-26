"""Workflow stage modules for orchestration decomposition."""

from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.hsbc_merge import (
    assign_hsbc_csv_transactions_to_statement_dates,
    merge_hsbc_sources,
)
from finance_tooling.workflow.ingest import ingest_statements, parse_hsbc_statement_period
from finance_tooling.workflow.reporting import persist_and_report

__all__ = [
    "assign_hsbc_csv_transactions_to_statement_dates",
    "enrich_transactions",
    "ingest_statements",
    "merge_hsbc_sources",
    "parse_hsbc_statement_period",
    "persist_and_report",
]

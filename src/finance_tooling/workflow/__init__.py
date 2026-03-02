"""Workflow stage modules for orchestration decomposition."""

from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.hsbc_merge import merge_hsbc_sources
from finance_tooling.workflow.ingest import ingest_statements, parse_hsbc_statement_period
from finance_tooling.workflow.reporting import persist_and_report
from finance_tooling.workflow.staging import read_staged_transactions, write_staged_transactions

__all__ = [
    "enrich_transactions",
    "ingest_statements",
    "merge_hsbc_sources",
    "parse_hsbc_statement_period",
    "persist_and_report",
    "read_staged_transactions",
    "write_staged_transactions",
]

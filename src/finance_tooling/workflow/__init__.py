"""Workflow stage modules for orchestration decomposition."""

from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.hsbc_merge import merge_hsbc_sources
from finance_tooling.workflow.ingest import ingest_statements, parse_hsbc_statement_period
from finance_tooling.workflow.ingest_stage import IngestExecutionResult, run_ingest
from finance_tooling.workflow.reporting import persist_and_report
from finance_tooling.workflow.staging import read_staged_transactions, write_staged_transactions
from finance_tooling.workflow.transform_stage import run_transform
from finance_tooling.workflow.update_stage import run_update, run_workflow

__all__ = [
    "IngestExecutionResult",
    "enrich_transactions",
    "ingest_statements",
    "merge_hsbc_sources",
    "parse_hsbc_statement_period",
    "persist_and_report",
    "read_staged_transactions",
    "run_ingest",
    "run_transform",
    "run_update",
    "run_workflow",
    "write_staged_transactions",
]

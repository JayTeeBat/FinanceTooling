"""Combined workflow orchestration across ingest and transform stages."""

from __future__ import annotations

from finance_tooling.config import Settings
from finance_tooling.models import WorkflowResult
from finance_tooling.workflow.ingest_stage import IngestExecutionResult, run_ingest
from finance_tooling.workflow.transform_stage import run_transform


def run_update(
    settings: Settings,
    *,
    ingest_only: bool = False,
    transform_only: bool = False,
) -> WorkflowResult | IngestExecutionResult:
    """Run ingest+transform orchestration with optional stage-only execution."""
    if ingest_only and transform_only:
        raise ValueError("--ingest-only and --transform-only are mutually exclusive.")

    if transform_only:
        return run_transform(settings)

    ingest_result = run_ingest(settings)
    if ingest_only:
        return ingest_result

    return run_transform(
        settings,
        staged_path=ingest_result.staged_path,
        ingest_result=ingest_result,
    )


def run_workflow(settings: Settings) -> WorkflowResult:
    """Compatibility wrapper for the combined update workflow."""
    result = run_update(settings)
    if isinstance(result, IngestExecutionResult):
        raise RuntimeError("run_workflow expects a full workflow result, not ingest-only output.")
    return result

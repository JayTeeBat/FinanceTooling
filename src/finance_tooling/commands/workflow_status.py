"""CLI command for pipeline workflow status and healthcheck output."""

from __future__ import annotations

import argparse

from finance_tooling.config import load_settings_from_env
from finance_tooling.workflow_status import PipelineFinding, build_pipeline_state


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register workflow-status-specific CLI arguments."""
    parser.set_defaults(command="workflow-status", handler=handle)


def handle(_args: argparse.Namespace) -> int:
    """Execute the workflow-status command from parsed CLI arguments."""
    try:
        settings = load_settings_from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    try:
        payload, output_path = build_pipeline_state(settings)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Workflow status error: {exc}")
        return 1

    raw_state = payload["raw_source_state"]
    transformed_state = payload["transformed_state"]
    master_state = transformed_state["master"]
    findings: list[PipelineFinding] = payload["findings"]

    print(f"Pipeline health: {payload['status']}")
    print(
        "Raw sources: "
        f"{raw_state['raw_file_count']} files, "
        f"{raw_state['unique_document_count']} unique documents, "
        f"{raw_state['ignored_duplicate_file_count']} ignored duplicates"
    )
    print(
        "Master parquet: "
        f"{master_state['total_rows']} rows "
        f"({master_state['booking_date_min']} -> {master_state['booking_date_max']})"
    )
    print(f"Run summary present: {transformed_state['summary_exists']}")
    if findings:
        print("Findings:")
        for finding in findings:
            print(f"- [{finding['severity']}] {finding['code']}: {finding['message']}")
    print(f"Pipeline state: {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for workflow-status."""
    parser = argparse.ArgumentParser(
        prog="workflow-status",
        description="Inspect raw, staged, and transformed pipeline state.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

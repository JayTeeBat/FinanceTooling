"""CLI command for pipeline workflow status and healthcheck output."""

from __future__ import annotations

import argparse

from finance_tooling.core.config import load_settings_from_env
from finance_tooling.reporting.workflow_status import PipelineFinding, build_pipeline_state


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register workflow-status-specific CLI arguments."""
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show fuller raw/staged/registry detail in the health snapshot.",
    )
    parser.set_defaults(command="workflow-status", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the workflow-status command from parsed CLI arguments."""
    try:
        settings = load_settings_from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1

    try:
        payload, _output_path = build_pipeline_state(settings)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Workflow status error: {exc}")
        return 1

    raw_state = payload["raw_source_state"]
    staged_state = payload.get(
        "staged_state",
        {
            "exists": False,
            "manifest_exists": False,
            "run_mode": None,
            "files_selected_for_processing": 0,
        },
    )
    committed_state = payload.get(
        "committed_state",
        {
            "committed_source_count": 0,
            "last_run_mode": None,
            "last_full_refresh_at": None,
        },
    )
    drift_state = payload.get(
        "drift_state",
        {
            "dataset_stale": False,
            "full_refresh_risk": "unknown",
        },
    )
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
        "Staged batch: "
        f"exists={staged_state['exists']}, "
        f"run mode={staged_state['run_mode']}, "
        f"selected files={staged_state['files_selected_for_processing']}"
    )
    print(
        "Canonical data: "
        f"{master_state['total_rows']} rows "
        f"({master_state['booking_date_min']} -> {master_state['booking_date_max']})"
    )
    print(
        "Drift state: "
        f"stale={drift_state['dataset_stale']}, "
        f"full refresh risk={drift_state['full_refresh_risk']}"
    )
    if args.verbose:
        print(
            "Committed registry: "
            f"{committed_state['committed_source_count']} documents, "
            f"last run mode={committed_state['last_run_mode']}, "
            f"last full refresh={committed_state['last_full_refresh_at']}"
        )
        print(
            "Staged manifest: "
            f"present={staged_state['manifest_exists']}, "
            f"summary_present={transformed_state['summary_exists']}"
        )
    if findings:
        print(f"Findings: {len(findings)}")
        for finding in findings:
            print(f"- [{finding['severity']}] {finding['code']}: {finding['message']}")
    print("Pipeline state: updated")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for workflow-status."""
    parser = argparse.ArgumentParser(
        prog="workflow-status",
        description="Recommended: inspect pipeline health and write a state snapshot.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

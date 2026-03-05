"""Console-script aliases for top-level finance_tooling commands."""

from __future__ import annotations

import sys

from finance_tooling.__main__ import main
from finance_tooling.perf_check import main as perf_check_main


def ingest() -> int:
    """Run the ingest subcommand via console-script alias."""
    return main(["ingest", *sys.argv[1:]])


def transform() -> int:
    """Run the transform subcommand via console-script alias."""
    return main(["transform", *sys.argv[1:]])


def update() -> int:
    """Run the update subcommand via console-script alias."""
    return main(["update", *sys.argv[1:]])


def review_export() -> int:
    """Run the review-export subcommand via console-script alias."""
    return main(["review-export", *sys.argv[1:]])


def review_import() -> int:
    """Run the review-import subcommand via console-script alias."""
    return main(["review-import", *sys.argv[1:]])


def metrics_log_update() -> int:
    """Run the metrics-log-update subcommand via console-script alias."""
    return main(["metrics-log-update", *sys.argv[1:]])


def perf_check() -> int:
    """Run the perf-check command via console-script alias."""
    return perf_check_main()

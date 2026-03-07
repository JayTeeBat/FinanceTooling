"""CLI command for metrics-log-update."""

from __future__ import annotations

import argparse
from pathlib import Path

from finance_tooling.config import load_settings_from_env
from finance_tooling.metrics_log import (
    build_bank_snapshots,
    build_snapshot,
    upsert_bank_snapshots,
    upsert_snapshot,
)


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Register metrics-log-update-specific CLI arguments."""
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="Path to run_summary.json (defaults to settings summary path when env is configured).",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=Path("docs/metrics_commit_log.csv"),
        help="Destination overall metrics CSV path.",
    )
    parser.add_argument(
        "--log-path-by-bank",
        type=Path,
        default=Path("docs/metrics_commit_log_by_bank.csv"),
        help="Destination per-bank metrics CSV path.",
    )
    parser.add_argument(
        "--commit",
        type=str,
        default=None,
        help="Optional commit hash override (defaults to current git HEAD short hash).",
    )
    parser.add_argument(
        "--branch",
        type=str,
        default=None,
        help="Optional branch override (defaults to current git branch).",
    )
    parser.set_defaults(command="metrics-log-update", handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Execute the metrics-log-update command from parsed CLI arguments."""
    summary_path = args.summary_path
    if summary_path is None:
        try:
            settings = load_settings_from_env()
            summary_path = settings.summary_json_path
        except ValueError:
            print(
                "Configuration error: provide --summary-path "
                "or configure env so settings can be loaded."
            )
            return 1
    if not summary_path.exists():
        print(f"Summary file not found: {summary_path}")
        return 1

    snapshot = build_snapshot(summary_path, commit=args.commit, branch=args.branch)
    total_rows, replaced = upsert_snapshot(args.log_path, snapshot)
    bank_snapshots = build_bank_snapshots(
        summary_path,
        commit=snapshot.commit,
        branch=snapshot.branch,
    )
    bank_rows, bank_replaced = upsert_bank_snapshots(args.log_path_by_bank, bank_snapshots)
    action = "updated" if replaced else "appended"
    bank_action = "updated" if bank_replaced else "appended"
    reconciliation_pct = (
        f"{snapshot.reconciliation_pass_pct:.2f}%"
        if snapshot.reconciliation_pass_pct is not None
        else "n/a"
    )
    print(f"Metrics log {action} for commit {snapshot.commit}: {args.log_path}")
    print(f"- parsing_success_pct: {snapshot.parsing_success_pct:.2f}%")
    print(f"- categorized_pct: {snapshot.categorized_pct:.2f}%")
    print(f"- uncategorized_pct: {snapshot.uncategorized_pct:.2f}%")
    print(f"- reconciliation_pass_pct: {reconciliation_pct}")
    print(f"- rows in log: {total_rows}")
    print(
        f"Per-bank metrics log {bank_action} for commit {snapshot.commit}: {args.log_path_by_bank}"
    )
    print(f"- bank rows for commit: {bank_rows}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint for metrics-log-update."""
    parser = argparse.ArgumentParser(
        prog="metrics-log-update",
        description="Append or update commit-level percentage metrics from run_summary.json.",
    )
    configure_parser(parser)
    args = parser.parse_args(argv)
    return handle(args)

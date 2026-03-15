from __future__ import annotations

import argparse
from typing import Protocol

import pytest

from finance_tooling.commands import (
    ingest as ingest_command,
)
from finance_tooling.commands import (
    metrics_log_update as metrics_log_update_command,
)
from finance_tooling.commands import (
    plan_savings as plan_savings_command,
)
from finance_tooling.commands import (
    review_export as review_export_command,
)
from finance_tooling.commands import (
    review_import as review_import_command,
)
from finance_tooling.commands import (
    transform as transform_command,
)
from finance_tooling.commands import (
    update as update_command,
)


class _CommandModule(Protocol):
    def main(self, argv: list[str] | None = None) -> int: ...

    def handle(self, args: argparse.Namespace) -> int: ...


@pytest.mark.parametrize(
    ("module", "argv"),
    [
        (ingest_command, []),
        (transform_command, ["--input-staged-path", "staged.parquet"]),
        (update_command, ["--ingest-only"]),
        (review_export_command, ["--normalized-path", "n.csv", "--output-path", "r.csv"]),
        (
            review_import_command,
            ["--review-path", "r.csv", "--transaction-overrides-path", "o.yaml"],
        ),
        (metrics_log_update_command, ["--summary-path", "run_summary.json"]),
        (plan_savings_command, ["--inputs-path", "planning_inputs.yaml"]),
    ],
)
def test_command_main_delegates_to_handle(
    monkeypatch: pytest.MonkeyPatch,
    module: _CommandModule,
    argv: list[str],
) -> None:
    captured: dict[str, argparse.Namespace] = {}

    def _handle(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 7

    monkeypatch.setattr(module, "handle", _handle)

    exit_code = module.main(argv)

    assert exit_code == 7
    assert "args" in captured

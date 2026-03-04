from __future__ import annotations

import sys

import pytest

from finance_tooling import cli_aliases


@pytest.mark.parametrize(
    ("fn_name", "subcommand"),
    [
        ("ingest", "ingest"),
        ("transform", "transform"),
        ("update", "update"),
        ("review_export", "review-export"),
        ("review_import", "review-import"),
        ("metrics_log_update", "metrics-log-update"),
    ],
)
def test_alias_dispatches_to_main_with_forwarded_argv(
    monkeypatch: pytest.MonkeyPatch,
    fn_name: str,
    subcommand: str,
) -> None:
    captured: dict[str, list[str]] = {}

    def _main(argv: list[str] | None = None) -> int:
        captured["argv"] = argv or []
        return 7

    monkeypatch.setattr(cli_aliases, "main", _main)
    monkeypatch.setattr(sys, "argv", ["alias", "--flag", "value"])

    fn = getattr(cli_aliases, fn_name)
    exit_code = fn()

    assert exit_code == 7
    assert captured["argv"] == [subcommand, "--flag", "value"]

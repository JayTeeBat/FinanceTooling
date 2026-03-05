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


def test_perf_check_alias_dispatches_to_perf_check_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"count": 0}

    def _perf_main() -> int:
        called["count"] += 1
        return 11

    monkeypatch.setattr(cli_aliases, "perf_check_main", _perf_main)
    exit_code = cli_aliases.perf_check()

    assert exit_code == 11
    assert called["count"] == 1

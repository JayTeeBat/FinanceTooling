from __future__ import annotations

from typing import Any

from finance_tooling.__main__ import main


def test_run_alias_emits_deprecation_and_dispatches_update(monkeypatch, capsys) -> None:
    captured: dict[str, bool] = {}

    def _run_update_command(*, ingest_only: bool, transform_only: bool) -> int:
        captured["ingest_only"] = ingest_only
        captured["transform_only"] = transform_only
        return 0

    monkeypatch.setattr("finance_tooling.__main__._run_update_command", _run_update_command)

    exit_code = main(["run"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured == {"ingest_only": False, "transform_only": False}
    assert "deprecated" in stdio.err
    assert "Use `update` instead." in stdio.err


def test_update_with_conflicting_flags_returns_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("finance_tooling.__main__.load_settings_from_env", lambda: object())

    def _run_update(
        settings: Any, *, ingest_only: bool, transform_only: bool
    ) -> object:  # pragma: no cover - simple control-path stub
        del settings
        if ingest_only and transform_only:
            raise ValueError("--ingest-only and --transform-only are mutually exclusive.")
        return object()

    monkeypatch.setattr("finance_tooling.__main__.run_update", _run_update)

    exit_code = main(["update", "--ingest-only", "--transform-only"])
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "mutually exclusive" in stdio.out

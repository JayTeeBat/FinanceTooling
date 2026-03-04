from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from finance_tooling.__main__ import main
from finance_tooling.categorization_review import ReviewImportResult
from finance_tooling.classify import OverrideStore
from finance_tooling.transaction_overrides import TransactionOverrideStore


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


def test_review_export_defaults_paths_from_settings(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    settings = SimpleNamespace(summary_json_path=processed_dir / "run_summary.json")
    captured: dict[str, Path | bool | str | None] = {}

    def _export(
        normalized_path: Path,
        output_path: Path,
        *,
        include_categorized: bool = False,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        captured["normalized_path"] = normalized_path
        captured["output_path"] = output_path
        captured["include_categorized"] = include_categorized
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        return 4

    monkeypatch.setattr("finance_tooling.__main__.load_settings_from_env", lambda: settings)
    monkeypatch.setattr("finance_tooling.__main__.export_fallback_review_rows", _export)

    exit_code = main(["review-export"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["normalized_path"] == processed_dir / "transactions_normalized.csv"
    assert captured["output_path"] == processed_dir / "fallback_category_review.csv"
    assert captured["include_categorized"] is False
    assert captured["start_date"] is None
    assert captured["end_date"] is None
    assert "Exported 4 fallback review rows" in stdio.out


def test_review_export_passes_explicit_filter_flags(monkeypatch, capsys) -> None:
    captured: dict[str, Path | bool | str | None] = {}

    def _export(
        normalized_path: Path,
        output_path: Path,
        *,
        include_categorized: bool = False,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        captured["normalized_path"] = normalized_path
        captured["output_path"] = output_path
        captured["include_categorized"] = include_categorized
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        return 1

    monkeypatch.setattr("finance_tooling.__main__.export_fallback_review_rows", _export)

    exit_code = main(
        [
            "review-export",
            "--normalized-path",
            "transactions_normalized.csv",
            "--output-path",
            "fallback_category_review.csv",
            "--include-categorized",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-01-31",
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["normalized_path"] == Path("transactions_normalized.csv")
    assert captured["output_path"] == Path("fallback_category_review.csv")
    assert captured["include_categorized"] is True
    assert captured["start_date"] == "2026-01-01"
    assert captured["end_date"] == "2026-01-31"
    assert "Exported 1 fallback review rows" in stdio.out


def test_review_import_defaults_paths_from_settings(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    overrides_path = tmp_path / "config" / "category_overrides.yaml"
    transaction_overrides_path = tmp_path / "config" / "transaction_overrides.yaml"
    settings = SimpleNamespace(
        summary_json_path=processed_dir / "run_summary.json",
        category_overrides_path=overrides_path,
        transaction_overrides_path=transaction_overrides_path,
    )
    captured: dict[str, object] = {}

    def _import(**kwargs: object) -> ReviewImportResult:
        captured.update(kwargs)
        return ReviewImportResult(
            rows_read=2,
            overrides_upserted=1,
            overrides_updated=1,
            overrides_inserted=0,
            rows_skipped=1,
            rows_skipped_non_fallback=1,
            rows_skipped_invalid=0,
            backup_path=None,
        )

    monkeypatch.setattr("finance_tooling.__main__.load_settings_from_env", lambda: settings)
    monkeypatch.setattr(
        "finance_tooling.__main__.load_override_store",
        lambda path: (OverrideStore(entries=()), []),
    )
    monkeypatch.setattr(
        "finance_tooling.__main__.load_transaction_override_store",
        lambda path: (TransactionOverrideStore(entries=()), []),
    )
    monkeypatch.setattr("finance_tooling.__main__.import_review_into_overrides", _import)

    exit_code = main(["review-import", "--dry-run"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["review_path"] == processed_dir / "fallback_category_review.csv"
    assert captured["overrides_path"] == overrides_path
    assert captured["transaction_overrides_path"] == transaction_overrides_path
    assert captured["dry_run"] is True
    assert "Dry run: no override file was written." in stdio.out


def test_review_import_infers_data_adjacent_paths_from_review_path(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed"
    processed_dir.mkdir(parents=True)
    review_path = processed_dir / "fallback_category_review.csv"
    review_path.write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    def _import(**kwargs: object) -> ReviewImportResult:
        captured.update(kwargs)
        return ReviewImportResult(
            rows_read=1,
            overrides_upserted=1,
            overrides_updated=0,
            overrides_inserted=1,
            rows_skipped=0,
            rows_skipped_non_fallback=0,
            rows_skipped_invalid=0,
            backup_path=None,
        )

    monkeypatch.setattr(
        "finance_tooling.__main__.load_settings_from_env",
        lambda: (_ for _ in ()).throw(ValueError("missing settings")),
    )
    monkeypatch.setattr(
        "finance_tooling.__main__.load_override_store",
        lambda path: (OverrideStore(entries=()), []),
    )
    monkeypatch.setattr(
        "finance_tooling.__main__.load_transaction_override_store",
        lambda path: (TransactionOverrideStore(entries=()), []),
    )
    monkeypatch.setattr("finance_tooling.__main__.import_review_into_overrides", _import)

    exit_code = main(["review-import", "--review-path", str(review_path), "--dry-run"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["review_path"] == review_path
    assert captured["overrides_path"] == data_dir / "config" / "category_overrides.yaml"
    assert captured["transaction_overrides_path"] == (
        data_dir / "config" / "transaction_overrides.yaml"
    )
    assert "Dry run: no override file was written." in stdio.out


def test_review_import_aborts_on_override_load_warnings(monkeypatch, capsys) -> None:
    called = {"import_called": False}

    def _import(**kwargs: object) -> ReviewImportResult:
        del kwargs
        called["import_called"] = True
        return ReviewImportResult(
            rows_read=0,
            overrides_upserted=0,
            overrides_updated=0,
            overrides_inserted=0,
            rows_skipped=0,
            rows_skipped_non_fallback=0,
            rows_skipped_invalid=0,
            backup_path=None,
        )

    monkeypatch.setattr(
        "finance_tooling.__main__.load_override_store",
        lambda path: (OverrideStore(entries=()), [f"bad override file: {path}"]),
    )
    monkeypatch.setattr(
        "finance_tooling.__main__.load_transaction_override_store",
        lambda path: (TransactionOverrideStore(entries=()), []),
    )
    monkeypatch.setattr("finance_tooling.__main__.import_review_into_overrides", _import)

    exit_code = main(
        [
            "review-import",
            "--review-path",
            "review.csv",
            "--overrides-path",
            "overrides.yaml",
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert called["import_called"] is False
    assert "Review import error: override load warnings detected" in stdio.out


def test_review_import_allows_override_load_warnings_with_flag(monkeypatch, capsys) -> None:
    called = {"import_called": False}

    def _import(**kwargs: object) -> ReviewImportResult:
        del kwargs
        called["import_called"] = True
        return ReviewImportResult(
            rows_read=1,
            overrides_upserted=1,
            overrides_updated=0,
            overrides_inserted=1,
            rows_skipped=0,
            rows_skipped_non_fallback=0,
            rows_skipped_invalid=0,
            backup_path=None,
        )

    monkeypatch.setattr(
        "finance_tooling.__main__.load_override_store",
        lambda path: (OverrideStore(entries=()), [f"bad override file: {path}"]),
    )
    monkeypatch.setattr(
        "finance_tooling.__main__.load_transaction_override_store",
        lambda path: (TransactionOverrideStore(entries=()), []),
    )
    monkeypatch.setattr("finance_tooling.__main__.import_review_into_overrides", _import)

    exit_code = main(
        [
            "review-import",
            "--review-path",
            "review.csv",
            "--overrides-path",
            "overrides.yaml",
            "--allow-load-warnings",
        ]
    )

    assert exit_code == 0
    assert called["import_called"] is True


def test_review_export_returns_clean_error_without_traceback(monkeypatch, capsys) -> None:
    def _export(
        normalized_path: Path,
        output_path: Path,
        *,
        include_categorized: bool = False,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        del normalized_path, output_path, include_categorized, start_date, end_date
        raise ValueError("boom")

    monkeypatch.setattr("finance_tooling.__main__.export_fallback_review_rows", _export)

    exit_code = main(
        [
            "review-export",
            "--normalized-path",
            "transactions_normalized.csv",
            "--output-path",
            "fallback_category_review.csv",
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "Review export error: boom" in stdio.out
    assert "Traceback" not in f"{stdio.out}\n{stdio.err}"


def test_review_import_returns_clean_error_without_traceback(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "finance_tooling.__main__.load_override_store",
        lambda path: (OverrideStore(entries=()), []),
    )
    monkeypatch.setattr(
        "finance_tooling.__main__.load_transaction_override_store",
        lambda path: (TransactionOverrideStore(entries=()), []),
    )
    monkeypatch.setattr(
        "finance_tooling.__main__.import_review_into_overrides",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("invalid review")),
    )

    exit_code = main(
        [
            "review-import",
            "--review-path",
            "review.csv",
            "--overrides-path",
            "overrides.yaml",
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "Review import error: invalid review" in stdio.out
    assert "Traceback" not in f"{stdio.out}\n{stdio.err}"

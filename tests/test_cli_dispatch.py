from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from finance_tooling.__main__ import main
from finance_tooling.review_import import ReviewImportResult
from finance_tooling.transaction_overrides import TransactionOverrideStore


def test_main_without_subcommand_prints_help(capsys) -> None:
    exit_code = main([])
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "usage:" in stdio.out


def test_update_with_conflicting_flags_returns_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("finance_tooling.commands.update.load_settings_from_env", lambda: object())

    def _run_update(
        settings: Any, *, ingest_only: bool, transform_only: bool
    ) -> object:  # pragma: no cover
        del settings
        if ingest_only and transform_only:
            raise ValueError("--ingest-only and --transform-only are mutually exclusive.")
        return object()

    monkeypatch.setattr("finance_tooling.commands.update.run_update", _run_update)

    exit_code = main(["update", "--ingest-only", "--transform-only"])
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "mutually exclusive" in stdio.out


def test_review_export_defaults_paths_from_settings(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    captured: dict[str, Path | bool | str | None] = {}

    def _export(
        normalized_path: Path,
        output_path: Path,
        *,
        include_categorized: bool = False,
        start_date: str | None = None,
        end_date: str | None = None,
        contains: str | None = None,
        bank: str | None = None,
        account_label: str | None = None,
        only_unreviewed: bool = False,
        preserve_review_state: bool = True,
        review_state_path: Path | None = None,
        dark_safe: bool = True,
    ) -> int:
        captured["normalized_path"] = normalized_path
        captured["output_path"] = output_path
        captured["dark_safe"] = dark_safe
        captured["include_categorized"] = include_categorized
        captured["review_state_path"] = review_state_path
        return 4

    monkeypatch.setattr(
        "finance_tooling.commands.common.try_load_settings_for_defaults",
        lambda: SimpleNamespace(
            summary_json_path=processed_dir / "run_summary.json",
            review_export_dark_safe=True,
            review_state_path=processed_dir / "review_state.parquet",
        ),
    )
    monkeypatch.setattr("finance_tooling.commands.review_export.export_review_rows", _export)

    exit_code = main(["review-export"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["normalized_path"] == processed_dir / "transactions_normalized.csv"
    assert captured["output_path"] == processed_dir / "transactions_review.xlsx"
    assert captured["include_categorized"] is False
    assert captured["review_state_path"] == processed_dir / "review_state.parquet"
    assert captured["dark_safe"] is True
    assert "Exported 4 review rows" in stdio.out


def test_review_export_passes_explicit_filter_flags(monkeypatch, capsys) -> None:
    captured: dict[str, Path | bool | str | None] = {}

    def _export(
        normalized_path: Path,
        output_path: Path,
        *,
        include_categorized: bool = False,
        start_date: str | None = None,
        end_date: str | None = None,
        contains: str | None = None,
        bank: str | None = None,
        account_label: str | None = None,
        only_unreviewed: bool = False,
        preserve_review_state: bool = True,
        review_state_path: Path | None = None,
        dark_safe: bool = True,
    ) -> int:
        captured.update(
            {
                "normalized_path": normalized_path,
                "output_path": output_path,
                "include_categorized": include_categorized,
                "start_date": start_date,
                "end_date": end_date,
                "contains": contains,
                "bank": bank,
                "account_label": account_label,
                "only_unreviewed": only_unreviewed,
                "preserve_review_state": preserve_review_state,
                "review_state_path": review_state_path,
                "dark_safe": dark_safe,
            }
        )
        return 1

    monkeypatch.setattr("finance_tooling.commands.review_export.export_review_rows", _export)

    exit_code = main(
        [
            "review-export",
            "--normalized-path",
            "transactions_normalized.csv",
            "--output-path",
            "transactions_review.csv",
            "--include-categorized",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-01-31",
            "--contains",
            "merchant",
            "--bank",
            "revolut",
            "--account-label",
            "main",
            "--only-unreviewed",
            "--no-dark-safe",
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["normalized_path"] == Path("transactions_normalized.csv")
    assert captured["output_path"] == Path("transactions_review.csv")
    assert captured["include_categorized"] is True
    assert captured["start_date"] == "2026-01-01"
    assert captured["end_date"] == "2026-01-31"
    assert captured["contains"] == "merchant"
    assert captured["bank"] == "revolut"
    assert captured["account_label"] == "main"
    assert captured["only_unreviewed"] is True
    assert captured["dark_safe"] is False
    assert "Exported 1 review rows" in stdio.out


def test_review_import_defaults_paths_from_settings(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    transaction_overrides_path = tmp_path / "config" / "transaction_overrides.yaml"
    settings = SimpleNamespace(
        summary_json_path=processed_dir / "run_summary.json",
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=processed_dir / "review_state.parquet",
    )
    captured: dict[str, object] = {}

    def _import(**kwargs: object) -> ReviewImportResult:
        captured.update(kwargs)
        return ReviewImportResult(
            rows_read=2,
            transaction_overrides_upserted=1,
            transaction_overrides_updated=1,
            transaction_overrides_inserted=0,
            rows_skipped=1,
            rows_skipped_invalid=0,
        )

    monkeypatch.setattr(
        "finance_tooling.commands.common.try_load_settings_for_defaults",
        lambda: settings,
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.load_transaction_override_store",
        lambda path: (TransactionOverrideStore(entries=()), []),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.import_review_into_overrides", _import
    )

    exit_code = main(["review-import", "--dry-run"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["review_path"] == processed_dir / "transactions_review.xlsx"
    assert captured["transaction_overrides_path"] == transaction_overrides_path
    assert captured["review_state_path"] == processed_dir / "review_state.parquet"
    assert captured["dry_run"] is True
    assert "Dry run: no override file was written." in stdio.out


def test_review_import_infers_data_adjacent_paths_from_review_path(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed"
    processed_dir.mkdir(parents=True)
    review_path = processed_dir / "transactions_review.csv"
    review_path.write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    def _import(**kwargs: object) -> ReviewImportResult:
        captured.update(kwargs)
        return ReviewImportResult(rows_read=1)

    monkeypatch.setattr(
        "finance_tooling.commands.common.try_load_settings_for_defaults",
        lambda: None,
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.load_transaction_override_store",
        lambda path: (TransactionOverrideStore(entries=()), []),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.import_review_into_overrides", _import
    )

    exit_code = main(["review-import", "--review-path", str(review_path), "--dry-run"])
    capsys.readouterr()

    assert exit_code == 0
    assert captured["transaction_overrides_path"] == (
        data_dir / "config" / "transaction_overrides.yaml"
    )


def test_review_import_rejects_transform_with_dry_run(capsys) -> None:
    exit_code = main(["review-import", "--dry-run", "--run-transform"])
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "--run-transform cannot be used together with --dry-run" in stdio.out


def test_migrate_category_overrides_command_prints_summary(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    rules_path = tmp_path / "category_rules.yaml"
    report_path = tmp_path / "migration_report.json"
    overrides_path = tmp_path / "category_overrides.yaml"

    monkeypatch.setattr(
        "finance_tooling.commands.migrate_category_overrides_to_rules.migrate_category_overrides_to_rules",
        lambda **kwargs: SimpleNamespace(
            migrated_count=2,
            skipped_count=1,
            conflict_count=0,
            rules_path=rules_path,
            report_path=report_path,
            backup_path=overrides_path.with_suffix(".bak"),
        ),
    )

    exit_code = main(
        [
            "migrate-category-overrides-to-rules",
            "--overrides-path",
            str(overrides_path),
            "--rules-path",
            str(rules_path),
            "--report-path",
            str(report_path),
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Migrated rules: 2" in stdio.out
    assert str(rules_path) in stdio.out

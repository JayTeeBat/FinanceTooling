from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from finance_tooling.__main__ import _build_parser, main
from finance_tooling.categorization.transaction_overrides import TransactionOverrideStore
from finance_tooling.core.backup import BackupRunResult
from finance_tooling.core.models import WorkflowResult
from finance_tooling.parsers.base import StatementValidation
from finance_tooling.review.importer import ReviewImportResult
from finance_tooling.workflow.ingest_stage import IngestExecutionResult


def test_main_without_subcommand_prints_help(capsys) -> None:
    exit_code = main([])
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "usage:" in stdio.out


def test_build_parser_help_labels_primary_and_advanced_commands() -> None:
    parser = _build_parser()
    help_text = parser.format_help()

    assert "Recommended: run the end-to-end workflow" in help_text
    assert "Recommended: export review rows" in help_text
    assert "Recommended: import reviewed workbook changes" in help_text
    assert "Generate a static HTML helper for review triage" in help_text
    assert "Recommended: inspect pipeline health" in help_text
    assert "Advanced: parse raw statements" in help_text
    assert "Advanced: rebuild canonical outputs" in help_text


def test_update_with_conflicting_flags_returns_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("finance_tooling.commands.update.load_settings_from_env", lambda: object())

    def _run_update(
        settings: Any,
        *,
        ingest_only: bool,
        transform_only: bool,
        emit_ingest_summary: bool = False,
    ) -> object:  # pragma: no cover
        del settings
        del emit_ingest_summary
        if ingest_only and transform_only:
            raise ValueError("--ingest-only and --transform-only are mutually exclusive.")
        return object()

    monkeypatch.setattr("finance_tooling.commands.update.run_update", _run_update)

    exit_code = main(["update", "--ingest-only", "--transform-only"])
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "mutually exclusive" in stdio.out


def test_update_full_refresh_dry_run_prints_preflight(monkeypatch, capsys) -> None:
    monkeypatch.setattr("finance_tooling.commands.update.load_settings_from_env", lambda: object())
    monkeypatch.setattr(
        "finance_tooling.commands.update.build_full_refresh_preflight",
        lambda **_: SimpleNamespace(
            full_refresh_risk="high",
            committed_source_count=10,
            raw_file_count=12,
            unique_document_count=11,
            modified_committed_count=2,
            missing_committed_count=1,
            config_drift=True,
            estimated_reprocessed_row_count=100,
            estimated_pruned_row_count=7,
            stale_reasons=("raw_source_missing_since_commit",),
            processed_backup_root=Path("processed/backup"),
            config_backup_root=Path("config/backup"),
            confirmation_token="token-123",
        ),
    )

    exit_code = main(["update", "--full-refresh", "--dry-run"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "FULL REFRESH WARNING" in stdio.out
    assert "token-123" in stdio.out


def test_ingest_full_refresh_requires_matching_confirmation(monkeypatch, capsys) -> None:
    monkeypatch.setattr("finance_tooling.commands.ingest.load_settings_from_env", lambda: object())
    monkeypatch.setattr(
        "finance_tooling.commands.ingest.build_full_refresh_preflight",
        lambda **_: SimpleNamespace(
            full_refresh_risk="medium",
            committed_source_count=0,
            raw_file_count=1,
            unique_document_count=1,
            modified_committed_count=0,
            missing_committed_count=0,
            config_drift=False,
            estimated_reprocessed_row_count=0,
            estimated_pruned_row_count=0,
            stale_reasons=(),
            processed_backup_root=Path("processed/backup"),
            config_backup_root=Path("config/backup"),
            confirmation_token="token-123",
        ),
    )

    exit_code = main(["ingest", "--full-refresh", "--confirm-full-refresh", "wrong-token"])
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "FULL REFRESH WARNING" in stdio.out
    assert "token-123" in stdio.out


def test_ingest_full_refresh_runs_with_confirmation(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr("finance_tooling.commands.ingest.load_settings_from_env", lambda: object())
    monkeypatch.setattr(
        "finance_tooling.commands.ingest.build_full_refresh_preflight",
        lambda **_: SimpleNamespace(
            full_refresh_risk="medium",
            committed_source_count=1,
            raw_file_count=1,
            unique_document_count=1,
            modified_committed_count=0,
            missing_committed_count=0,
            config_drift=False,
            estimated_reprocessed_row_count=1,
            estimated_pruned_row_count=0,
            stale_reasons=(),
            processed_backup_root=Path("processed/backup"),
            config_backup_root=Path("config/backup"),
            confirmation_token="token-123",
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.ingest.run_ingest",
        lambda _settings, run_mode="incremental", emit_ingest_summary=False: captured.setdefault(
            "result",
            IngestExecutionResult(
                staged_path=processed_dir / "state" / "ingest_staged_transactions.parquet",
                ingest_summary_path=processed_dir / "state" / "ingest_summary.json",
                files_scanned=1,
                raw_files_discovered=1,
                duplicate_raw_file_count=0,
                files_failed=0,
                transactions_parsed=1,
                hsbc_csv_files_scanned=0,
                parser_low_confidence_file_count=0,
                warnings=(),
                source_files=(),
                selected_source_files=(),
                validations=(),
                parser_selection_diagnostics=(),
                hsbc_merge_metrics={},
                hsbc_period_parse_variant_match_count=0,
                hsbc_boundary_metrics={},
                hsbc_boundary_diagnostics=(),
                hsbc_sign_metrics={},
                hsbc_sign_diagnostics=(),
                hsbc_selection_diagnostics=(),
                ingest_parser_duration_seconds_by_parser={},
                ingest_duration_seconds_by_bank={},
                ingest_text_cache_enabled=False,
                ingest_text_cache_hits=0,
                ingest_text_cache_misses=0,
                ingest_text_cache_write_count=0,
                run_mode=run_mode,
            ),
        ),
    )

    exit_code = main(["ingest", "--full-refresh", "--confirm-full-refresh", "token-123"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Run mode: full_refresh" in stdio.out
    assert "Statements: 0 preexisting, 0 new" in stdio.out
    assert "New coverage months: none" in stdio.out
    assert "New transactions: 1" in stdio.out


def test_review_export_defaults_paths_from_settings(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    captured: dict[str, Path | bool | str | None] = {}

    def _build_review_dataframe(
        normalized_path: Path,
        output_path: Path,
        *,
        include_categorized: bool = False,
        month: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contains: str | None = None,
        bank: str | None = None,
        account_label: str | None = None,
        min_amount: str | None = None,
        max_amount: str | None = None,
        min_abs_amount: str | None = None,
        max_abs_amount: str | None = None,
        only_unreviewed: bool = False,
        preserve_review_state: bool = True,
        review_state_path: Path | None = None,
        category_rules_path: Path | None = None,
    ) -> tuple[pd.DataFrame, None]:
        captured["normalized_path"] = normalized_path
        captured["output_path"] = output_path
        captured["include_categorized"] = include_categorized
        captured["review_state_path"] = review_state_path
        captured["month"] = month
        captured["category_rules_path"] = category_rules_path
        return (pd.DataFrame([{"transaction_id": "tx_1"}] * 4), None)

    monkeypatch.setattr(
        "finance_tooling.commands.common.try_load_settings_for_defaults",
        lambda: SimpleNamespace(
            summary_json_path=processed_dir / "run_summary.json",
            review_export_dark_safe=True,
            review_state_path=processed_dir / "review_state.parquet",
            category_rules_path=processed_dir / "category_rules.yaml",
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_export.build_review_dataframe",
        _build_review_dataframe,
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_export.write_table",
        lambda output_path, review_rows, *, dark_safe, review_rules: captured.update(
            {"dark_safe": dark_safe}
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_export.render_review_helper_html",
        lambda review_rows, output_path, *, rules=None: captured.update(
            {"helper_path": output_path}
        ),
    )

    exit_code = main(["review-export"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["normalized_path"] == processed_dir / "outputs" / "transform_transactions.csv"
    assert captured["output_path"] == processed_dir / "transactions_review.xlsx"
    assert captured["include_categorized"] is False
    assert captured["review_state_path"] == processed_dir / "review_state.parquet"
    assert captured["category_rules_path"] == processed_dir / "category_rules.yaml"
    assert captured["dark_safe"] is True
    assert "Review export: 4 rows" in stdio.out
    assert captured["helper_path"] == processed_dir / "review_helper.html"
    assert "Review helper: review_helper.html" in stdio.out
    assert str(captured["output_path"]) not in stdio.out


def test_review_export_passes_explicit_filter_flags(monkeypatch, capsys) -> None:
    captured: dict[str, Path | bool | str | None] = {}

    def _build_review_dataframe(
        normalized_path: Path,
        output_path: Path,
        *,
        include_categorized: bool = False,
        month: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contains: str | None = None,
        bank: str | None = None,
        account_label: str | None = None,
        min_amount: str | None = None,
        max_amount: str | None = None,
        min_abs_amount: str | None = None,
        max_abs_amount: str | None = None,
        only_unreviewed: bool = False,
        preserve_review_state: bool = True,
        review_state_path: Path | None = None,
        category_rules_path: Path | None = None,
    ) -> tuple[pd.DataFrame, None]:
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
                "min_amount": min_amount,
                "max_amount": max_amount,
                "min_abs_amount": min_abs_amount,
                "max_abs_amount": max_abs_amount,
                "only_unreviewed": only_unreviewed,
                "preserve_review_state": preserve_review_state,
                "review_state_path": review_state_path,
                "category_rules_path": category_rules_path,
            }
        )
        return (pd.DataFrame([{"transaction_id": "tx_1"}]), None)

    monkeypatch.setattr(
        "finance_tooling.commands.review_export.build_review_dataframe",
        _build_review_dataframe,
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_export.write_table",
        lambda output_path, review_rows, *, dark_safe, review_rules: captured.update(
            {"dark_safe": dark_safe}
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_export.render_review_helper_html",
        lambda review_rows, output_path, *, rules=None: captured.update(
            {"helper_path": output_path}
        ),
    )

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
            "--min-amount",
            "-200",
            "--max-amount",
            "50",
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
    assert captured["min_amount"] == "-200"
    assert captured["max_amount"] == "50"
    assert captured["min_abs_amount"] is None
    assert captured["max_abs_amount"] is None
    assert captured["only_unreviewed"] is True
    assert captured["dark_safe"] is False
    assert "Review export: 1 rows" in stdio.out
    assert captured["helper_path"] == Path("review_helper.html")
    assert "transactions_review.csv" not in stdio.out


def test_review_export_can_disable_helper_generation(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "finance_tooling.commands.review_export.build_review_dataframe",
        lambda normalized_path, output_path, **kwargs: (
            pd.DataFrame([{"transaction_id": "tx_1"}]),
            None,
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_export.write_table",
        lambda output_path, review_rows, *, dark_safe, review_rules: captured.update(
            {"wrote_table": True}
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_export.render_review_helper_html",
        lambda review_rows, output_path, *, rules=None: captured.update({"helper_called": True}),
    )

    exit_code = main(
        [
            "review-export",
            "--normalized-path",
            "transactions_normalized.csv",
            "--output-path",
            "transactions_review.csv",
            "--no-helper",
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["wrote_table"] is True
    assert "helper_called" not in captured
    assert "Review helper:" not in stdio.out


def test_review_export_reports_error_for_mixed_amount_filter_types(
    tmp_path: Path, capsys
) -> None:
    normalized_path = tmp_path / "transactions_normalized.csv"
    normalized_path.write_text(
        (
            "transaction_id,booking_date,description,amount_native,currency,bank,"
            "account_label,category,subcategory,category_source\n"
            "tx_1,2026-01-01,UNKNOWN,-10,EUR,REVOLUT,,Uncategorized,,uncategorized\n"
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "review-export",
            "--normalized-path",
            str(normalized_path),
            "--output-path",
            str(tmp_path / "transactions_review.csv"),
            "--min-amount",
            "-50",
            "--min-abs-amount",
            "50",
        ]
    )
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert (
        "Review export error: min_amount/max_amount cannot be combined with "
        "min_abs_amount/max_abs_amount" in stdio.out
    )


def test_review_helper_defaults_paths_from_settings(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    outputs_dir = processed_dir / "outputs"
    outputs_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "finance_tooling.commands.common.try_load_settings_for_defaults",
        lambda: SimpleNamespace(
            processed_path=processed_dir,
            export_csv_path=outputs_dir / "transform_transactions.csv",
            review_state_path=processed_dir / "state" / "review_state.parquet",
            category_rules_path=processed_dir / "category_rules.yaml",
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_helper.build_review_dataframe",
        lambda normalized_path, *args, **kwargs: (
            [{"transaction_id": "tx_1"}],
            None,
        ),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_helper.render_review_helper_html",
        lambda review_rows, output_path, rules=None: output_path,
    )

    exit_code = main(["review-helper"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Review helper: 1 rows" in stdio.out
    assert "review_helper.html" in stdio.out


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
    assert "Review import: read 2 rows" in stdio.out
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


def test_review_import_dry_run_skips_transform(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    review_path = processed_dir / "transactions_review.xlsx"
    review_path.write_text("", encoding="utf-8")
    transaction_overrides_path = tmp_path / "config" / "transaction_overrides.yaml"
    transaction_overrides_path.parent.mkdir(parents=True)
    transaction_overrides_path.write_text("entries: []\n", encoding="utf-8")
    settings = SimpleNamespace(
        processed_path=processed_dir,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=processed_dir / "review_state.parquet",
    )
    captured: dict[str, object] = {}

    def _import(**kwargs: object) -> ReviewImportResult:
        captured.update(kwargs)
        return ReviewImportResult(rows_read=1)

    def _transform(_settings: object) -> object:
        raise AssertionError("transform should not run during dry-run import")

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
    monkeypatch.setattr("finance_tooling.commands.review_import.run_transform", _transform)

    exit_code = main(["review-import", "--dry-run"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert captured["dry_run"] is True
    assert "Dry run: no override file was written." in stdio.out


def test_review_import_runs_transform_by_default(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    review_path = processed_dir / "transactions_review.xlsx"
    review_path.write_text("", encoding="utf-8")
    transaction_overrides_path = tmp_path / "config" / "transaction_overrides.yaml"
    transaction_overrides_path.parent.mkdir(parents=True)
    transaction_overrides_path.write_text("entries: []\n", encoding="utf-8")
    settings = SimpleNamespace(
        processed_path=processed_dir,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=processed_dir / "review_state.parquet",
    )
    transform_called: list[object] = []

    monkeypatch.setattr(
        "finance_tooling.commands.common.try_load_settings_for_defaults",
        lambda: settings,
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.load_transaction_override_store",
        lambda path: (TransactionOverrideStore(entries=()), []),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.import_review_into_overrides",
        lambda **kwargs: ReviewImportResult(rows_read=1),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.load_settings_from_env",
        lambda: settings,
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.print_workflow_result",
        lambda workflow_result, verbose=False: print("Transform: ok") or 0,
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.run_transform",
        lambda loaded_settings, backup_command="transform", backup_run=None: (
            transform_called.append(loaded_settings) or object()
        ),
    )

    exit_code = main(["review-import"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert transform_called == [settings]
    assert "Transform: ok" in stdio.out


def test_review_import_can_skip_default_transform(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    review_path = processed_dir / "transactions_review.xlsx"
    review_path.write_text("", encoding="utf-8")
    transaction_overrides_path = tmp_path / "config" / "transaction_overrides.yaml"
    transaction_overrides_path.parent.mkdir(parents=True)
    transaction_overrides_path.write_text("entries: []\n", encoding="utf-8")
    settings = SimpleNamespace(
        processed_path=processed_dir,
        transaction_overrides_path=transaction_overrides_path,
        review_state_path=processed_dir / "review_state.parquet",
    )

    def _transform(
        _settings: object,
        backup_command: str = "transform",
        backup_run: object | None = None,
    ) -> object:
        del backup_command, backup_run
        raise AssertionError("transform should not run with --no-run-transform")

    monkeypatch.setattr(
        "finance_tooling.commands.common.try_load_settings_for_defaults",
        lambda: settings,
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.load_transaction_override_store",
        lambda path: (TransactionOverrideStore(entries=()), []),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.review_import.import_review_into_overrides",
        lambda **kwargs: ReviewImportResult(rows_read=1),
    )
    monkeypatch.setattr("finance_tooling.commands.review_import.run_transform", _transform)

    exit_code = main(["review-import", "--no-run-transform"])
    capsys.readouterr()

    assert exit_code == 0


def test_workflow_status_command_prints_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    monkeypatch.setattr(
        "finance_tooling.commands.workflow_status.load_settings_from_env",
        lambda: object(),
    )
    monkeypatch.setattr(
        "finance_tooling.commands.workflow_status.build_pipeline_state",
        lambda _settings: (
            {
                "status": "warn",
                "raw_source_state": {
                    "raw_file_count": 4,
                    "unique_document_count": 3,
                    "ignored_duplicate_file_count": 1,
                },
                "transformed_state": {
                    "summary_exists": True,
                    "master": {
                        "total_rows": 10,
                        "booking_date_min": "2026-01-01",
                        "booking_date_max": "2026-03-01",
                    },
                },
                "findings": [
                    {
                        "severity": "warning",
                        "code": "duplicate_raw_sources",
                        "message": "Duplicate raw source files detected.",
                    }
                ],
            },
            processed_dir / "state" / "workflow_pipeline_state.json",
        ),
    )

    exit_code = main(["workflow-status"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Pipeline health: warn" in stdio.out
    assert "ignored duplicates" in stdio.out
    assert "Canonical data:" in stdio.out
    assert "Pipeline state: updated" in stdio.out
    assert "workflow_pipeline_state.json" not in stdio.out


def test_ingest_command_prints_backup_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    backup_run = BackupRunResult(
        run_id="20260321T101530000000Z",
        stage="ingest",
        command="ingest",
        created_at="2026-03-21T10:15:30+00:00",
        processed_backup_dir=processed_dir / "backup" / "ingest" / "20260321T101530000000Z",
        config_backup_dir=None,
        manifest_paths=(),
        copied_files=(),
        skipped_missing_files=(),
        pruned_run_ids=(),
    )

    monkeypatch.setattr("finance_tooling.commands.ingest.load_settings_from_env", lambda: object())
    monkeypatch.setattr(
        "finance_tooling.commands.ingest.run_ingest",
        lambda _settings, emit_ingest_summary=False: IngestExecutionResult(
            staged_path=processed_dir / "state" / "ingest_staged_transactions.parquet",
            ingest_summary_path=processed_dir / "state" / "ingest_summary.json",
            files_scanned=0,
            raw_files_discovered=0,
            duplicate_raw_file_count=0,
            files_failed=0,
            transactions_parsed=0,
            hsbc_csv_files_scanned=0,
            parser_low_confidence_file_count=0,
            warnings=(),
            source_files=(),
            selected_source_files=(),
            validations=(),
            parser_selection_diagnostics=(),
            hsbc_merge_metrics={},
            hsbc_period_parse_variant_match_count=0,
            hsbc_boundary_metrics={},
            hsbc_boundary_diagnostics=(),
            hsbc_sign_metrics={},
            hsbc_sign_diagnostics=(),
            hsbc_selection_diagnostics=(),
            ingest_parser_duration_seconds_by_parser={},
            ingest_duration_seconds_by_bank={},
            ingest_text_cache_enabled=False,
            ingest_text_cache_hits=0,
            ingest_text_cache_misses=0,
            ingest_text_cache_write_count=0,
            newly_covered_months=(),
            backup_run=backup_run,
        ),
    )

    exit_code = main(["ingest"])
    stdio = capsys.readouterr()

    assert exit_code == 2
    assert "Run mode: incremental" in stdio.out
    assert "Statements: 0 preexisting, 0 new" in stdio.out
    assert "New coverage months: none" in stdio.out
    assert "Backup run:" not in stdio.out
    assert str(backup_run.processed_backup_dir) not in stdio.out


def test_ingest_command_verbose_prints_backup_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    backup_run = BackupRunResult(
        run_id="20260321T101530000000Z",
        stage="ingest",
        command="ingest",
        created_at="2026-03-21T10:15:30+00:00",
        processed_backup_dir=processed_dir / "backup" / "ingest" / "20260321T101530000000Z",
        config_backup_dir=None,
        manifest_paths=(),
        copied_files=(),
        skipped_missing_files=(),
        pruned_run_ids=(),
    )

    monkeypatch.setattr("finance_tooling.commands.ingest.load_settings_from_env", lambda: object())
    monkeypatch.setattr(
        "finance_tooling.commands.ingest.run_ingest",
        lambda _settings, emit_ingest_summary=False: IngestExecutionResult(
            staged_path=processed_dir / "state" / "ingest_staged_transactions.parquet",
            staged_batch_manifest_path=(
                processed_dir / "state" / "ingest_staged_batch_manifest.json"
            ),
            ingest_summary_path=processed_dir / "state" / "ingest_summary.json",
            files_scanned=0,
            raw_files_discovered=0,
            duplicate_raw_file_count=0,
            files_failed=0,
            transactions_parsed=0,
            hsbc_csv_files_scanned=0,
            parser_low_confidence_file_count=0,
            warnings=(),
            source_files=(),
            selected_source_files=(),
            validations=(),
            parser_selection_diagnostics=(),
            hsbc_merge_metrics={},
            hsbc_period_parse_variant_match_count=0,
            hsbc_boundary_metrics={},
            hsbc_boundary_diagnostics=(),
            hsbc_sign_metrics={},
            hsbc_sign_diagnostics=(),
            hsbc_selection_diagnostics=(),
            ingest_parser_duration_seconds_by_parser={},
            ingest_duration_seconds_by_bank={},
            ingest_text_cache_enabled=False,
            ingest_text_cache_hits=0,
            ingest_text_cache_misses=0,
            ingest_text_cache_write_count=0,
            newly_covered_months=("2026-03",),
            backup_run=backup_run,
        ),
    )

    exit_code = main(["ingest", "--verbose"])
    stdio = capsys.readouterr()

    assert exit_code == 2
    assert "Backup run: 20260321T101530000000Z" in stdio.out
    assert str(backup_run.processed_backup_dir) not in stdio.out


def test_ingest_command_summarizes_reconciliation_and_new_months(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    monkeypatch.setattr("finance_tooling.commands.ingest.load_settings_from_env", lambda: object())
    monkeypatch.setattr(
        "finance_tooling.commands.ingest.run_ingest",
        lambda _settings, emit_ingest_summary=False: IngestExecutionResult(
            staged_path=processed_dir / "state" / "ingest_staged_transactions.parquet",
            files_scanned=3,
            raw_files_discovered=3,
            duplicate_raw_file_count=0,
            files_failed=0,
            transactions_parsed=12,
            hsbc_csv_files_scanned=0,
            parser_low_confidence_file_count=0,
            warnings=(),
            source_files=(),
            selected_source_files=(),
            validations=(
                StatementValidation(
                    source_file=Path("a.pdf"),
                    bank="hsbc",
                    parser="hsbc",
                    statement_type="statement",
                    opening_balance=Decimal("100"),
                    closing_balance=Decimal("80"),
                    transaction_sum=Decimal("-20"),
                    expected_closing_balance=Decimal("80"),
                    difference=Decimal("0"),
                    status="pass",
                    reason=None,
                    severity="info",
                ),
                StatementValidation(
                    source_file=Path("b.pdf"),
                    bank="hsbc",
                    parser="hsbc",
                    statement_type="statement",
                    opening_balance=Decimal("100"),
                    closing_balance=Decimal("70"),
                    transaction_sum=Decimal("-20"),
                    expected_closing_balance=Decimal("80"),
                    difference=Decimal("10"),
                    status="fail",
                    reason="mismatch",
                    severity="warning",
                ),
            ),
            parser_selection_diagnostics=(),
            hsbc_merge_metrics={},
            hsbc_period_parse_variant_match_count=0,
            hsbc_boundary_metrics={},
            hsbc_boundary_diagnostics=(),
            hsbc_sign_metrics={},
            hsbc_sign_diagnostics=(),
            hsbc_selection_diagnostics=(),
            ingest_parser_duration_seconds_by_parser={},
            ingest_duration_seconds_by_bank={},
            ingest_text_cache_enabled=False,
            ingest_text_cache_hits=0,
            ingest_text_cache_misses=0,
            ingest_text_cache_write_count=0,
            newly_covered_months=("2026-01", "2026-02"),
            run_mode="incremental",
            files_selected_for_processing=2,
            files_skipped_already_committed=5,
        ),
    )

    exit_code = main(["ingest"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Run mode: incremental" in stdio.out
    assert "Statements: 5 preexisting, 2 new" in stdio.out
    assert "New coverage months: 2026-01, 2026-02" in stdio.out
    assert "New transactions: 12" in stdio.out
    assert "Reconciliation: 1 pass, 1 fail, 0 uncheckable" in stdio.out
    assert "Failure reasons: mismatch x1; abs EUR gap 10.00" in stdio.out


def test_transform_command_prints_backup_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    config_dir = tmp_path / "config"
    result_backup_run = BackupRunResult(
        run_id="20260321T101530000000Z",
        stage="transform",
        command="transform",
        created_at="2026-03-21T10:15:30+00:00",
        processed_backup_dir=processed_dir / "backup" / "transform" / "20260321T101530000000Z",
        config_backup_dir=config_dir / "backup" / "transform" / "20260321T101530000000Z",
        manifest_paths=(),
        copied_files=(),
        skipped_missing_files=(),
        pruned_run_ids=(),
    )

    monkeypatch.setattr(
        "finance_tooling.commands.transform.load_settings_from_env", lambda: object()
    )
    def _run_transform(
        _settings: object,
        staged_path: Path | None = None,
        backup_command: str = "transform",
        backup_run: object | None = None,
    ) -> WorkflowResult:
        del staged_path, backup_command, backup_run
        return WorkflowResult(
            dashboard_path=processed_dir / "finance_dashboard.html",
            parquet_path=processed_dir / "transactions_master.parquet",
            csv_path=processed_dir / "transactions_normalized.csv",
            json_path=processed_dir / "transactions_normalized.json",
            summary_path=processed_dir / "run_summary.json",
            completeness_path=processed_dir / "completeness_report.json",
            files_scanned=1,
            files_failed=0,
            transactions_parsed=1,
            new_rows=1,
            total_rows=1,
            completeness_status="pass",
            completeness_coverage_ratio=1.0,
            missing_source_file_count=0,
            reconciliation_checkable_file_count=0,
            reconciliation_fail_count=0,
            reconciliation_uncheckable_file_count=0,
            reconciliation_pass_ratio=None,
            categorized_count=1,
            uncategorized_count=0,
            categorized_amount_eur_abs=1.0,
            uncategorized_amount_eur_abs=0.0,
            categorized_amount_eur_abs_ratio=1.0,
            uncategorized_amount_eur_abs_ratio=0.0,
            backup_run=result_backup_run,
        )

    monkeypatch.setattr("finance_tooling.commands.transform.run_transform", _run_transform)

    exit_code = main(["transform"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Transactions: 1 total" in stdio.out
    assert "Uncategorized exposure: 0 transactions (0.00%), EUR 0.00 (0.00% of Income)" in stdio.out
    assert "Uncategorized delta: n/a" in stdio.out
    assert "Backup run:" not in stdio.out
    assert "Categorization by transaction count:" not in stdio.out
    assert "transactions_master.parquet" not in stdio.out


def test_transform_command_verbose_prints_backup_and_detailed_metrics(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    config_dir = tmp_path / "config"
    result_backup_run = BackupRunResult(
        run_id="20260321T101530000000Z",
        stage="transform",
        command="transform",
        created_at="2026-03-21T10:15:30+00:00",
        processed_backup_dir=processed_dir / "backup" / "transform" / "20260321T101530000000Z",
        config_backup_dir=config_dir / "backup" / "transform" / "20260321T101530000000Z",
        manifest_paths=(),
        copied_files=(),
        skipped_missing_files=(),
        pruned_run_ids=(),
    )

    monkeypatch.setattr(
        "finance_tooling.commands.transform.load_settings_from_env", lambda: object()
    )
    def _run_transform(
        _settings: object,
        staged_path: Path | None = None,
        backup_command: str = "transform",
        backup_run: object | None = None,
    ) -> WorkflowResult:
        del staged_path, backup_command, backup_run
        return WorkflowResult(
            dashboard_path=processed_dir / "finance_dashboard.html",
            parquet_path=processed_dir / "transactions_master.parquet",
            csv_path=processed_dir / "transactions_normalized.csv",
            json_path=processed_dir / "transactions_normalized.json",
            summary_path=processed_dir / "run_summary.json",
            completeness_path=processed_dir / "completeness_report.json",
            files_scanned=1,
            files_failed=0,
            transactions_parsed=1,
            new_rows=1,
            total_rows=1,
            completeness_status="pass",
            completeness_coverage_ratio=1.0,
            missing_source_file_count=0,
            reconciliation_checkable_file_count=0,
            reconciliation_fail_count=0,
            reconciliation_uncheckable_file_count=0,
            reconciliation_pass_ratio=None,
            categorized_count=1,
            uncategorized_count=0,
            categorized_amount_eur_abs=1.0,
            uncategorized_amount_eur_abs=0.0,
            categorized_amount_eur_abs_ratio=1.0,
            uncategorized_amount_eur_abs_ratio=0.0,
            categorized_count_delta=1,
            uncategorized_count_delta=-1,
            categorized_amount_eur_abs_delta=1.0,
            uncategorized_amount_eur_abs_delta=-1.0,
            backup_run=result_backup_run,
        )

    monkeypatch.setattr("finance_tooling.commands.transform.run_transform", _run_transform)

    exit_code = main(["transform", "--verbose"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Backup run: 20260321T101530000000Z" in stdio.out
    assert str(result_backup_run.config_backup_dir) not in stdio.out
    assert (
        "Categorization by transaction count: "
        "0.00% uncategorized / 100.00% categorized"
    ) in stdio.out
    assert (
        "Categorization by EUR amount vs Income: "
        "0.00% uncategorized / 100.00% categorized"
    ) in stdio.out

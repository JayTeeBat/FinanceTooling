from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from finance_tooling.__main__ import main
from finance_tooling.backup import BackupRunResult
from finance_tooling.models import WorkflowResult
from finance_tooling.review_import import ReviewImportResult
from finance_tooling.transaction_overrides import TransactionOverrideStore
from finance_tooling.workflow.ingest_stage import IngestExecutionResult


def test_main_without_subcommand_prints_help(capsys) -> None:
    exit_code = main([])
    stdio = capsys.readouterr()

    assert exit_code == 1
    assert "usage:" in stdio.out


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
        min_abs_amount: str | None = None,
        max_abs_amount: str | None = None,
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
    assert captured["normalized_path"] == processed_dir / "outputs" / "transform_transactions.csv"
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
        min_abs_amount: str | None = None,
        max_abs_amount: str | None = None,
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
                "min_abs_amount": min_abs_amount,
                "max_abs_amount": max_abs_amount,
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
            "--min-abs-amount",
            "50",
            "--max-abs-amount",
            "200",
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
    assert captured["min_abs_amount"] == "50"
    assert captured["max_abs_amount"] == "200"
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
            processed_dir / "pipeline_state.json",
        ),
    )

    exit_code = main(["workflow-status"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Pipeline health: warn" in stdio.out
    assert "ignored duplicates" in stdio.out
    assert "pipeline_state.json" in stdio.out


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
            backup_run=backup_run,
        ),
    )

    exit_code = main(["ingest"])
    stdio = capsys.readouterr()

    assert exit_code == 2
    assert "Backup run: 20260321T101530000000Z" in stdio.out
    assert str(backup_run.processed_backup_dir) in stdio.out


def test_transform_command_prints_backup_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    config_dir = tmp_path / "config"
    backup_run = BackupRunResult(
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
    monkeypatch.setattr(
        "finance_tooling.commands.transform.run_transform",
        lambda _settings, staged_path=None: WorkflowResult(
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
            backup_run=backup_run,
        ),
    )

    exit_code = main(["transform"])
    stdio = capsys.readouterr()

    assert exit_code == 0
    assert "Backup run: 20260321T101530000000Z" in stdio.out
    assert str(backup_run.config_backup_dir) in stdio.out

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finance_tooling.core.backup import create_stage_backup_run


def test_create_stage_backup_run_copies_full_state_and_prunes_by_run_day(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed"
    config_dir = data_dir / "config"
    processed_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    staged_file = processed_dir / "outputs" / "transform_transactions.parquet"
    category_rules = config_dir / "category_rules.yaml"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text("master", encoding="utf-8")
    category_rules.write_text("version: 1\nrules: []\n", encoding="utf-8")

    backup_root = data_dir / "backup"
    for run_id in (
        "20260310-010000-000000",
        "20260310-020000-000000",
        "20260310-030000-000000",
        "20260310-040000-000000",
    ):
        snapshot_dir = backup_root / run_id
        (snapshot_dir / "processed").mkdir(parents=True, exist_ok=True)
        (snapshot_dir / "config").mkdir(parents=True, exist_ok=True)
        (snapshot_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "retention_day_local": "2026-03-10",
                    "created_at": "2026-03-10T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

    result = create_stage_backup_run(
        stage="transform",
        command="update",
        processed_dir=processed_dir,
        processed_targets=(staged_file,),
        config_targets=(category_rules,),
    )

    assert result.backup_root == backup_root
    assert result.snapshot_dir is not None
    assert result.processed_backup_dir is not None
    assert result.config_backup_dir is not None
    assert (result.processed_backup_dir / "outputs" / staged_file.name).exists()
    assert (result.config_backup_dir / category_rules.name).exists()
    assert (result.snapshot_dir / "manifest.json").exists()
    retained = sorted(
        child.name for child in backup_root.iterdir() if child.is_dir() and child.name != "legacy"
    )
    assert len(retained) == 4
    assert "20260310-010000-000000" not in retained
    assert result.pruned_run_ids == ("20260310-010000-000000",)


def test_create_stage_backup_run_skips_unreadable_processed_paths(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed"
    config_dir = data_dir / "config"
    processed_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    readable = processed_dir / "outputs" / "transform_transactions.parquet"
    unreadable = processed_dir / "archive" / "missing-target"
    category_rules = config_dir / "category_rules.yaml"
    readable.parent.mkdir(parents=True, exist_ok=True)
    unreadable.parent.mkdir(parents=True, exist_ok=True)
    readable.write_text("master", encoding="utf-8")
    unreadable.symlink_to(processed_dir / "does-not-exist")
    category_rules.write_text("version: 1\nrules: []\n", encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="Skipping unreadable backup source file"):
        result = create_stage_backup_run(
            stage="transform",
            command="update",
            processed_dir=processed_dir,
            config_targets=(category_rules,),
        )

    assert result.processed_backup_dir is not None
    assert (result.processed_backup_dir / "outputs" / readable.name).exists()
    assert not (result.processed_backup_dir / "archive" / unreadable.name).exists()


def test_create_stage_backup_run_migrates_legacy_backups_and_records_missing_files(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed"
    config_dir = data_dir / "config"
    processed_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    legacy_processed_backup = processed_dir / "backup" / "ingest" / "old-run"
    legacy_processed_backup.mkdir(parents=True, exist_ok=True)
    (legacy_processed_backup / "old.txt").write_text("processed", encoding="utf-8")
    legacy_config_backup = config_dir / "backup"
    legacy_config_backup.mkdir(parents=True, exist_ok=True)
    legacy_file_backup = legacy_config_backup / "transaction_overrides.yaml.20260310-000000.bak"
    legacy_file_backup.write_text("config", encoding="utf-8")

    with pytest.warns(FutureWarning, match="Migrated legacy backup layout"):
        result = create_stage_backup_run(
            stage="ingest",
            command="ingest",
            processed_dir=processed_dir,
            processed_targets=(processed_dir / "state" / "ingest_staged_transactions.parquet",),
            config_targets=(
                config_dir / "project_rules.yaml",
                config_dir / "transaction_overrides.yaml",
            ),
        )

    assert result.processed_backup_dir is not None
    assert result.config_backup_dir is not None
    assert result.copied_files == ()
    assert len(result.skipped_missing_files) == 2
    assert result.migrated_legacy_paths

    legacy_root = result.backup_root / "legacy"  # type: ignore[operator]
    assert legacy_root.exists()
    assert not (processed_dir / "backup").exists()
    assert not legacy_file_backup.exists()

    manifest = json.loads((result.snapshot_dir / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[arg-type]
    assert manifest["copied_files"] == []
    assert sorted(manifest["skipped_missing_files"]) == sorted(
        str(path) for path in result.skipped_missing_files
    )
    assert manifest["migrated_legacy_paths"]

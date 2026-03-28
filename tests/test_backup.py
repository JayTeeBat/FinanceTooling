from __future__ import annotations

import json
from pathlib import Path

from finance_tooling.backup import create_stage_backup_run


def test_create_stage_backup_run_copies_files_and_prunes_oldest_run(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    config_dir = tmp_path / "config"
    processed_dir.mkdir()
    config_dir.mkdir()

    staged_file = processed_dir / "outputs" / "transform_transactions.parquet"
    category_rules = config_dir / "category_rules.yaml"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text("master", encoding="utf-8")
    category_rules.write_text("version: 1\nrules: []\n", encoding="utf-8")

    processed_backup_root = processed_dir / "backup" / "transform"
    config_backup_root = config_dir / "backup" / "transform"
    for index in range(10):
        run_id = f"20260310T00000{index}000000Z"
        (processed_backup_root / run_id).mkdir(parents=True, exist_ok=True)
        (config_backup_root / run_id).mkdir(parents=True, exist_ok=True)

    result = create_stage_backup_run(
        stage="transform",
        command="update",
        processed_dir=processed_dir,
        processed_targets=(staged_file,),
        config_dir=config_dir,
        config_targets=(category_rules,),
    )

    assert result.processed_backup_dir is not None
    assert result.config_backup_dir is not None
    assert (result.processed_backup_dir / staged_file.name).exists()
    assert (result.config_backup_dir / category_rules.name).exists()
    assert (result.processed_backup_dir / "backup_manifest.json").exists()
    assert (result.config_backup_dir / "backup_manifest.json").exists()
    assert len(list(processed_backup_root.iterdir())) == 10
    assert len(list(config_backup_root.iterdir())) == 10
    assert not (processed_backup_root / "20260310T000000000000Z").exists()
    assert not (config_backup_root / "20260310T000000000000Z").exists()
    assert result.pruned_run_ids == ("20260310T000000000000Z",)


def test_create_stage_backup_run_records_missing_files_in_manifest(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    config_dir = tmp_path / "config"
    processed_dir.mkdir()
    config_dir.mkdir()

    result = create_stage_backup_run(
        stage="ingest",
        command="ingest",
        processed_dir=processed_dir,
        processed_targets=(processed_dir / "state" / "ingest_staged_transactions.parquet",),
        config_dir=config_dir,
        config_targets=(config_dir / "project_rules.yaml",),
    )

    assert result.processed_backup_dir is not None
    assert result.config_backup_dir is not None
    assert result.copied_files == ()
    assert len(result.skipped_missing_files) == 2

    processed_manifest = json.loads(
        (result.processed_backup_dir / "backup_manifest.json").read_text(encoding="utf-8")
    )
    config_manifest = json.loads(
        (result.config_backup_dir / "backup_manifest.json").read_text(encoding="utf-8")
    )
    assert processed_manifest["copied_files"] == []
    assert sorted(processed_manifest["skipped_missing_files"]) == sorted(
        [str(path) for path in result.skipped_missing_files]
    )
    assert config_manifest["copied_files"] == []

"""Backup helpers for config artifacts and pipeline stage snapshots."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

BackupRootKind = Literal["processed", "config"]


@dataclass(frozen=True)
class BackupSnapshotFile:
    """Single file captured in a stage backup snapshot."""

    source_path: Path
    destination_path: Path
    root_kind: BackupRootKind


@dataclass(frozen=True)
class BackupRunResult:
    """Result metadata for a stage-scoped backup snapshot."""

    run_id: str
    stage: str
    command: str
    created_at: str
    processed_backup_dir: Path | None
    config_backup_dir: Path | None
    manifest_paths: tuple[Path, ...]
    copied_files: tuple[BackupSnapshotFile, ...]
    skipped_missing_files: tuple[Path, ...]
    pruned_run_ids: tuple[str, ...]


def default_backup_path(path: Path) -> Path:
    """Build a default timestamped backup path under the sibling backup folder."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return path.parent / "backup" / f"{path.name}.{timestamp}.bak"


def create_backup(path: Path, backup_path: Path | None = None, *, keep: int = 10) -> Path | None:
    """Create a backup copy for a path and prune older backups with FIFO retention."""
    if not path.exists():
        return None
    destination = backup_path or default_backup_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    prune_backups(path, destination.parent, keep=keep)
    return destination


def prune_backups(path: Path, backup_dir: Path, *, keep: int = 10) -> None:
    """Keep only the latest backups for a file family in the backup directory."""
    if keep < 1 or not backup_dir.exists():
        return
    candidates = sorted(
        (
            candidate
            for candidate in backup_dir.iterdir()
            if candidate.is_file()
            and candidate.name.startswith(path.name)
            and ".bak" in candidate.name
        ),
        key=lambda candidate: candidate.name,
    )
    for candidate in candidates[:-keep]:
        candidate.unlink(missing_ok=True)


def _make_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _stage_backup_root(base_dir: Path, stage: str) -> Path:
    return base_dir / "backup" / stage


def _run_manifest_payload(
    *,
    result: BackupRunResult,
    scoped_copied_files: list[BackupSnapshotFile],
    scoped_skipped_missing_files: list[Path],
) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "stage": result.stage,
        "command": result.command,
        "created_at": result.created_at,
        "processed_backup_dir": (
            str(result.processed_backup_dir) if result.processed_backup_dir is not None else None
        ),
        "config_backup_dir": (
            str(result.config_backup_dir) if result.config_backup_dir is not None else None
        ),
        "copied_files": [
            {
                **asdict(copy),
                "source_path": str(copy.source_path),
                "destination_path": str(copy.destination_path),
            }
            for copy in scoped_copied_files
        ],
        "skipped_missing_files": [str(path) for path in scoped_skipped_missing_files],
        "pruned_run_ids": list(result.pruned_run_ids),
    }


def _write_manifest(
    manifest_path: Path,
    *,
    result: BackupRunResult,
    root_kind: BackupRootKind,
) -> None:
    copied_files = [copy for copy in result.copied_files if copy.root_kind == root_kind]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            _run_manifest_payload(
                result=result,
                scoped_copied_files=copied_files,
                scoped_skipped_missing_files=list(result.skipped_missing_files),
            ),
            indent=2,
        ),
        encoding="utf-8",
    )


def _prune_stage_runs(
    *,
    stage: str,
    keep: int,
    processed_base_dir: Path | None,
    config_base_dir: Path | None,
) -> tuple[str, ...]:
    if keep < 1:
        return ()

    candidate_run_ids: set[str] = set()
    for base_dir in (processed_base_dir, config_base_dir):
        if base_dir is None:
            continue
        stage_root = _stage_backup_root(base_dir, stage)
        if not stage_root.exists():
            continue
        candidate_run_ids.update(
            child.name for child in stage_root.iterdir() if child.is_dir() and child.name
        )

    run_ids = sorted(candidate_run_ids)
    pruned = tuple(run_ids[:-keep])
    for run_id in pruned:
        for base_dir in (processed_base_dir, config_base_dir):
            if base_dir is None:
                continue
            shutil.rmtree(_stage_backup_root(base_dir, stage) / run_id, ignore_errors=True)
    return pruned


def create_stage_backup_run(
    *,
    stage: str,
    command: str,
    processed_dir: Path,
    processed_targets: tuple[Path, ...] = (),
    config_dir: Path | None = None,
    config_targets: tuple[Path, ...] = (),
    keep: int = 10,
) -> BackupRunResult:
    """Create a stage-scoped backup snapshot with run-folder retention."""
    run_id = _make_run_id()
    created_at = datetime.now(UTC).isoformat()
    processed_backup_dir = _stage_backup_root(processed_dir, stage) / run_id
    config_backup_dir = (
        (_stage_backup_root(config_dir, stage) / run_id) if config_dir is not None else None
    )

    copied_files: list[BackupSnapshotFile] = []
    skipped_missing_files: list[Path] = []
    manifest_paths: list[Path] = []
    try:
        if processed_targets:
            processed_backup_dir.mkdir(parents=True, exist_ok=True)
        if config_targets and config_backup_dir is not None:
            config_backup_dir.mkdir(parents=True, exist_ok=True)

        for root_kind, targets, destination_dir in (
            ("processed", processed_targets, processed_backup_dir),
            ("config", config_targets, config_backup_dir),
        ):
            if destination_dir is None:
                continue
            for target in targets:
                if not target.exists():
                    skipped_missing_files.append(target)
                    continue
                destination = destination_dir / target.name
                shutil.copy2(target, destination)
                copied_files.append(
                    BackupSnapshotFile(
                        source_path=target,
                        destination_path=destination,
                        root_kind=root_kind,
                    )
                )

        result = BackupRunResult(
            run_id=run_id,
            stage=stage,
            command=command,
            created_at=created_at,
            processed_backup_dir=processed_backup_dir if processed_targets else None,
            config_backup_dir=config_backup_dir if config_targets else None,
            manifest_paths=(),
            copied_files=tuple(copied_files),
            skipped_missing_files=tuple(skipped_missing_files),
            pruned_run_ids=(),
        )

        if processed_targets:
            manifest_path = processed_backup_dir / "backup_manifest.json"
            _write_manifest(manifest_path, result=result, root_kind="processed")
            manifest_paths.append(manifest_path)
        if config_targets and config_backup_dir is not None:
            manifest_path = config_backup_dir / "backup_manifest.json"
            _write_manifest(manifest_path, result=result, root_kind="config")
            manifest_paths.append(manifest_path)

        pruned_run_ids = _prune_stage_runs(
            stage=stage,
            keep=keep,
            processed_base_dir=processed_dir if processed_targets else None,
            config_base_dir=config_dir if config_targets else None,
        )
        finalized = BackupRunResult(
            run_id=run_id,
            stage=stage,
            command=command,
            created_at=created_at,
            processed_backup_dir=processed_backup_dir if processed_targets else None,
            config_backup_dir=config_backup_dir if config_targets else None,
            manifest_paths=tuple(manifest_paths),
            copied_files=tuple(copied_files),
            skipped_missing_files=tuple(skipped_missing_files),
            pruned_run_ids=pruned_run_ids,
        )

        for manifest_path in manifest_paths:
            _write_manifest(
                manifest_path,
                result=finalized,
                root_kind="processed" if manifest_path.parent == processed_backup_dir else "config",
            )
        return finalized
    except OSError:
        shutil.rmtree(processed_backup_dir, ignore_errors=True)
        if config_backup_dir is not None:
            shutil.rmtree(config_backup_dir, ignore_errors=True)
        raise

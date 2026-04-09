"""Unified snapshot backup helpers for mutable pipeline state."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

BackupRootKind = Literal["processed", "config", "legacy"]
RETENTION_DAY_KEEP_COUNT = 7
RETENTION_SNAPSHOTS_PER_DAY = 3


@dataclass(frozen=True)
class BackupSnapshotFile:
    """Single file captured in a backup snapshot."""

    source_path: Path
    destination_path: Path
    root_kind: BackupRootKind


@dataclass(frozen=True)
class BackupRunResult:
    """Result metadata for a unified backup snapshot."""

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
    backup_root: Path | None = None
    snapshot_dir: Path | None = None
    retention_day_local: str | None = None
    migrated_legacy_paths: tuple[tuple[Path, Path], ...] = ()


def backup_root_from_processed_dir(processed_dir: Path) -> Path:
    """Return the unified backup root for a processed tree."""
    return processed_dir.resolve().parent / "backup"


def _make_snapshot_id(now_local: datetime) -> str:
    return now_local.strftime("%Y%m%d-%H%M%S-%f")


def _copy_tree_files(source_dir: Path, destination_dir: Path) -> list[BackupSnapshotFile]:
    copied_files: list[BackupSnapshotFile] = []
    if not source_dir.exists():
        return copied_files
    for source_path in sorted(source_dir.rglob("*")):
        if source_path.is_dir():
            continue
        relative_path = source_path.relative_to(source_dir)
        destination_path = destination_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        copied_files.append(
            BackupSnapshotFile(
                source_path=source_path,
                destination_path=destination_path,
                root_kind="processed",
            )
        )
    return copied_files


def _copy_config_files(
    targets: tuple[Path, ...],
    destination_dir: Path,
) -> tuple[list[BackupSnapshotFile], list[Path]]:
    copied_files: list[BackupSnapshotFile] = []
    skipped_missing_files: list[Path] = []
    destination_dir.mkdir(parents=True, exist_ok=True)
    for target in targets:
        if not target.exists():
            skipped_missing_files.append(target)
            continue
        destination_path = destination_dir / target.name
        shutil.copy2(target, destination_path)
        copied_files.append(
            BackupSnapshotFile(
                source_path=target,
                destination_path=destination_path,
                root_kind="config",
            )
        )
    return copied_files, skipped_missing_files


def _iter_legacy_file_backups(target: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in (f"{target.name}*.bak",):
        candidates.extend(
            candidate
            for candidate in target.parent.glob(pattern)
            if candidate.is_file()
        )
    return sorted(set(candidates))


def _legacy_destination_name(source: Path) -> str:
    resolved = source.expanduser().resolve()
    parts = [part for part in resolved.parts if part not in {resolved.anchor, ""}]
    return "__".join(parts[-4:]) or source.name


def _migrate_legacy_backups(
    *,
    backup_root: Path,
    processed_dir: Path,
    config_targets: tuple[Path, ...],
) -> tuple[tuple[Path, Path], ...]:
    migration_pairs: list[tuple[Path, Path]] = []
    legacy_root = backup_root / "legacy"
    legacy_root.mkdir(parents=True, exist_ok=True)

    candidate_dirs = [processed_dir / "backup"]
    candidate_dirs.extend(target.parent / "backup" for target in config_targets)
    seen_dirs: set[Path] = set()
    for source_dir in candidate_dirs:
        resolved_source = source_dir.expanduser().resolve()
        if resolved_source == backup_root.resolve():
            continue
        if resolved_source in seen_dirs or not source_dir.exists():
            continue
        seen_dirs.add(resolved_source)
        destination = legacy_root / _legacy_destination_name(source_dir)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(source_dir), str(destination))
        migration_pairs.append((source_dir, destination))

    seen_files: set[Path] = set()
    for target in config_targets:
        for source_file in _iter_legacy_file_backups(target):
            resolved_source = source_file.expanduser().resolve()
            if resolved_source in seen_files:
                continue
            seen_files.add(resolved_source)
            destination_dir = legacy_root / _legacy_destination_name(source_file.parent)
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / source_file.name
            if destination.exists():
                destination.unlink()
            shutil.move(str(source_file), str(destination))
            migration_pairs.append((source_file, destination))

    if migration_pairs:
        migration_manifest_path = legacy_root / "migration_manifest.json"
        existing_payload: list[dict[str, str]] = []
        if migration_manifest_path.exists():
            try:
                payload = json.loads(migration_manifest_path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    existing_payload = [
                        item
                        for item in payload
                        if isinstance(item, dict)
                        and isinstance(item.get("source"), str)
                        and isinstance(item.get("destination"), str)
                    ]
            except (OSError, json.JSONDecodeError):
                existing_payload = []
        existing_payload.extend(
            {
                "migrated_at": datetime.now(UTC).isoformat(),
                "source": str(source),
                "destination": str(destination),
            }
            for source, destination in migration_pairs
        )
        migration_manifest_path.write_text(
            json.dumps(existing_payload, indent=2),
            encoding="utf-8",
        )
    return tuple(migration_pairs)


def _snapshot_manifest_payload(result: BackupRunResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "stage": result.stage,
        "command": result.command,
        "created_at": result.created_at,
        "retention_day_local": result.retention_day_local,
        "backup_root": str(result.backup_root) if result.backup_root is not None else None,
        "snapshot_dir": str(result.snapshot_dir) if result.snapshot_dir is not None else None,
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
            for copy in result.copied_files
        ],
        "skipped_missing_files": [str(path) for path in result.skipped_missing_files],
        "pruned_run_ids": list(result.pruned_run_ids),
        "migrated_legacy_paths": [
            {"source": str(source), "destination": str(destination)}
            for source, destination in result.migrated_legacy_paths
        ],
    }


def _write_manifest(manifest_path: Path, result: BackupRunResult) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(_snapshot_manifest_payload(result), indent=2),
        encoding="utf-8",
    )


def _load_retention_day(snapshot_dir: Path) -> str | None:
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    retention_day = payload.get("retention_day_local")
    return str(retention_day) if isinstance(retention_day, str) and retention_day else None


def _prune_snapshot_runs(backup_root: Path) -> tuple[str, ...]:
    if not backup_root.exists():
        return ()

    snapshots_by_day: dict[str, list[Path]] = {}
    for child in backup_root.iterdir():
        if not child.is_dir() or child.name == "legacy":
            continue
        retention_day = _load_retention_day(child)
        if retention_day is None:
            continue
        snapshots_by_day.setdefault(retention_day, []).append(child)

    retained_days = sorted(snapshots_by_day.keys(), reverse=True)[:RETENTION_DAY_KEEP_COUNT]
    pruned_run_ids: list[str] = []
    for retention_day, snapshots in snapshots_by_day.items():
        sorted_snapshots = sorted(snapshots, key=lambda snapshot: snapshot.name, reverse=True)
        keep_count = RETENTION_SNAPSHOTS_PER_DAY if retention_day in retained_days else 0
        for snapshot_dir in sorted_snapshots[keep_count:]:
            pruned_run_ids.append(snapshot_dir.name)
            shutil.rmtree(snapshot_dir, ignore_errors=True)
    return tuple(sorted(pruned_run_ids))


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
    """Create a unified snapshot backup for the current mutable pipeline state."""
    del processed_targets, config_dir, keep
    now_local = datetime.now().astimezone()
    run_id = _make_snapshot_id(now_local)
    created_at = datetime.now(UTC).isoformat()
    retention_day_local = now_local.date().isoformat()
    backup_root = backup_root_from_processed_dir(processed_dir)
    snapshot_dir = backup_root / run_id
    processed_backup_dir = snapshot_dir / "processed"
    config_backup_dir = snapshot_dir / "config"
    manifest_path = snapshot_dir / "manifest.json"

    copied_files: list[BackupSnapshotFile] = []
    skipped_missing_files: list[Path] = []
    migrated_legacy_paths = _migrate_legacy_backups(
        backup_root=backup_root,
        processed_dir=processed_dir,
        config_targets=config_targets,
    )

    try:
        processed_backup_dir.mkdir(parents=True, exist_ok=True)
        copied_files.extend(_copy_tree_files(processed_dir, processed_backup_dir))
        config_copies, missing_config_targets = _copy_config_files(
            config_targets,
            config_backup_dir,
        )
        copied_files.extend(config_copies)
        skipped_missing_files.extend(missing_config_targets)

        provisional = BackupRunResult(
            run_id=run_id,
            stage=stage,
            command=command,
            created_at=created_at,
            processed_backup_dir=processed_backup_dir,
            config_backup_dir=config_backup_dir,
            manifest_paths=(),
            copied_files=tuple(copied_files),
            skipped_missing_files=tuple(skipped_missing_files),
            pruned_run_ids=(),
            backup_root=backup_root,
            snapshot_dir=snapshot_dir,
            retention_day_local=retention_day_local,
            migrated_legacy_paths=migrated_legacy_paths,
        )
        _write_manifest(manifest_path, provisional)
        pruned_run_ids = _prune_snapshot_runs(backup_root)
        finalized = BackupRunResult(
            run_id=run_id,
            stage=stage,
            command=command,
            created_at=created_at,
            processed_backup_dir=processed_backup_dir,
            config_backup_dir=config_backup_dir,
            manifest_paths=(manifest_path,),
            copied_files=tuple(copied_files),
            skipped_missing_files=tuple(skipped_missing_files),
            pruned_run_ids=pruned_run_ids,
            backup_root=backup_root,
            snapshot_dir=snapshot_dir,
            retention_day_local=retention_day_local,
            migrated_legacy_paths=migrated_legacy_paths,
        )
        _write_manifest(manifest_path, finalized)
        return finalized
    except OSError:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise

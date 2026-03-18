"""Backup helpers for config artifacts."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path


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

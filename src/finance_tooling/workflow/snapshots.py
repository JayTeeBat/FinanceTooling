"""Pre-run snapshot utilities."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_run_snapshot(
    *,
    snapshot_root: Path,
    run_id: str,
    master_parquet_path: Path,
    ingest_state_path: Path,
    period_status_path: Path,
    category_rules_path: Path,
    category_overrides_path: Path,
) -> Path:
    """Create pre-run snapshot directory with full file copies when present."""
    snapshot_dir = snapshot_root / run_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "master_parquet": master_parquet_path,
        "ingest_state": ingest_state_path,
        "period_status": period_status_path,
        "category_rules": category_rules_path,
        "category_overrides": category_overrides_path,
    }
    manifest: dict[str, dict[str, object]] = {}
    for name, source in files.items():
        if not source.exists():
            manifest[name] = {"exists": False}
            continue
        target = snapshot_dir / source.name
        shutil.copy2(source, target)
        stat = target.stat()
        manifest[name] = {
            "exists": True,
            "source_path": str(source),
            "snapshot_path": str(target),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": _sha256(target),
        }

    (snapshot_dir / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "files": manifest}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return snapshot_dir

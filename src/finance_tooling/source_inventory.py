"""Raw-source inventory and content-based source identity helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast


@dataclass(frozen=True)
class SourceInventoryEntry:
    """Single discovered raw source file and its source-document grouping."""

    source_file: str
    source_document_id: str
    file_size: int
    mtime_ns: int
    is_representative: bool
    representative_source_file: str
    duplicate_group_size: int


@dataclass(frozen=True)
class SourceInventorySnapshot:
    """Machine-readable snapshot of the currently discovered raw corpus."""

    generated_at: str
    raw_file_count: int
    unique_document_count: int
    ignored_duplicate_file_count: int
    entries: tuple[SourceInventoryEntry, ...]


def source_inventory_payload(snapshot: SourceInventorySnapshot) -> dict[str, object]:
    """Return the JSON payload used for persisted source-inventory snapshots."""
    return {
        "generated_at": snapshot.generated_at,
        "raw_file_count": snapshot.raw_file_count,
        "unique_document_count": snapshot.unique_document_count,
        "ignored_duplicate_file_count": snapshot.ignored_duplicate_file_count,
        "duplicate_groups": duplicate_groups(snapshot),
        "entries": [asdict(entry) for entry in snapshot.entries],
    }


def _payload_int(payload: dict[str, object], key: str, default: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def load_source_inventory_payload(payload: dict[str, object]) -> SourceInventorySnapshot:
    """Load a source-inventory snapshot from a JSON-like payload."""
    raw_entries = payload.get("entries", [])
    if not isinstance(raw_entries, list):
        raise ValueError("Invalid source inventory entries in payload")
    typed_entries = cast(list[dict[str, object]], raw_entries)
    entries = tuple(
        SourceInventoryEntry(
            source_file=str(entry["source_file"]),
            source_document_id=str(entry["source_document_id"]),
            file_size=int(cast(int, entry["file_size"])),
            mtime_ns=int(cast(int, entry["mtime_ns"])),
            is_representative=bool(entry["is_representative"]),
            representative_source_file=str(entry["representative_source_file"]),
            duplicate_group_size=int(cast(int, entry["duplicate_group_size"])),
        )
        for entry in typed_entries
    )
    return SourceInventorySnapshot(
        generated_at=str(payload.get("generated_at", "")),
        raw_file_count=_payload_int(payload, "raw_file_count", len(entries)),
        unique_document_count=_payload_int(payload, "unique_document_count", len(entries)),
        ignored_duplicate_file_count=_payload_int(payload, "ignored_duplicate_file_count", 0),
        entries=entries,
    )


def compute_source_document_id(path: Path) -> str:
    """Compute a content-based document id that is robust to path/name changes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_source_inventory(files: list[Path]) -> SourceInventorySnapshot:
    """Build a deduplicated raw-source inventory from discovered files."""
    grouped: dict[str, list[Path]] = {}
    file_stats: dict[Path, tuple[int, int]] = {}
    for path in sorted({entry.resolve() for entry in files}):
        stat = path.stat()
        file_stats[path] = (stat.st_size, stat.st_mtime_ns)
        document_id = compute_source_document_id(path)
        grouped.setdefault(document_id, []).append(path)

    entries: list[SourceInventoryEntry] = []
    for document_id in sorted(grouped):
        group = sorted(grouped[document_id], key=lambda item: str(item))
        representative = group[0]
        for path in group:
            size, mtime_ns = file_stats[path]
            entries.append(
                SourceInventoryEntry(
                    source_file=str(path),
                    source_document_id=document_id,
                    file_size=size,
                    mtime_ns=mtime_ns,
                    is_representative=path == representative,
                    representative_source_file=str(representative),
                    duplicate_group_size=len(group),
                )
            )

    raw_file_count = len(entries)
    unique_document_count = len(grouped)
    return SourceInventorySnapshot(
        generated_at=datetime.now(UTC).isoformat(),
        raw_file_count=raw_file_count,
        unique_document_count=unique_document_count,
        ignored_duplicate_file_count=max(0, raw_file_count - unique_document_count),
        entries=tuple(entries),
    )


def representative_source_files(snapshot: SourceInventorySnapshot) -> list[Path]:
    """Return the canonical representative source files for processing."""
    return [Path(entry.source_file) for entry in snapshot.entries if entry.is_representative]


def duplicate_groups(snapshot: SourceInventorySnapshot) -> list[dict[str, object]]:
    """Summarize duplicate raw-file groups for reporting and health checks."""
    grouped: dict[str, list[str]] = {}
    for entry in snapshot.entries:
        grouped.setdefault(entry.source_document_id, []).append(entry.source_file)

    groups: list[dict[str, object]] = []
    for document_id in sorted(grouped):
        members = sorted(grouped[document_id])
        if len(members) <= 1:
            continue
        groups.append(
            {
                "source_document_id": document_id,
                "representative_source_file": members[0],
                "duplicate_source_files": members[1:],
                "group_size": len(members),
            }
        )
    return groups


def write_source_inventory(path: Path, snapshot: SourceInventorySnapshot) -> Path:
    """Persist a raw-source inventory snapshot to JSON."""
    payload = source_inventory_payload(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_source_inventory(path: Path) -> SourceInventorySnapshot | None:
    """Load a persisted source inventory snapshot when available."""
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid source inventory payload in {path}")
    return load_source_inventory_payload(payload)

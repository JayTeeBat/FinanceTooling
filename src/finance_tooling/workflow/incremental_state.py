"""State store for incremental ingestion source tracking."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

SourceStatus = Literal["new", "changed", "unchanged"]
LastStatus = Literal["success", "failed"]


@dataclass(frozen=True)
class SourceSignature:
    """Stable source-file signature for incremental classification."""

    path: str
    size_bytes: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class IngestStateEntry:
    """Persisted incremental state record for one source file."""

    path: str
    size_bytes: int
    mtime_ns: int
    sha256: str
    first_seen_at: str
    last_ingested_at: str
    last_status: LastStatus
    last_error: str | None
    last_run_id: str
    bank_guess: str | None
    statement_month: str | None


def _timestamp_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.json")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def compute_source_signature(path: Path) -> SourceSignature:
    """Compute incremental signature from file metadata and bytes hash."""
    resolved = path.resolve()
    stat = resolved.stat()
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return SourceSignature(
        path=str(resolved),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=digest,
    )


def load_ingest_state(path: Path) -> dict[str, IngestStateEntry]:
    """Load ingest state map keyed by canonical source path."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    entries: dict[str, IngestStateEntry] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        try:
            entries[key] = IngestStateEntry(
                path=str(value["path"]),
                size_bytes=int(value["size_bytes"]),
                mtime_ns=int(value["mtime_ns"]),
                sha256=str(value["sha256"]),
                first_seen_at=str(value["first_seen_at"]),
                last_ingested_at=str(value["last_ingested_at"]),
                last_status=str(value["last_status"]),  # type: ignore[arg-type]
                last_error=str(value["last_error"]) if value.get("last_error") else None,
                last_run_id=str(value["last_run_id"]),
                bank_guess=str(value["bank_guess"]) if value.get("bank_guess") else None,
                statement_month=(
                    str(value["statement_month"]) if value.get("statement_month") else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return entries


def save_ingest_state(path: Path, entries: dict[str, IngestStateEntry]) -> None:
    """Persist ingest state map keyed by canonical source path."""
    payload = {key: asdict(value) for key, value in sorted(entries.items())}
    _atomic_write_json(path, payload)


def classify_source(
    signature: SourceSignature,
    existing: IngestStateEntry | None,
) -> SourceStatus:
    """Classify source file compared to prior stored state."""
    if existing is None:
        return "new"
    if (
        existing.size_bytes == signature.size_bytes
        and existing.mtime_ns == signature.mtime_ns
        and existing.sha256 == signature.sha256
    ):
        return "unchanged"
    return "changed"


def build_state_entry(
    *,
    signature: SourceSignature,
    existing: IngestStateEntry | None,
    last_status: LastStatus,
    last_error: str | None,
    last_run_id: str,
    bank_guess: str | None,
    statement_month: str | None,
) -> IngestStateEntry:
    """Create next state entry preserving first-seen metadata when available."""
    now = _timestamp_now()
    return IngestStateEntry(
        path=signature.path,
        size_bytes=signature.size_bytes,
        mtime_ns=signature.mtime_ns,
        sha256=signature.sha256,
        first_seen_at=existing.first_seen_at if existing is not None else now,
        last_ingested_at=now,
        last_status=last_status,
        last_error=last_error,
        last_run_id=last_run_id,
        bank_guess=bank_guess,
        statement_month=statement_month,
    )

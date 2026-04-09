"""Persistent cache for extracted PDF statement text."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.core.extract import ExtractedPdfText

_CACHE_COLUMNS = [
    "source_file",
    "mtime_ns",
    "file_size",
    "first_page_text",
    "full_text",
    "cached_at",
]

CacheKey = tuple[str, int, int]


@dataclass(frozen=True)
class CachedExtractionRow:
    """Single cache row for extracted text payload."""

    source_file: str
    mtime_ns: int
    file_size: int
    first_page_text: str
    full_text: str


def build_cache_key(path: Path) -> CacheKey:
    """Build cache key from resolved path, mtime, and size."""
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


def load_text_cache(path: Path) -> tuple[dict[CacheKey, ExtractedPdfText], list[str]]:
    """Load extracted text cache from parquet, returning warnings on failure."""
    if not path.exists():
        return {}, []

    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        return {}, [f"Ingest text cache read failed for {path}: {exc}"]

    missing_columns = [column for column in _CACHE_COLUMNS if column not in frame.columns]
    if missing_columns:
        return {}, [
            f"Ingest text cache schema invalid for {path}: missing {', '.join(missing_columns)}"
        ]

    cache: dict[CacheKey, ExtractedPdfText] = {}
    for row in frame[_CACHE_COLUMNS].itertuples(index=False):
        key: CacheKey = (str(row.source_file), int(row.mtime_ns), int(row.file_size))
        cache[key] = ExtractedPdfText(
            first_page_text=str(row.first_page_text),
            full_text=str(row.full_text),
        )
    return cache, []


def upsert_text_cache(path: Path, rows: list[CachedExtractionRow]) -> tuple[int, list[str]]:
    """Upsert extraction rows into cache parquet and return rows written."""
    if not rows:
        return 0, []

    incoming = pd.DataFrame(
        [
            {
                "source_file": row.source_file,
                "mtime_ns": row.mtime_ns,
                "file_size": row.file_size,
                "first_page_text": row.first_page_text,
                "full_text": row.full_text,
                "cached_at": datetime.now(UTC).isoformat(),
            }
            for row in rows
        ]
    )[_CACHE_COLUMNS]

    if path.exists():
        try:
            existing = pd.read_parquet(path)
        except Exception as exc:
            return 0, [f"Ingest text cache read failed for {path}: {exc}"]
        for column in _CACHE_COLUMNS:
            if column not in existing.columns:
                existing[column] = None
        existing = existing[_CACHE_COLUMNS]
    else:
        existing = pd.DataFrame(columns=_CACHE_COLUMNS)

    combined = pd.concat([existing, incoming], ignore_index=True)
    dedup = combined.drop_duplicates(
        subset=["source_file", "mtime_ns", "file_size"],
        keep="last",
    ).reset_index(drop=True)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp.parquet")
        dedup.to_parquet(temp_path, index=False)
        temp_path.replace(path)
    except Exception as exc:
        return 0, [f"Ingest text cache write failed for {path}: {exc}"]

    return len(incoming), []

"""Filesystem scanning utilities."""

from __future__ import annotations

from pathlib import Path


def discover_statement_pdfs(folder: Path) -> list[Path]:
    """Return sorted PDF files discovered recursively in ``folder``."""
    return sorted(
        path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"
    )


def discover_csv_files(path: Path) -> list[Path]:
    """Return sorted CSV files from ``path`` (file or directory)."""
    if path.is_file():
        return [path] if path.suffix.lower() == ".csv" else []

    return sorted(
        entry
        for entry in path.rglob("*")
        if entry.is_file()
        and entry.suffix.lower() == ".csv"
        and not entry.name.startswith(".~lock")
    )

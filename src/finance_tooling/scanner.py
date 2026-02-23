"""Filesystem scanning utilities."""

from __future__ import annotations

from pathlib import Path


def discover_statement_pdfs(folder: Path) -> list[Path]:
    """Return sorted PDF files discovered recursively in ``folder``."""
    return sorted(
        path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"
    )

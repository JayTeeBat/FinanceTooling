from __future__ import annotations

import json
from pathlib import Path

from finance_tooling.core.source_inventory import (
    build_source_inventory,
    duplicate_groups,
    load_source_inventory,
    representative_source_files,
    write_source_inventory,
)


def test_build_source_inventory_groups_duplicate_raw_files(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    duplicate = tmp_path / "b.pdf"
    other = tmp_path / "c.pdf"
    first.write_bytes(b"same-pdf-content")
    duplicate.write_bytes(b"same-pdf-content")
    other.write_bytes(b"different")

    snapshot = build_source_inventory([first, duplicate, other])

    assert snapshot.raw_file_count == 3
    assert snapshot.unique_document_count == 2
    assert snapshot.ignored_duplicate_file_count == 1
    assert representative_source_files(snapshot) == [first.resolve(), other.resolve()]
    groups = duplicate_groups(snapshot)
    assert groups[0]["representative_source_file"] == str(first.resolve())
    assert groups[0]["duplicate_source_files"] == [str(duplicate.resolve())]


def test_source_inventory_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(b"content")
    snapshot = build_source_inventory([source])
    destination = tmp_path / "source_inventory.json"

    write_source_inventory(destination, snapshot)

    loaded = load_source_inventory(destination)
    assert loaded is not None
    assert loaded.raw_file_count == 1
    assert loaded.entries[0].source_document_id == snapshot.entries[0].source_document_id
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["unique_document_count"] == 1

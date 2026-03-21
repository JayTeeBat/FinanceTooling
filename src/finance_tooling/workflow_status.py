"""Pipeline healthcheck and status snapshot generation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import pandas as pd

from finance_tooling.config import Settings
from finance_tooling.scanner import discover_statement_pdfs
from finance_tooling.source_inventory import (
    SourceInventorySnapshot,
    build_source_inventory,
    duplicate_groups,
    load_source_inventory,
    write_source_inventory,
)

PIPELINE_STATE_FILENAME = "pipeline_state.json"
SOURCE_INVENTORY_FILENAME = "source_inventory.json"


class PipelineFinding(TypedDict):
    """Single healthcheck finding."""

    severity: str
    code: str
    message: str


class RawSourceState(TypedDict):
    """Raw source state section of the pipeline status payload."""

    raw_file_count: int
    unique_document_count: int
    ignored_duplicate_file_count: int
    duplicate_groups: list[dict[str, object]]
    matches_last_ingest_inventory: bool


class StagedState(TypedDict):
    """Staged artifact state section of the pipeline status payload."""

    exists: bool
    path: str
    mtime: str | None


class MasterState(TypedDict):
    """Canonical master parquet state section."""

    exists: bool
    total_rows: int
    booking_date_min: str | None
    booking_date_max: str | None


class TransformedState(TypedDict):
    """Transformed output state section of the pipeline status payload."""

    summary_exists: bool
    summary_generated_at: object | None
    master: MasterState
    summary_path: str
    completeness_path: str


class PipelineStatePayload(TypedDict):
    """Machine-readable pipeline status payload."""

    generated_at: str
    status: str
    processed_path: str
    raw_source_state: RawSourceState
    staged_state: StagedState
    transformed_state: TransformedState
    findings: list[PipelineFinding]


def _inventory_representatives(
    snapshot: SourceInventorySnapshot,
) -> dict[str, str]:
    representatives: dict[str, str] = {}
    for entry in snapshot.entries:
        if entry.is_representative:
            representatives[entry.source_document_id] = entry.source_file
    return representatives


def _load_summary(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _master_snapshot(path: Path) -> MasterState:
    if not path.exists():
        return {
            "exists": False,
            "total_rows": 0,
            "booking_date_min": None,
            "booking_date_max": None,
        }
    frame = pd.read_parquet(path)
    if frame.empty or "booking_date" not in frame.columns:
        return {
            "exists": True,
            "total_rows": len(frame),
            "booking_date_min": None,
            "booking_date_max": None,
        }
    booking_dates = frame["booking_date"].dropna()
    return {
        "exists": True,
        "total_rows": len(frame),
        "booking_date_min": str(booking_dates.min()) if not booking_dates.empty else None,
        "booking_date_max": str(booking_dates.max()) if not booking_dates.empty else None,
    }


def build_pipeline_state(settings: Settings) -> tuple[PipelineStatePayload, Path]:
    """Build and persist a machine-readable pipeline status snapshot."""
    processed_dir = settings.summary_json_path.parent
    pipeline_state_path = processed_dir / PIPELINE_STATE_FILENAME
    stored_inventory_path = processed_dir / SOURCE_INVENTORY_FILENAME

    current_inventory = build_source_inventory(discover_statement_pdfs(settings.input_path))
    previous_inventory = load_source_inventory(stored_inventory_path)
    current_representatives = _inventory_representatives(current_inventory)
    previous_representatives = (
        _inventory_representatives(previous_inventory) if previous_inventory is not None else {}
    )

    findings: list[PipelineFinding] = []

    if current_inventory.ignored_duplicate_file_count > 0:
        findings.append(
            {
                "severity": "warning",
                "code": "duplicate_raw_sources",
                "message": (
                    "Duplicate raw source files detected; non-representative copies are ignored "
                    f"({current_inventory.ignored_duplicate_file_count} file(s))."
                ),
            }
        )

    if previous_inventory is None:
        findings.append(
            {
                "severity": "warning",
                "code": "source_inventory_missing",
                "message": "No prior source inventory snapshot found in processed outputs.",
            }
        )
    else:
        current_ids = set(current_representatives)
        previous_ids = set(previous_representatives)
        if current_ids != previous_ids:
            findings.append(
                {
                    "severity": "warning",
                    "code": "raw_source_set_changed",
                    "message": (
                        "Current raw source-document set differs from the last ingested source "
                        "inventory."
                    ),
                }
            )
        path_change_count = sum(
            1
            for document_id, source_file in current_representatives.items()
            if document_id in previous_representatives
            and previous_representatives[document_id] != source_file
        )
        if path_change_count > 0:
            findings.append(
                {
                    "severity": "warning",
                    "code": "source_path_changed",
                    "message": (
                        "Known source documents are now present under different paths "
                        f"({path_change_count} document(s))."
                    ),
                }
            )

    staged_exists = settings.staged_transactions_path.exists()
    summary_exists = settings.summary_json_path.exists()
    if staged_exists and (
        not summary_exists
        or settings.staged_transactions_path.stat().st_mtime
        > settings.summary_json_path.stat().st_mtime
    ):
        findings.append(
            {
                "severity": "warning",
                "code": "staged_newer_than_transform",
                "message": "Staged transactions are newer than transformed outputs.",
            }
        )

    for artifact_name, artifact_path in (
        ("master_parquet", settings.master_parquet_path),
        ("run_summary", settings.summary_json_path),
        ("completeness_report", settings.completeness_json_path),
    ):
        if not artifact_path.exists():
            findings.append(
                {
                    "severity": "warning",
                    "code": f"missing_{artifact_name}",
                    "message": f"Processed artifact missing: {artifact_path.name}",
                }
            )

    status = "pass"
    if findings:
        status = "warn"

    summary_payload = _load_summary(settings.summary_json_path)
    master_state = _master_snapshot(settings.master_parquet_path)

    payload: PipelineStatePayload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "processed_path": str(processed_dir),
        "raw_source_state": {
            "raw_file_count": current_inventory.raw_file_count,
            "unique_document_count": current_inventory.unique_document_count,
            "ignored_duplicate_file_count": current_inventory.ignored_duplicate_file_count,
            "duplicate_groups": duplicate_groups(current_inventory),
            "matches_last_ingest_inventory": previous_inventory is not None
            and set(current_representatives) == set(previous_representatives),
        },
        "staged_state": {
            "exists": staged_exists,
            "path": str(settings.staged_transactions_path),
            "mtime": (
                datetime.fromtimestamp(
                    settings.staged_transactions_path.stat().st_mtime,
                    tz=UTC,
                ).isoformat()
                if staged_exists
                else None
            ),
        },
        "transformed_state": {
            "summary_exists": summary_exists,
            "summary_generated_at": summary_payload.get("generated_at")
            if summary_payload is not None
            else None,
            "master": master_state,
            "summary_path": str(settings.summary_json_path),
            "completeness_path": str(settings.completeness_json_path),
        },
        "findings": findings,
    }
    pipeline_state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload, pipeline_state_path


def refresh_source_inventory(settings: Settings) -> Path:
    """Persist a fresh source inventory snapshot without running the pipeline."""
    inventory = build_source_inventory(discover_statement_pdfs(settings.input_path))
    path = settings.summary_json_path.parent / SOURCE_INVENTORY_FILENAME
    return write_source_inventory(path, inventory)

"""Pipeline healthcheck and status snapshot generation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import pandas as pd

from finance_tooling.config import Settings, state_root_path
from finance_tooling.scanner import discover_statement_pdfs
from finance_tooling.source_inventory import (
    SourceInventorySnapshot,
    build_source_inventory,
    duplicate_groups,
    load_source_inventory,
    write_source_inventory,
)
from finance_tooling.workflow.incremental_state import (
    build_incremental_selection_plan,
    compute_config_fingerprint,
    load_source_registry,
    load_staged_batch_manifest,
    resolve_staged_batch_manifest_path,
    source_registry_path,
)
from finance_tooling.workflow.staging import resolve_staged_transactions_path

PIPELINE_STATE_FILENAME = "workflow_pipeline_state.json"
SOURCE_INVENTORY_FILENAME = "workflow_source_inventory.json"


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
    modified_committed_file_count: int
    missing_committed_file_count: int


class StagedState(TypedDict):
    """Staged artifact state section of the pipeline status payload."""

    exists: bool
    path: str
    mtime: str | None
    manifest_exists: bool
    manifest_path: str
    run_mode: str | None
    files_selected_for_processing: int


class CommittedState(TypedDict):
    """Committed registry state section."""

    exists: bool
    path: str
    committed_source_count: int
    last_run_mode: str | None
    last_full_refresh_at: str | None
    config_drift_since_last_full_refresh: bool


class DriftState(TypedDict):
    """Current stale-state and full-refresh risk summary."""

    dataset_stale: bool
    stale_reasons: list[str]
    full_refresh_risk: str


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
    committed_state: CommittedState
    drift_state: DriftState
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
    processed_dir = settings.processed_path
    pipeline_state_path = state_root_path(settings) / PIPELINE_STATE_FILENAME
    stored_inventory_path = state_root_path(settings) / SOURCE_INVENTORY_FILENAME

    current_inventory = build_source_inventory(discover_statement_pdfs(settings.input_path))
    registry = load_source_registry(source_registry_path(settings))
    manifest = load_staged_batch_manifest(resolve_staged_batch_manifest_path(settings))
    manifest_inventory = manifest.source_inventory if manifest is not None else None
    if (
        manifest_inventory is None
        and manifest is not None
        and manifest.source_inventory_path is not None
    ):
        manifest_inventory = load_source_inventory(Path(manifest.source_inventory_path))
    previous_inventory = manifest_inventory or load_source_inventory(stored_inventory_path)
    selection_plan = build_incremental_selection_plan(
        settings=settings,
        run_mode="incremental",
        current_inventory=current_inventory,
        registry=registry,
    )
    config_fingerprint = compute_config_fingerprint(settings)
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

    if selection_plan.modified_existing_entries:
        findings.append(
            {
                "severity": "warning",
                "code": "raw_source_modified_since_commit",
                "message": (
                    "Previously committed source files changed on disk; default incremental "
                    "runs will skip them until a full refresh."
                ),
            }
        )
    if selection_plan.missing_committed_entries:
        findings.append(
            {
                "severity": "warning",
                "code": "raw_source_missing_since_commit",
                "message": (
                    "Previously committed source files are missing from the current raw corpus; "
                    "canonical rows are retained until a full refresh."
                ),
            }
        )
    if (
        registry is not None
        and registry.last_full_refresh_config_fingerprint is not None
        and registry.last_full_refresh_config_fingerprint != config_fingerprint
    ):
        findings.append(
            {
                "severity": "warning",
                "code": "config_changed_since_last_full_refresh",
                "message": (
                    "Categorization or project config changed since the last full refresh; "
                    "historical rows may be stale."
                ),
            }
        )

    staged_transactions_path = resolve_staged_transactions_path(settings)
    staged_exists = staged_transactions_path.exists()
    summary_exists = settings.summary_json_path.exists()
    if staged_exists and (
        not summary_exists
        or staged_transactions_path.stat().st_mtime
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
    if (
        selection_plan.modified_existing_entries
        or selection_plan.missing_committed_entries
        or selection_plan.dataset_stale
    ):
        full_refresh_risk = "high"
    elif current_inventory.ignored_duplicate_file_count > 0 or manifest is not None:
        full_refresh_risk = "medium"
    else:
        full_refresh_risk = "low"

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
            "modified_committed_file_count": len(selection_plan.modified_existing_entries),
            "missing_committed_file_count": len(selection_plan.missing_committed_entries),
        },
        "staged_state": {
            "exists": staged_exists,
            "path": str(staged_transactions_path),
            "mtime": (
                datetime.fromtimestamp(staged_transactions_path.stat().st_mtime, tz=UTC).isoformat()
                if staged_exists
                else None
            ),
            "manifest_exists": manifest is not None,
            "manifest_path": str(resolve_staged_batch_manifest_path(settings)),
            "run_mode": manifest.run_mode if manifest is not None else None,
            "files_selected_for_processing": (
                manifest.files_selected_for_processing if manifest is not None else 0
            ),
        },
        "committed_state": {
            "exists": registry is not None,
            "path": str(source_registry_path(settings)),
            "committed_source_count": len(registry.entries) if registry is not None else 0,
            "last_run_mode": registry.last_run_mode if registry is not None else None,
            "last_full_refresh_at": (
                registry.last_full_refresh_at if registry is not None else None
            ),
            "config_drift_since_last_full_refresh": (
                registry is not None
                and registry.last_full_refresh_config_fingerprint is not None
                and registry.last_full_refresh_config_fingerprint != config_fingerprint
            ),
        },
        "drift_state": {
            "dataset_stale": selection_plan.dataset_stale,
            "stale_reasons": list(selection_plan.stale_reasons),
            "full_refresh_risk": full_refresh_risk,
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

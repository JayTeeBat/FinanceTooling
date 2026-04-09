"""Incremental workflow state, selection, and full-refresh safeguards."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from finance_tooling.core.backup import backup_root_from_processed_dir
from finance_tooling.core.config import (
    LEGACY_STAGED_TRANSACTIONS_FILENAME,
    TRANSFORM_SOURCE_REGISTRY_FILENAME,
    Settings,
    ingest_state_path,
    state_root_path,
)
from finance_tooling.core.scanner import discover_statement_pdfs
from finance_tooling.core.source_inventory import (
    SourceInventoryEntry,
    SourceInventorySnapshot,
    build_source_inventory,
    duplicate_groups,
    load_source_inventory,
    load_source_inventory_payload,
)
from finance_tooling.parsers.base import StatementValidation

RunMode = Literal["incremental", "full_refresh"]

LEGACY_SOURCE_REGISTRY_FILENAME = "source_registry.json"
INGEST_STAGED_BATCH_MANIFEST_FILENAME = "ingest_staged_batch_manifest.json"
LEGACY_STAGED_BATCH_MANIFEST_FILENAME = "staged_batch_manifest.json"


@dataclass(frozen=True)
class CommittedSourceEntry:
    """Committed representative source document metadata."""

    source_document_id: str
    representative_source_file: str
    file_size: int
    mtime_ns: int
    committed_at: str
    parser_status: str
    parsed_transaction_count: int
    validation: dict[str, object] | None


@dataclass(frozen=True)
class SourceRegistrySnapshot:
    """Committed source registry snapshot."""

    generated_at: str
    last_run_mode: RunMode
    last_full_refresh_at: str | None
    last_full_refresh_config_fingerprint: str | None
    entries: tuple[CommittedSourceEntry, ...]


@dataclass(frozen=True)
class StagedBatchManifest:
    """Metadata for the currently staged batch."""

    generated_at: str
    run_mode: RunMode
    source_inventory: SourceInventorySnapshot | None
    source_inventory_path: str | None
    selected_source_files: tuple[str, ...]
    selected_source_document_ids: tuple[str, ...]
    files_selected_for_processing: int
    files_skipped_already_committed: int
    files_skipped_modified_existing: int
    files_missing_since_last_commit: int
    dataset_stale: bool
    stale_reasons: tuple[str, ...]
    config_fingerprint: str
    context: dict[str, object]


@dataclass(frozen=True)
class IncrementalSelectionPlan:
    """Selected source files and stale-state view for an ingest run."""

    run_mode: RunMode
    current_inventory: SourceInventorySnapshot
    selected_entries: tuple[SourceInventoryEntry, ...]
    files_skipped_already_committed: int
    modified_existing_entries: tuple[SourceInventoryEntry, ...]
    missing_committed_entries: tuple[CommittedSourceEntry, ...]
    dataset_stale: bool
    stale_reasons: tuple[str, ...]
    config_fingerprint: str

    @property
    def selected_source_files(self) -> list[Path]:
        return [Path(entry.source_file) for entry in self.selected_entries]

    @property
    def all_representative_source_files(self) -> list[Path]:
        return [
            Path(entry.source_file)
            for entry in self.current_inventory.entries
            if entry.is_representative
        ]


@dataclass(frozen=True)
class FullRefreshPreflight:
    """Risk and confirmation payload for a full refresh."""

    command: str
    run_mode: RunMode
    confirmation_token: str
    full_refresh_risk: str
    raw_file_count: int
    unique_document_count: int
    committed_source_count: int
    modified_committed_count: int
    missing_committed_count: int
    config_drift: bool
    estimated_pruned_row_count: int
    estimated_reprocessed_row_count: int
    processed_backup_root: Path
    config_backup_root: Path
    stale_reasons: tuple[str, ...]


def source_registry_path(settings: Settings) -> Path:
    preferred = state_root_path(settings) / TRANSFORM_SOURCE_REGISTRY_FILENAME
    if preferred.exists():
        return preferred
    for legacy in (
        settings.processed_path / LEGACY_SOURCE_REGISTRY_FILENAME,
        settings.summary_json_path.parent / LEGACY_SOURCE_REGISTRY_FILENAME,
    ):
        if legacy.exists():
            return legacy
    return preferred


def staged_batch_manifest_path(settings: Settings) -> Path:
    return ingest_state_path(settings) / INGEST_STAGED_BATCH_MANIFEST_FILENAME


def resolve_staged_transactions_path(settings: Settings) -> Path:
    """Resolve the staged transactions path, falling back to the legacy root filename."""
    preferred = settings.staged_transactions_path
    if preferred.exists():
        return preferred
    for legacy in (
        settings.processed_path / LEGACY_STAGED_TRANSACTIONS_FILENAME,
        settings.summary_json_path.parent / LEGACY_STAGED_TRANSACTIONS_FILENAME,
    ):
        if legacy.exists():
            return legacy
    return preferred


def resolve_staged_batch_manifest_path(settings: Settings) -> Path:
    """Resolve the staged batch manifest path, falling back to the legacy root filename."""
    preferred = staged_batch_manifest_path(settings)
    if preferred.exists():
        return preferred
    for legacy in (
        settings.processed_path / LEGACY_STAGED_BATCH_MANIFEST_FILENAME,
        settings.summary_json_path.parent / LEGACY_STAGED_BATCH_MANIFEST_FILENAME,
    ):
        if legacy.exists():
            return legacy
    return preferred


def _serialize_validation(validation: StatementValidation | None) -> dict[str, object] | None:
    if validation is None:
        return None
    return {
        "source_file": str(validation.source_file),
        "bank": validation.bank,
        "parser": validation.parser,
        "statement_type": validation.statement_type,
        "opening_balance": (
            str(validation.opening_balance) if validation.opening_balance is not None else None
        ),
        "closing_balance": (
            str(validation.closing_balance) if validation.closing_balance is not None else None
        ),
        "transaction_sum": (
            str(validation.transaction_sum) if validation.transaction_sum is not None else None
        ),
        "expected_closing_balance": (
            str(validation.expected_closing_balance)
            if validation.expected_closing_balance is not None
            else None
        ),
        "difference": str(validation.difference) if validation.difference is not None else None,
        "status": validation.status,
        "reason": validation.reason,
        "severity": validation.severity,
    }


def _deserialize_validation(payload: dict[str, object] | None) -> StatementValidation | None:
    if payload is None:
        return None

    def _decimal_or_none(value: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    return StatementValidation(
        source_file=Path(str(payload["source_file"])),
        bank=str(payload["bank"]),
        parser=str(payload["parser"]),
        statement_type=str(payload["statement_type"]),
        opening_balance=_decimal_or_none(payload["opening_balance"]),
        closing_balance=_decimal_or_none(payload["closing_balance"]),
        transaction_sum=Decimal(str(payload["transaction_sum"])),
        expected_closing_balance=_decimal_or_none(payload["expected_closing_balance"]),
        difference=_decimal_or_none(payload["difference"]),
        status=str(payload["status"]),
        reason=str(payload["reason"]) if payload["reason"] is not None else None,
        severity=str(payload["severity"]),
    )


def _compute_paths_fingerprint(paths: tuple[Path, ...]) -> str:
    """Compute a fingerprint over an ordered set of paths."""
    return _compute_labeled_paths_fingerprint(tuple((str(path), path) for path in paths))


def _compute_labeled_paths_fingerprint(items: tuple[tuple[str, Path], ...]) -> str:
    """Compute a fingerprint over ordered labels plus file contents."""
    digest = hashlib.sha256()
    for label, path in items:
        digest.update(label.encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def compute_rule_config_fingerprint(settings: Settings) -> str:
    """Fingerprint rule files that determine whether a full refresh is needed."""
    return _compute_paths_fingerprint(
        (
            settings.category_rules_path,
            settings.project_rules_path,
        )
    )


def compute_transform_input_fingerprint(settings: Settings) -> str:
    """Fingerprint transform-affecting config inputs for output cache freshness."""
    return _compute_paths_fingerprint(
        (
            settings.category_rules_path,
            settings.project_rules_path,
            settings.account_rules_path,
            settings.project_overrides_path,
            settings.transaction_overrides_path,
        )
    )


def compute_config_fingerprint(settings: Settings) -> str:
    """Backward-compatible alias for transform input fingerprinting."""
    return compute_transform_input_fingerprint(settings)


def _last_full_refresh_rule_fingerprint_from_backup(
    settings: Settings,
    *,
    last_full_refresh_at: str | None,
) -> str | None:
    """Load the last full-refresh rule fingerprint from the saved config backup when present."""
    if last_full_refresh_at is None:
        return None
    try:
        target_timestamp = datetime.fromisoformat(last_full_refresh_at).astimezone(UTC)
    except ValueError:
        return None
    backup_root = backup_root_from_processed_dir(settings.processed_path)
    candidate_dirs: list[tuple[datetime, Path]] = []
    if backup_root.exists():
        for child in backup_root.iterdir():
            if not child.is_dir() or child.name == "legacy":
                continue
            manifest_path = child / "manifest.json"
            created_at: datetime | None = None
            if manifest_path.exists():
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                    raw_created_at = payload.get("created_at")
                    if isinstance(raw_created_at, str):
                        created_at = datetime.fromisoformat(raw_created_at).astimezone(UTC)
                except (OSError, ValueError, json.JSONDecodeError):
                    created_at = None
            if created_at is None:
                continue
            if created_at is not None and created_at <= target_timestamp:
                candidate_dirs.append((created_at, child))

    if candidate_dirs:
        _created_at, backup_dir = max(candidate_dirs, key=lambda item: item[0])
    else:
        return None

    config_backup_dir = backup_dir / "config"
    category_rules_path = config_backup_dir / settings.category_rules_path.name
    project_rules_path = config_backup_dir / settings.project_rules_path.name
    if not category_rules_path.exists() and not project_rules_path.exists():
        return None
    return _compute_labeled_paths_fingerprint(
        (
            (str(settings.category_rules_path), category_rules_path),
            (str(settings.project_rules_path), project_rules_path),
        )
    )


def has_rule_config_drift_since_last_full_refresh(
    settings: Settings,
    registry: SourceRegistrySnapshot | None,
) -> bool:
    """Return whether category/project rules changed since the last full refresh.

    Supports registries written before the rule-only fingerprint split by falling
    back to the saved full-refresh config backup when available.
    """
    if (
        registry is None
        or registry.last_full_refresh_config_fingerprint is None
        or registry.last_full_refresh_at is None
    ):
        return False

    current_rule_fingerprint = compute_rule_config_fingerprint(settings)
    if registry.last_full_refresh_config_fingerprint == current_rule_fingerprint:
        return False

    backup_rule_fingerprint = _last_full_refresh_rule_fingerprint_from_backup(
        settings,
        last_full_refresh_at=registry.last_full_refresh_at,
    )
    if backup_rule_fingerprint is None:
        return True
    return backup_rule_fingerprint != current_rule_fingerprint


def load_source_registry(path: Path) -> SourceRegistrySnapshot | None:
    """Load committed source registry when available."""
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = tuple(
        CommittedSourceEntry(
            source_document_id=str(entry["source_document_id"]),
            representative_source_file=str(entry["representative_source_file"]),
            file_size=int(entry["file_size"]),
            mtime_ns=int(entry["mtime_ns"]),
            committed_at=str(entry["committed_at"]),
            parser_status=str(entry["parser_status"]),
            parsed_transaction_count=int(entry["parsed_transaction_count"]),
            validation=(
                dict(entry["validation"]) if isinstance(entry.get("validation"), dict) else None
            ),
        )
        for entry in payload.get("entries", [])
    )
    return SourceRegistrySnapshot(
        generated_at=str(payload.get("generated_at", "")),
        last_run_mode=str(payload.get("last_run_mode", "incremental")),  # type: ignore[arg-type]
        last_full_refresh_at=(
            str(payload["last_full_refresh_at"])
            if payload.get("last_full_refresh_at") is not None
            else None
        ),
        last_full_refresh_config_fingerprint=(
            str(payload["last_full_refresh_config_fingerprint"])
            if payload.get("last_full_refresh_config_fingerprint") is not None
            else None
        ),
        entries=entries,
    )


def write_source_registry(path: Path, snapshot: SourceRegistrySnapshot) -> Path:
    """Persist committed source registry to JSON."""
    payload = {
        "generated_at": snapshot.generated_at,
        "last_run_mode": snapshot.last_run_mode,
        "last_full_refresh_at": snapshot.last_full_refresh_at,
        "last_full_refresh_config_fingerprint": snapshot.last_full_refresh_config_fingerprint,
        "entries": [asdict(entry) for entry in snapshot.entries],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_staged_batch_manifest(path: Path) -> StagedBatchManifest | None:
    """Load staged batch manifest when available."""
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    source_inventory_payload = payload.get("source_inventory")
    source_inventory = None
    if isinstance(source_inventory_payload, dict):
        source_inventory = load_source_inventory_payload(source_inventory_payload)
    source_inventory_path = payload.get("source_inventory_path")
    if (
        source_inventory is None
        and isinstance(source_inventory_path, str)
        and source_inventory_path
    ):
        source_inventory = load_source_inventory(Path(source_inventory_path))
    return StagedBatchManifest(
        generated_at=str(payload["generated_at"]),
        run_mode=str(payload["run_mode"]),  # type: ignore[arg-type]
        source_inventory=source_inventory,
        source_inventory_path=(
            str(source_inventory_path) if isinstance(source_inventory_path, str) else None
        ),
        selected_source_files=tuple(str(item) for item in payload["selected_source_files"]),
        selected_source_document_ids=tuple(
            str(item) for item in payload["selected_source_document_ids"]
        ),
        files_selected_for_processing=int(payload["files_selected_for_processing"]),
        files_skipped_already_committed=int(payload["files_skipped_already_committed"]),
        files_skipped_modified_existing=int(payload["files_skipped_modified_existing"]),
        files_missing_since_last_commit=int(payload["files_missing_since_last_commit"]),
        dataset_stale=bool(payload["dataset_stale"]),
        stale_reasons=tuple(str(item) for item in payload["stale_reasons"]),
        config_fingerprint=str(payload["config_fingerprint"]),
        context=dict(payload.get("context", {})),
    )


def write_staged_batch_manifest(path: Path, manifest: StagedBatchManifest) -> Path:
    """Persist staged batch manifest to JSON."""
    payload = asdict(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def build_incremental_selection_plan(
    *,
    settings: Settings,
    run_mode: RunMode,
    current_inventory: SourceInventorySnapshot,
    registry: SourceRegistrySnapshot | None,
) -> IncrementalSelectionPlan:
    """Select source files for default incremental or full-refresh ingest."""
    config_fingerprint = compute_rule_config_fingerprint(settings)
    has_config_drift = has_rule_config_drift_since_last_full_refresh(settings, registry)
    representative_entries = tuple(
        entry for entry in current_inventory.entries if entry.is_representative
    )
    if run_mode == "full_refresh":
        stale_reasons: list[str] = []
        if has_config_drift:
            stale_reasons.append("config_changed_since_last_full_refresh")
        return IncrementalSelectionPlan(
            run_mode=run_mode,
            current_inventory=current_inventory,
            selected_entries=representative_entries,
            files_skipped_already_committed=0,
            modified_existing_entries=(),
            missing_committed_entries=(),
            dataset_stale=bool(stale_reasons),
            stale_reasons=tuple(stale_reasons),
            config_fingerprint=config_fingerprint,
        )

    if registry is None:
        return IncrementalSelectionPlan(
            run_mode=run_mode,
            current_inventory=current_inventory,
            selected_entries=representative_entries,
            files_skipped_already_committed=0,
            modified_existing_entries=(),
            missing_committed_entries=(),
            dataset_stale=False,
            stale_reasons=(),
            config_fingerprint=config_fingerprint,
        )

    registry_by_id = {entry.source_document_id: entry for entry in registry.entries}
    selected_entries: list[SourceInventoryEntry] = []
    modified_existing_entries: list[SourceInventoryEntry] = []
    skipped_already_committed = 0

    for entry in representative_entries:
        committed = registry_by_id.get(entry.source_document_id)
        if committed is None:
            selected_entries.append(entry)
            continue
        if committed.file_size != entry.file_size or committed.mtime_ns != entry.mtime_ns:
            modified_existing_entries.append(entry)
            continue
        skipped_already_committed += 1

    current_document_ids = {entry.source_document_id for entry in representative_entries}
    missing_committed_entries = tuple(
        entry for entry in registry.entries if entry.source_document_id not in current_document_ids
    )

    stale_reasons: list[str] = []
    if modified_existing_entries:
        stale_reasons.append("raw_source_modified_since_commit")
    if missing_committed_entries:
        stale_reasons.append("raw_source_missing_since_commit")
    if has_config_drift:
        stale_reasons.append("config_changed_since_last_full_refresh")

    return IncrementalSelectionPlan(
        run_mode=run_mode,
        current_inventory=current_inventory,
        selected_entries=tuple(selected_entries),
        files_skipped_already_committed=skipped_already_committed,
        modified_existing_entries=tuple(modified_existing_entries),
        missing_committed_entries=missing_committed_entries,
        dataset_stale=bool(stale_reasons),
        stale_reasons=tuple(stale_reasons),
        config_fingerprint=config_fingerprint,
    )


def build_manifest_from_selection_plan(
    *,
    selection_plan: IncrementalSelectionPlan,
    source_inventory: SourceInventorySnapshot,
    source_inventory_path: Path | None = None,
) -> StagedBatchManifest:
    """Build a staged-batch manifest from the ingest selection plan."""
    return StagedBatchManifest(
        generated_at=datetime.now(UTC).isoformat(),
        run_mode=selection_plan.run_mode,
        source_inventory=source_inventory,
        source_inventory_path=str(source_inventory_path) if source_inventory_path else None,
        selected_source_files=tuple(str(path) for path in selection_plan.selected_source_files),
        selected_source_document_ids=tuple(
            entry.source_document_id for entry in selection_plan.selected_entries
        ),
        files_selected_for_processing=len(selection_plan.selected_entries),
        files_skipped_already_committed=selection_plan.files_skipped_already_committed,
        files_skipped_modified_existing=len(selection_plan.modified_existing_entries),
        files_missing_since_last_commit=len(selection_plan.missing_committed_entries),
        dataset_stale=selection_plan.dataset_stale,
        stale_reasons=selection_plan.stale_reasons,
        config_fingerprint=selection_plan.config_fingerprint,
        context={},
    )


def update_source_registry(
    *,
    existing: SourceRegistrySnapshot | None,
    selection_plan: IncrementalSelectionPlan,
    processed_source_files: list[Path],
    validations: list[StatementValidation],
    transactions: list[Any],
) -> SourceRegistrySnapshot:
    """Build the next committed source registry after a successful transform."""
    validation_by_file = {str(validation.source_file): validation for validation in validations}
    parsed_count_by_file: dict[str, int] = {}
    for transaction in transactions:
        parsed_count_by_file[str(transaction.source_file)] = (
            parsed_count_by_file.get(str(transaction.source_file), 0) + 1
        )

    processed_file_set = {str(path) for path in processed_source_files}
    committed_at = datetime.now(UTC).isoformat()

    if selection_plan.run_mode == "full_refresh" or existing is None:
        base_entries: dict[str, CommittedSourceEntry] = {}
    else:
        base_entries = {entry.source_document_id: entry for entry in existing.entries}

    for source_file in processed_file_set:
        matching_entry = next(
            (
                entry
                for entry in selection_plan.selected_entries
                if entry.source_file == source_file
            ),
            None,
        )
        if matching_entry is None:
            continue
        validation = validation_by_file.get(source_file)
        base_entries[matching_entry.source_document_id] = CommittedSourceEntry(
            source_document_id=matching_entry.source_document_id,
            representative_source_file=matching_entry.source_file,
            file_size=matching_entry.file_size,
            mtime_ns=matching_entry.mtime_ns,
            committed_at=committed_at,
            parser_status="processed",
            parsed_transaction_count=parsed_count_by_file.get(source_file, 0),
            validation=_serialize_validation(validation),
        )

    if selection_plan.run_mode == "full_refresh":
        entries = tuple(sorted(base_entries.values(), key=lambda entry: entry.source_document_id))
        last_full_refresh_at = committed_at
        last_full_refresh_config_fingerprint = selection_plan.config_fingerprint
    else:
        entries = tuple(sorted(base_entries.values(), key=lambda entry: entry.source_document_id))
        last_full_refresh_at = existing.last_full_refresh_at if existing is not None else None
        last_full_refresh_config_fingerprint = (
            existing.last_full_refresh_config_fingerprint if existing is not None else None
        )
        committed_document_ids = {entry.source_document_id for entry in entries}
        current_document_ids = {
            entry.source_document_id
            for entry in selection_plan.current_inventory.entries
            if entry.is_representative
        }
        if (
            last_full_refresh_config_fingerprint is None
            and committed_document_ids == current_document_ids
            and not selection_plan.modified_existing_entries
            and not selection_plan.missing_committed_entries
        ):
            last_full_refresh_at = committed_at
            last_full_refresh_config_fingerprint = selection_plan.config_fingerprint

    return SourceRegistrySnapshot(
        generated_at=committed_at,
        last_run_mode=selection_plan.run_mode,
        last_full_refresh_at=last_full_refresh_at,
        last_full_refresh_config_fingerprint=last_full_refresh_config_fingerprint,
        entries=entries,
    )


def committed_validations_for_current_inventory(
    *,
    registry: SourceRegistrySnapshot | None,
    current_inventory: SourceInventorySnapshot,
) -> list[StatementValidation]:
    """Return committed validations for the currently discovered representative files."""
    if registry is None:
        return []
    current_ids = {
        entry.source_document_id for entry in current_inventory.entries if entry.is_representative
    }
    validations: list[StatementValidation] = []
    for entry in registry.entries:
        if entry.source_document_id not in current_ids:
            continue
        validation = _deserialize_validation(entry.validation)
        if validation is not None:
            validations.append(validation)
    return validations


def build_full_refresh_preflight(
    *,
    settings: Settings,
    command: str,
) -> FullRefreshPreflight:
    """Build a dry-run impact summary and confirmation token for full refresh."""
    current_inventory = build_source_inventory(discover_statement_pdfs(settings.input_path))
    registry = load_source_registry(source_registry_path(settings))
    selection_plan = build_incremental_selection_plan(
        settings=settings,
        run_mode="full_refresh",
        current_inventory=current_inventory,
        registry=registry,
    )
    committed_count = len(registry.entries) if registry is not None else 0
    modified_count = 0
    missing_count = 0
    stale_reasons = list(selection_plan.stale_reasons)
    if registry is not None:
        registry_by_id = {entry.source_document_id: entry for entry in registry.entries}
        for entry in selection_plan.current_inventory.entries:
            if not entry.is_representative:
                continue
            committed = registry_by_id.get(entry.source_document_id)
            if committed is None:
                continue
            if committed.file_size != entry.file_size or committed.mtime_ns != entry.mtime_ns:
                modified_count += 1
        current_ids = {
            entry.source_document_id
            for entry in selection_plan.current_inventory.entries
            if entry.is_representative
        }
        missing_count = sum(
            1 for entry in registry.entries if entry.source_document_id not in current_ids
        )
    estimated_pruned_row_count = 0
    estimated_reprocessed_row_count = 0
    if settings.master_parquet_path.exists():
        frame = pd.read_parquet(settings.master_parquet_path)
        estimated_reprocessed_row_count = len(frame)
        if registry is not None and missing_count > 0 and "source_document_id" in frame.columns:
            current_ids = {
                entry.source_document_id
                for entry in selection_plan.current_inventory.entries
                if entry.is_representative
            }
            estimated_pruned_row_count = int((~frame["source_document_id"].isin(current_ids)).sum())
    if missing_count > 0 or modified_count > 0 or selection_plan.dataset_stale:
        risk = "high"
    else:
        risk = "medium"
    token_payload = {
        "command": command,
        "raw_inventory": {
            "raw_file_count": current_inventory.raw_file_count,
            "unique_document_count": current_inventory.unique_document_count,
            "duplicate_groups": duplicate_groups(current_inventory),
        },
        "registry_count": committed_count,
        "modified_count": modified_count,
        "missing_count": missing_count,
        "config_fingerprint": selection_plan.config_fingerprint,
    }
    confirmation_token = hashlib.sha256(
        json.dumps(token_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    return FullRefreshPreflight(
        command=command,
        run_mode="full_refresh",
        confirmation_token=confirmation_token,
        full_refresh_risk=risk,
        raw_file_count=current_inventory.raw_file_count,
        unique_document_count=current_inventory.unique_document_count,
        committed_source_count=committed_count,
        modified_committed_count=modified_count,
        missing_committed_count=missing_count,
        config_drift=(
            registry is not None
            and registry.last_full_refresh_config_fingerprint is not None
            and registry.last_full_refresh_config_fingerprint != selection_plan.config_fingerprint
        ),
        estimated_pruned_row_count=estimated_pruned_row_count,
        estimated_reprocessed_row_count=estimated_reprocessed_row_count,
        processed_backup_root=backup_root_from_processed_dir(settings.processed_path),
        config_backup_root=backup_root_from_processed_dir(settings.processed_path),
        stale_reasons=tuple(stale_reasons),
    )

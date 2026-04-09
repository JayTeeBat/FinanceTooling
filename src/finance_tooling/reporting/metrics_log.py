"""Commit-to-commit metrics log helpers."""

from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class MetricsSnapshot:
    """Compact percentage-oriented performance snapshot."""

    generated_at: str
    commit: str
    branch: str
    files_scanned: int
    files_failed: int
    parsing_success_pct: float
    completeness_coverage_pct: float
    reconciliation_pass_pct: float | None
    categorized_pct: float
    uncategorized_pct: float
    categorized_amount_eur_abs: float
    uncategorized_amount_eur_abs: float
    categorized_amount_eur_abs_pct: float
    uncategorized_amount_eur_abs_pct: float


@dataclass(frozen=True)
class BankMetricsSnapshot:
    """Per-bank categorization snapshot for commit-level trend tracking."""

    generated_at: str
    commit: str
    branch: str
    bank: str
    transactions_count: int
    categorized_count: int
    uncategorized_count: int
    categorized_pct: float
    uncategorized_pct: float
    categorized_amount_eur_abs: float
    uncategorized_amount_eur_abs: float
    categorized_amount_eur_abs_pct: float
    uncategorized_amount_eur_abs_pct: float


_LOG_COLUMNS: tuple[str, ...] = (
    "generated_at",
    "commit",
    "branch",
    "files_scanned",
    "files_failed",
    "parsing_success_pct",
    "completeness_coverage_pct",
    "reconciliation_pass_pct",
    "categorized_pct",
    "uncategorized_pct",
    "categorized_amount_eur_abs",
    "uncategorized_amount_eur_abs",
    "categorized_amount_eur_abs_pct",
    "uncategorized_amount_eur_abs_pct",
)

_BANK_LOG_COLUMNS: tuple[str, ...] = (
    "generated_at",
    "commit",
    "branch",
    "bank",
    "transactions_count",
    "categorized_count",
    "uncategorized_count",
    "categorized_pct",
    "uncategorized_pct",
    "categorized_amount_eur_abs",
    "uncategorized_amount_eur_abs",
    "categorized_amount_eur_abs_pct",
    "uncategorized_amount_eur_abs_pct",
)


def _git_value(args: list[str], *, default: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
        value = completed.stdout.strip()
        return value or default
    except Exception:
        return default


def _to_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _to_float(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


def _load_completeness_payload(summary_path: Path, payload: dict[str, object]) -> dict[str, object]:
    completeness_path_raw = payload.get("completeness_report_path")
    candidate = (
        Path(completeness_path_raw)
        if isinstance(completeness_path_raw, str) and completeness_path_raw
        else summary_path.parent.parent / "state" / "transform_completeness_report.json"
    )
    try:
        completeness_payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return completeness_payload if isinstance(completeness_payload, dict) else {}


def build_snapshot(
    summary_path: Path, *, commit: str | None, branch: str | None
) -> MetricsSnapshot:
    """Build a metrics snapshot from a workflow run summary."""
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    completeness_payload = _load_completeness_payload(summary_path, payload)

    files_scanned = _to_int(payload.get("files_scanned"))
    files_failed = _to_int(payload.get("files_failed"))
    categorized_count = _to_int(payload.get("categorized_count"))
    uncategorized_count = _to_int(payload.get("uncategorized_count"))
    transactions_parsed = _to_int(payload.get("transactions_parsed"))
    categorized_amount_eur_abs = _to_float(payload.get("categorized_amount_eur_abs"), default=0.0)
    uncategorized_amount_eur_abs = _to_float(
        payload.get("uncategorized_amount_eur_abs"), default=0.0
    )
    total_income_eur = _to_float(
        payload.get("total_income_eur", payload.get("total_amount_eur_abs")),
        default=0.0,
    )

    file_coverage_ratio = _to_float(
        completeness_payload.get("file_coverage_ratio", payload.get("file_coverage_ratio")),
        default=0.0,
    )
    reconciliation = completeness_payload.get("statement_reconciliation", {})
    if not isinstance(reconciliation, dict):
        reconciliation = {}
    reconciliation_pass_ratio_raw = reconciliation.get(
        "pass_ratio", payload.get("statement_reconciliation_pass_ratio")
    )
    reconciliation_pass_ratio = (
        None if reconciliation_pass_ratio_raw is None else _to_float(reconciliation_pass_ratio_raw)
    )

    resolved_commit = commit or _git_value(["rev-parse", "--short", "HEAD"], default="unknown")
    resolved_branch = branch or _git_value(["rev-parse", "--abbrev-ref", "HEAD"], default="unknown")
    generated_at = datetime.now(UTC).isoformat()

    return MetricsSnapshot(
        generated_at=generated_at,
        commit=resolved_commit,
        branch=resolved_branch,
        files_scanned=files_scanned,
        files_failed=files_failed,
        parsing_success_pct=round(_pct(files_scanned - files_failed, files_scanned), 4),
        completeness_coverage_pct=round(file_coverage_ratio * 100.0, 4),
        reconciliation_pass_pct=(
            round(reconciliation_pass_ratio * 100.0, 4)
            if reconciliation_pass_ratio is not None
            else None
        ),
        categorized_pct=round(_pct(categorized_count, transactions_parsed), 4),
        uncategorized_pct=round(_pct(uncategorized_count, transactions_parsed), 4),
        categorized_amount_eur_abs=round(categorized_amount_eur_abs, 4),
        uncategorized_amount_eur_abs=round(uncategorized_amount_eur_abs, 4),
        categorized_amount_eur_abs_pct=round(
            _pct(categorized_amount_eur_abs, total_income_eur),
            4,
        ),
        uncategorized_amount_eur_abs_pct=round(
            _pct(uncategorized_amount_eur_abs, total_income_eur), 4
        ),
    )


def upsert_snapshot(log_path: Path, snapshot: MetricsSnapshot) -> tuple[int, int]:
    """Upsert snapshot by commit and persist CSV log."""
    rows: list[dict[str, str]] = []
    if log_path.exists():
        with log_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [
                {column: str(row.get(column, "") or "") for column in _LOG_COLUMNS}
                for row in reader
            ]

    serialized: dict[str, str] = {
        "generated_at": snapshot.generated_at,
        "commit": snapshot.commit,
        "branch": snapshot.branch,
        "files_scanned": str(snapshot.files_scanned),
        "files_failed": str(snapshot.files_failed),
        "parsing_success_pct": f"{snapshot.parsing_success_pct:.4f}",
        "completeness_coverage_pct": f"{snapshot.completeness_coverage_pct:.4f}",
        "reconciliation_pass_pct": (
            ""
            if snapshot.reconciliation_pass_pct is None
            else f"{snapshot.reconciliation_pass_pct:.4f}"
        ),
        "categorized_pct": f"{snapshot.categorized_pct:.4f}",
        "uncategorized_pct": f"{snapshot.uncategorized_pct:.4f}",
        "categorized_amount_eur_abs": f"{snapshot.categorized_amount_eur_abs:.4f}",
        "uncategorized_amount_eur_abs": f"{snapshot.uncategorized_amount_eur_abs:.4f}",
        "categorized_amount_eur_abs_pct": f"{snapshot.categorized_amount_eur_abs_pct:.4f}",
        "uncategorized_amount_eur_abs_pct": f"{snapshot.uncategorized_amount_eur_abs_pct:.4f}",
    }

    replaced = 0
    for index, row in enumerate(rows):
        if row.get("commit") == snapshot.commit:
            rows[index] = serialized
            replaced = 1
            break
    if replaced == 0:
        rows.append(serialized)

    rows.sort(key=lambda row: row.get("generated_at", ""))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_LOG_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), replaced


def build_bank_snapshots(
    summary_path: Path, *, commit: str | None, branch: str | None
) -> list[BankMetricsSnapshot]:
    """Build per-bank categorization percentage snapshots from run summary payload."""
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    raw_metrics = payload.get("category_metrics_by_bank")
    if not isinstance(raw_metrics, list):
        return []

    resolved_commit = commit or _git_value(["rev-parse", "--short", "HEAD"], default="unknown")
    resolved_branch = branch or _git_value(["rev-parse", "--abbrev-ref", "HEAD"], default="unknown")
    generated_at = datetime.now(UTC).isoformat()

    snapshots: list[BankMetricsSnapshot] = []
    for raw_metric in raw_metrics:
        if not isinstance(raw_metric, dict):
            continue
        bank_name = str(raw_metric.get("bank", "")).strip()
        normalized_bank = bank_name if bank_name else "UNKNOWN"
        count = _to_int(raw_metric.get("transactions_count"))
        categorized_count = _to_int(raw_metric.get("categorized_count"))
        uncategorized_count = _to_int(raw_metric.get("uncategorized_count"))
        categorized_amount_eur_abs = _to_float(
            raw_metric.get("categorized_amount_eur_abs"),
            default=0.0,
        )
        uncategorized_amount_eur_abs = _to_float(
            raw_metric.get("uncategorized_amount_eur_abs"),
            default=0.0,
        )
        income_amount_eur = _to_float(raw_metric.get("income_amount_eur"), default=0.0)
        snapshots.append(
            BankMetricsSnapshot(
                generated_at=generated_at,
                commit=resolved_commit,
                branch=resolved_branch,
                bank=normalized_bank,
                transactions_count=count,
                categorized_count=categorized_count,
                uncategorized_count=uncategorized_count,
                categorized_pct=round(
                    _to_float(
                        raw_metric.get("categorized_pct"),
                        default=_pct(categorized_count, count),
                    ),
                    4,
                ),
                uncategorized_pct=round(
                    _to_float(
                        raw_metric.get("uncategorized_pct"),
                        default=_pct(uncategorized_count, count),
                    ),
                    4,
                ),
                categorized_amount_eur_abs=round(categorized_amount_eur_abs, 4),
                uncategorized_amount_eur_abs=round(uncategorized_amount_eur_abs, 4),
                categorized_amount_eur_abs_pct=round(
                    _to_float(
                        raw_metric.get("categorized_amount_eur_abs_ratio"),
                        default=_pct(categorized_amount_eur_abs, income_amount_eur),
                    ),
                    4,
                ),
                uncategorized_amount_eur_abs_pct=round(
                    _to_float(
                        raw_metric.get("uncategorized_amount_eur_abs_ratio"),
                        default=_pct(uncategorized_amount_eur_abs, income_amount_eur),
                    ),
                    4,
                ),
            )
        )
    snapshots.sort(key=lambda row: row.bank)
    return snapshots


def upsert_bank_snapshots(
    log_path: Path,
    snapshots: list[BankMetricsSnapshot],
) -> tuple[int, int]:
    """Upsert per-bank rows by commit, replacing any existing rows for that commit."""
    if not snapshots:
        if not log_path.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(_BANK_LOG_COLUMNS))
                writer.writeheader()
        return 0, 0

    rows: list[dict[str, str]] = []
    if log_path.exists():
        with log_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [
                {column: str(row.get(column, "") or "") for column in _BANK_LOG_COLUMNS}
                for row in reader
            ]

    commit = snapshots[0].commit
    existing_count = sum(1 for row in rows if row.get("commit") == commit)
    rows = [row for row in rows if row.get("commit") != commit]
    replacement_count = existing_count

    rows.extend(
        {
            "generated_at": snapshot.generated_at,
            "commit": snapshot.commit,
            "branch": snapshot.branch,
            "bank": snapshot.bank,
            "transactions_count": str(snapshot.transactions_count),
            "categorized_count": str(snapshot.categorized_count),
            "uncategorized_count": str(snapshot.uncategorized_count),
            "categorized_pct": f"{snapshot.categorized_pct:.4f}",
            "uncategorized_pct": f"{snapshot.uncategorized_pct:.4f}",
            "categorized_amount_eur_abs": f"{snapshot.categorized_amount_eur_abs:.4f}",
            "uncategorized_amount_eur_abs": f"{snapshot.uncategorized_amount_eur_abs:.4f}",
            "categorized_amount_eur_abs_pct": f"{snapshot.categorized_amount_eur_abs_pct:.4f}",
            "uncategorized_amount_eur_abs_pct": f"{snapshot.uncategorized_amount_eur_abs_pct:.4f}",
        }
        for snapshot in snapshots
    )
    rows.sort(key=lambda row: (row.get("generated_at", ""), row.get("bank", "")))

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_BANK_LOG_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    return len(snapshots), replacement_count

"""Period open/closed state helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

PeriodStatus = Literal["open", "closed"]

_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.json")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def validate_month(month: str) -> str:
    """Validate canonical month token `YYYY-MM`."""
    normalized = month.strip()
    if not _MONTH_PATTERN.match(normalized):
        raise ValueError(f"Invalid month format (expected YYYY-MM): {month}")
    return normalized


def validate_status(status: str) -> PeriodStatus:
    """Validate period status token."""
    normalized = status.strip().lower()
    if normalized not in {"open", "closed"}:
        raise ValueError(f"Invalid period status (expected open|closed): {status}")
    return normalized  # type: ignore[return-value]


def load_period_statuses(path: Path) -> dict[str, PeriodStatus]:
    """Load period-status map keyed by `YYYY-MM`."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    statuses: dict[str, PeriodStatus] = {}
    for month, status in raw.items():
        if not isinstance(month, str) or not isinstance(status, str):
            continue
        try:
            statuses[validate_month(month)] = validate_status(status)
        except ValueError:
            continue
    return statuses


def save_period_statuses(path: Path, statuses: dict[str, PeriodStatus]) -> None:
    """Persist period-status map keyed by `YYYY-MM`."""
    payload = {month: statuses[month] for month in sorted(statuses)}
    _atomic_write_json(path, payload)


def set_period_status(path: Path, month: str, status: str) -> dict[str, PeriodStatus]:
    """Set and persist one month status."""
    statuses = load_period_statuses(path)
    statuses[validate_month(month)] = validate_status(status)
    save_period_statuses(path, statuses)
    return statuses


def list_period_statuses(path: Path) -> list[tuple[str, PeriodStatus]]:
    """Return sorted `(month, status)` pairs."""
    statuses = load_period_statuses(path)
    return sorted(statuses.items())


def is_closed(statuses: dict[str, PeriodStatus], month: str | None) -> bool:
    """Return whether month is explicitly marked closed."""
    if month is None:
        return False
    return statuses.get(month) == "closed"

"""Restatement helpers and append-only logging."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from finance_tooling.workflow.periods import validate_month


@dataclass(frozen=True)
class RestatementRange:
    """Inclusive restatement month range."""

    from_month: str
    to_month: str
    months: tuple[str, ...]


def month_range(from_month: str, to_month: str) -> RestatementRange:
    """Build inclusive month range from `YYYY-MM` to `YYYY-MM`."""
    start = validate_month(from_month)
    end = validate_month(to_month)
    start_date = date.fromisoformat(f"{start}-01")
    end_date = date.fromisoformat(f"{end}-01")
    if start_date > end_date:
        raise ValueError(f"from-month must be <= to-month: {from_month} > {to_month}")

    months: list[str] = []
    current = start_date
    while current <= end_date:
        months.append(f"{current.year:04d}-{current.month:02d}")
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return RestatementRange(from_month=start, to_month=end, months=tuple(months))


def append_restatement_log(
    *,
    path: Path,
    run_id: str,
    month_range_value: RestatementRange,
    reason: str,
    dry_run: bool,
    rows_before: int,
    rows_after: int,
) -> None:
    """Append one restatement event to JSON Lines log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "from_month": month_range_value.from_month,
        "to_month": month_range_value.to_month,
        "reason": reason,
        "run_id": run_id,
        "dry_run": dry_run,
        "rows_before": rows_before,
        "rows_after": rows_after,
        "delta": rows_after - rows_before,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True))
        handle.write("\n")

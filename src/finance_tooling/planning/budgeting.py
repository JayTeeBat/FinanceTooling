"""Budget target loading and budget-vs-actual helpers for dashboard analytics."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pandas as pd
import yaml

_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
_BUDGET_STATUS_COLUMNS = (
    "month",
    "category",
    "project",
    "budget_amount",
    "actual_amount",
    "variance",
    "status",
    "utilization_pct",
)


@dataclass(frozen=True)
class BudgetTarget:
    """Monthly budget target for one category and optional project scope."""

    month: str
    category: str
    project: str | None
    amount: float


@dataclass(frozen=True)
class BudgetConfig:
    """Loaded budget configuration."""

    currency: str
    targets: tuple[BudgetTarget, ...]


def _default_budget_config() -> BudgetConfig:
    return BudgetConfig(currency="EUR", targets=())


def _load_payload(path: Path) -> object:
    content = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(content)
    if suffix == ".json":
        return json.loads(content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return yaml.safe_load(content)


def _parse_month(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("budget target month must be a string")
    month = value.strip()
    if not _MONTH_PATTERN.match(month):
        raise ValueError(f"invalid budget month format (expected YYYY-MM): {value}")
    month_num = int(month[5:7])
    if month_num < 1 or month_num > 12:
        raise ValueError(f"invalid budget month value: {value}")
    return month


def _parse_budget_payload(payload: object) -> BudgetConfig:
    if not isinstance(payload, dict):
        raise ValueError("budget config payload must be an object")
    data = cast(dict[str, object], payload)

    currency_raw = data.get("currency", "EUR")
    currency = (
        str(currency_raw).strip().upper()
        if isinstance(currency_raw, str) and str(currency_raw).strip()
        else "EUR"
    )

    raw_targets = data.get("targets")
    if raw_targets is not None and not isinstance(raw_targets, list):
        raise ValueError("budget config field `targets` must be a list")

    parsed_targets: list[BudgetTarget] = []
    seen: set[tuple[str, str, str | None]] = set()
    for raw_target in raw_targets or []:
        if not isinstance(raw_target, dict):
            continue
        target = cast(dict[str, object], raw_target)
        month = _parse_month(target.get("month"))
        category_raw = target.get("category")
        category = str(category_raw).strip() if isinstance(category_raw, str) else ""
        if not category:
            raise ValueError("budget target category is required")
        project_raw = target.get("project")
        project = (
            str(project_raw).strip()
            if isinstance(project_raw, str) and str(project_raw).strip()
            else None
        )
        amount_raw = target.get("amount")
        amount = None
        if isinstance(amount_raw, bool):
            amount = float(int(amount_raw))
        elif isinstance(amount_raw, int | float):
            amount = float(amount_raw)
        elif isinstance(amount_raw, str) and amount_raw.strip():
            try:
                amount = float(amount_raw.strip())
            except ValueError as exc:
                raise ValueError(f"invalid budget amount for {month}/{category}") from exc
        if amount is None:
            raise ValueError(f"invalid budget amount for {month}/{category}")
        if amount <= 0:
            raise ValueError(f"budget amount must be positive for {month}/{category}")

        unique_key = (month, category.casefold(), project.casefold() if project else None)
        if unique_key in seen:
            raise ValueError(f"duplicate budget target for ({month}, {category}, {project})")
        seen.add(unique_key)
        parsed_targets.append(
            BudgetTarget(
                month=month,
                category=category,
                project=project,
                amount=amount,
            )
        )

    parsed_targets.sort(
        key=lambda item: (item.month, item.category.casefold(), (item.project or "").casefold())
    )
    return BudgetConfig(currency=currency, targets=tuple(parsed_targets))


def load_budget_config(path: Path) -> tuple[BudgetConfig, list[str]]:
    """Load budget targets from YAML/JSON."""
    if not path.exists():
        return _default_budget_config(), []
    try:
        payload = _load_payload(path)
        return _parse_budget_payload(payload), []
    except Exception as exc:
        return _default_budget_config(), [f"Failed to load budget config from {path}: {exc}"]


def budget_targets_to_rows(config: BudgetConfig) -> list[dict[str, object]]:
    """Serialize targets to plain rows for JSON payload embedding."""
    return [
        {
            "month": target.month,
            "category": target.category,
            "project": target.project,
            "amount": round(target.amount, 2),
        }
        for target in config.targets
    ]


def build_budget_status(dataframe: pd.DataFrame, config: BudgetConfig) -> pd.DataFrame:
    """Compute budget-vs-actual rows from transactions and budget targets."""
    if not config.targets:
        return pd.DataFrame(columns=list(_BUDGET_STATUS_COLUMNS))

    by_category: dict[tuple[str, str], float] = defaultdict(float)
    by_project: dict[tuple[str, str, str], float] = defaultdict(float)
    for row in dataframe.to_dict(orient="records"):
        booking_date_raw = row.get("booking_date")
        month = ""
        if isinstance(booking_date_raw, str) and len(booking_date_raw) >= 7:
            month = booking_date_raw[:7]
        elif isinstance(booking_date_raw, pd.Timestamp):
            month = cast(str, booking_date_raw.strftime("%Y-%m"))
        if not month:
            continue

        category_raw = row.get("category")
        category = str(category_raw).strip() if isinstance(category_raw, str) else ""
        if not category:
            continue

        amount_raw = row.get("amount_eur")
        amount = None
        if isinstance(amount_raw, bool):
            amount = float(int(amount_raw))
        elif isinstance(amount_raw, int | float):
            amount = float(amount_raw)
        elif isinstance(amount_raw, str) and amount_raw.strip():
            try:
                amount = float(amount_raw.strip())
            except ValueError:
                continue
        if amount is None:
            continue
        if amount >= 0:
            continue
        spend = abs(amount)

        category_key = (month, category.casefold())
        by_category[category_key] += spend

        project_raw = row.get("project")
        project = str(project_raw).strip() if isinstance(project_raw, str) else ""
        if project:
            project_key = (month, category.casefold(), project.casefold())
            by_project[project_key] += spend

    rows: list[dict[str, object]] = []
    for target in config.targets:
        category_key = (target.month, target.category.casefold())
        if target.project is None:
            actual_amount = by_category.get(category_key, 0.0)
        else:
            actual_amount = by_project.get(
                (target.month, target.category.casefold(), target.project.casefold()),
                0.0,
            )
        variance = target.amount - actual_amount
        status = "on_track" if actual_amount <= target.amount else "over_budget"
        utilization = (actual_amount / target.amount * 100.0) if target.amount > 0 else 0.0
        rows.append(
            {
                "month": target.month,
                "category": target.category,
                "project": target.project,
                "budget_amount": round(target.amount, 2),
                "actual_amount": round(actual_amount, 2),
                "variance": round(variance, 2),
                "status": status,
                "utilization_pct": round(utilization, 2),
            }
        )

    return pd.DataFrame(rows, columns=list(_BUDGET_STATUS_COLUMNS))

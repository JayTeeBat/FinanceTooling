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

from finance_tooling.categorization.classify import (
    ClassificationRules,
    resolve_category_id_from_labels,
    resolve_reporting_category_id,
    resolve_taxonomy_cashflow_type_for_category_id,
    resolve_taxonomy_decision_role_for_category_id,
    resolve_taxonomy_economic_role_for_category_id,
)
from finance_tooling.core.semantic_resolution import resolve_planning_bucket

_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
_BUDGET_STATUS_COLUMNS = (
    "month",
    "category_id",
    "category",
    "project",
    "budget_amount",
    "actual_amount",
    "variance",
    "status",
    "utilization_pct",
)
_PLANNING_LEDGER_COLUMNS = (
    "transaction_id",
    "month",
    "booking_date",
    "source_document_id",
    "description",
    "category_id",
    "reporting_category_id",
    "category",
    "subcategory",
    "project",
    "cashflow_type",
    "economic_role",
    "decision_role",
    "planning_bucket",
    "amount_eur",
    "planning_amount_eur",
    "bank",
    "account_label",
    "account_holder",
)


@dataclass(frozen=True)
class BudgetTarget:
    """Monthly budget target for one category and optional project scope."""

    month: str
    category_id: str | None
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
        category_id_raw = target.get("category_id")
        category_id = (
            str(category_id_raw).strip()
            if isinstance(category_id_raw, str) and str(category_id_raw).strip()
            else None
        )
        category_raw = target.get("category")
        category = str(category_raw).strip() if isinstance(category_raw, str) else ""
        if not category and category_id is None:
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
            target_label = category_id or category
            raise ValueError(f"budget amount must be positive for {month}/{target_label}")

        unique_key = (
            month,
            (category_id or category).casefold(),
            project.casefold() if project else None,
        )
        if unique_key in seen:
            raise ValueError(
                f"duplicate budget target for ({month}, {category_id or category}, {project})"
            )
        seen.add(unique_key)
        parsed_targets.append(
            BudgetTarget(
                month=month,
                category_id=category_id,
                category=category,
                project=project,
                amount=amount,
            )
        )

    parsed_targets.sort(
        key=lambda item: (
            item.month,
            (item.category_id or item.category).casefold(),
            (item.project or "").casefold(),
        )
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
            "category_id": target.category_id,
            "category": target.category,
            "project": target.project,
            "amount": round(target.amount, 2),
        }
        for target in config.targets
    ]


def _normalize_month_from_booking_date(value: object) -> str | None:
    if isinstance(value, str) and len(value) >= 7:
        return value[:7]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m")
    return None


def _coerce_amount(value: object) -> float | None:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _row_text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().casefold()


def _optional_text(row: dict[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _resolve_row_category_id(
    row: dict[str, object],
    *,
    classification_rules: ClassificationRules | None,
) -> str | None:
    category_id_raw = row.get("category_id")
    if isinstance(category_id_raw, str) and category_id_raw.strip():
        category_id = category_id_raw.strip()
        if classification_rules is None:
            return category_id.casefold()
        return resolve_reporting_category_id(category_id, rules=classification_rules) or category_id

    category_raw = row.get("category")
    category = str(category_raw).strip() if isinstance(category_raw, str) else ""
    subcategory_raw = row.get("subcategory")
    subcategory = str(subcategory_raw).strip() if isinstance(subcategory_raw, str) else None
    if not category:
        return None
    if classification_rules is None:
        return category.casefold()
    resolved = resolve_category_id_from_labels(
        category,
        subcategory,
        rules=classification_rules,
        prefer_active=True,
    )
    return resolved or category.casefold()


def _resolve_target_category_id(
    target: BudgetTarget,
    *,
    classification_rules: ClassificationRules | None,
) -> str | None:
    if target.category_id is not None:
        if classification_rules is None:
            return target.category_id.casefold()
        return (
            resolve_reporting_category_id(target.category_id, rules=classification_rules)
            or target.category_id
        )
    if classification_rules is None:
        return target.category.casefold() if target.category else None
    return resolve_category_id_from_labels(
        target.category,
        None,
        rules=classification_rules,
        prefer_active=True,
    )


def build_monthly_planning_ledger(
    dataframe: pd.DataFrame,
    *,
    classification_rules: ClassificationRules | None = None,
) -> pd.DataFrame:
    """Build a row-level monthly planning ledger traceable to source transactions."""
    if dataframe.empty:
        return pd.DataFrame(columns=list(_PLANNING_LEDGER_COLUMNS))

    rows: list[dict[str, object]] = []
    for row in dataframe.to_dict(orient="records"):
        month = _normalize_month_from_booking_date(row.get("booking_date"))
        if month is None:
            continue
        amount = _coerce_amount(row.get("amount_eur"))
        if amount is None:
            continue
        category_id = _resolve_row_category_id(row, classification_rules=classification_rules)
        reporting_category_id = (
            resolve_reporting_category_id(category_id, rules=classification_rules)
            if category_id is not None and classification_rules is not None
            else category_id
        )
        cashflow_type = _row_text(row, "cashflow_type")
        economic_role = _row_text(row, "economic_role")
        decision_role = _row_text(row, "decision_role")
        if classification_rules is not None and category_id is not None:
            if cashflow_type in {"", "unknown"}:
                cashflow_type = (
                    resolve_taxonomy_cashflow_type_for_category_id(
                        category_id,
                        rules=classification_rules,
                    )
                    or cashflow_type
                )
            if economic_role in {"", "unknown"}:
                economic_role = (
                    resolve_taxonomy_economic_role_for_category_id(
                        category_id,
                        rules=classification_rules,
                    )
                    or economic_role
                )
            if decision_role in {"", "unknown"}:
                decision_role = (
                    resolve_taxonomy_decision_role_for_category_id(
                        category_id,
                        rules=classification_rules,
                    )
                    or decision_role
                )
        planning_bucket, planning_amount = resolve_planning_bucket(
            cashflow_type,
            economic_role,
            decision_role,
            amount,
        )
        rows.append(
            {
                "transaction_id": row.get("transaction_id"),
                "month": month,
                "booking_date": row.get("booking_date"),
                "source_document_id": row.get("source_document_id"),
                "description": row.get("description"),
                "category_id": category_id,
                "reporting_category_id": reporting_category_id,
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "project": row.get("project"),
                "cashflow_type": cashflow_type or None,
                "economic_role": economic_role or None,
                "decision_role": decision_role or None,
                "planning_bucket": planning_bucket,
                "amount_eur": amount,
                "planning_amount_eur": round(planning_amount, 2),
                "bank": row.get("bank"),
                "account_label": row.get("account_label"),
                "account_holder": _optional_text(row, "account_holder")
                or _optional_text(row, "account_label"),
            }
        )

    ledger = pd.DataFrame(rows, columns=list(_PLANNING_LEDGER_COLUMNS))
    if ledger.empty:
        return ledger
    return ledger.sort_values(
        by=["month", "category_id", "project", "transaction_id"],
        kind="stable",
        ignore_index=True,
    )


def build_budget_status(
    dataframe: pd.DataFrame,
    config: BudgetConfig,
    *,
    classification_rules: ClassificationRules | None = None,
) -> pd.DataFrame:
    """Compute budget-vs-actual rows from transactions and budget targets."""
    if not config.targets:
        return pd.DataFrame(columns=list(_BUDGET_STATUS_COLUMNS))

    ledger = build_monthly_planning_ledger(
        dataframe,
        classification_rules=classification_rules,
    )
    if ledger.empty:
        return pd.DataFrame(columns=list(_BUDGET_STATUS_COLUMNS))

    by_category: dict[tuple[str, str], float] = defaultdict(float)
    by_project: dict[tuple[str, str, str], float] = defaultdict(float)

    expense_ledger = ledger[ledger["planning_bucket"].eq("expense")]
    for row in expense_ledger.to_dict(orient="records"):
        month = str(row.get("month") or "").strip()
        category_id = str(row.get("category_id") or "").strip()
        if not month or not category_id:
            continue
        amount = _coerce_amount(row.get("planning_amount_eur"))
        if amount is None:
            continue
        by_category[(month, category_id.casefold())] += amount
        project = str(row.get("project") or "").strip()
        if project:
            by_project[(month, category_id.casefold(), project.casefold())] += amount

    rows: list[dict[str, object]] = []
    for target in config.targets:
        target_category_id = _resolve_target_category_id(
            target,
            classification_rules=classification_rules,
        )
        if target_category_id is None:
            continue
        category_key = (target.month, target_category_id.casefold())
        if target.project is None:
            actual_amount = by_category.get(category_key, 0.0)
        else:
            actual_amount = by_project.get(
                (target.month, target_category_id.casefold(), target.project.casefold()),
                0.0,
            )
        variance = target.amount - actual_amount
        status = "on_track" if actual_amount <= target.amount else "over_budget"
        utilization = (actual_amount / target.amount * 100.0) if target.amount > 0 else 0.0
        rows.append(
            {
                "month": target.month,
                "category_id": target_category_id,
                "category": target.category or target_category_id,
                "project": target.project,
                "budget_amount": round(target.amount, 2),
                "actual_amount": round(actual_amount, 2),
                "variance": round(variance, 2),
                "status": status,
                "utilization_pct": round(utilization, 2),
            }
        )

    return pd.DataFrame(rows, columns=list(_BUDGET_STATUS_COLUMNS))

"""Shared helpers for transaction semantic defaults and normalization."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from finance_tooling.core.semantics import (
    EXPENSE_LIKE_ECONOMIC_ROLES,
    VALID_CASHFLOW_ROLES,
    VALID_DECISION_ROLES,
    VALID_ECONOMIC_ROLES,
    CashflowRoleType,
    CashflowType,
    DecisionRoleType,
    EconomicRoleType,
)

_ESSENTIAL_CATEGORY_NAMES = frozenset(
    {"groceries", "housing", "utilities", "family", "insurance", "transport"}
)
_DISCRETIONARY_CATEGORY_NAMES = frozenset({"dining", "shopping", "leisure"})
_NOT_APPLICABLE_CATEGORY_NAMES = frozenset(
    {"non personal transactions", "pass-through", "excluded"}
)
_TRANSFER_DECISION_ROLE_MARKERS: tuple[tuple[str, DecisionRoleType], ...] = (
    ("savings", "savings"),
    ("retirement", "savings"),
    ("house", "savings"),
    ("emergency", "savings"),
    ("investment", "investment"),
    ("loan", "debt_service"),
    ("debt", "debt_service"),
    ("mortgage", "debt_service"),
    ("tax", "tax"),
)


def _normalized_text(value: object) -> str:
    return str(value).strip().casefold() if value is not None else ""


def _transfer_planning_bucket_for_row(
    *,
    category_id: object = None,
    category: object = None,
    subcategory: object = None,
) -> str | None:
    """Return a transfer planning bucket from transfer semantic labels."""
    normalized_category_id = _normalized_text(category_id)
    normalized_category = _normalized_text(category)
    normalized_subcategory = _normalized_text(subcategory)
    normalized_text = " ".join(
        value
        for value in (normalized_category_id, normalized_category, normalized_subcategory)
        if value
    )
    if any(marker in normalized_text for marker in ("savings", "retirement", "house", "emergency")):
        return "savings"
    if "investment" in normalized_text:
        return "investment"
    if any(marker in normalized_text for marker in ("loan", "debt", "mortgage")):
        return "debt_service"
    if "tax" in normalized_text:
        return "tax"
    return None


def normalize_cashflow_role_value(value: object) -> CashflowRoleType | None:
    """Return a valid cashflow role when the value is already canonical."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in VALID_CASHFLOW_ROLES:
        return cast(CashflowRoleType, normalized)
    return None


def normalize_cashflow_role_for_row(value: object) -> CashflowRoleType | None:
    """Compatibility alias for row-level cashflow normalization."""
    return normalize_cashflow_role_value(value)


def normalize_cashflow_type_value(value: object) -> CashflowType | None:
    """Legacy compatibility alias for row-level cashflow normalization."""
    return normalize_cashflow_role_value(value)


def normalize_cashflow_type_for_row(value: object) -> CashflowType | None:
    """Legacy compatibility alias for row-level cashflow normalization."""
    return normalize_cashflow_type_value(value)


def normalize_economic_role_value(value: object) -> EconomicRoleType | None:
    """Return a valid economic role when the value is already canonical."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in VALID_ECONOMIC_ROLES:
        return cast(EconomicRoleType, normalized)
    return None


def normalize_economic_role_for_row(
    value: object,
    *,
    cashflow_role: object = None,
    cashflow_type: object = None,
    category: object = None,
    subcategory: object = None,
) -> EconomicRoleType | None:
    """Normalize a resolved economic role with semantic fallbacks."""
    normalized = normalize_economic_role_value(value)
    if normalized is not None:
        return normalized
    normalized_cashflow_role = normalize_cashflow_role_value(cashflow_role or cashflow_type)
    normalized_category = _normalized_text(category)
    normalized_subcategory = _normalized_text(subcategory)
    if normalized_cashflow_role == "transfer":
        return None
    if normalized_category in {"non personal transactions", "pass-through", "excluded"}:
        return "exclude"
    if normalized_category == "income":
        fallback = "income"
    elif normalized_subcategory in {"salary", "interest"}:
        fallback = "income"
    else:
        fallback = "variable_expense"
    return fallback


def normalize_decision_role_value(value: object) -> DecisionRoleType | None:
    """Return a valid decision role when the value is already canonical."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in VALID_DECISION_ROLES:
        return cast(DecisionRoleType, normalized)
    return None


def normalize_decision_role_for_row(
    value: object,
    *,
    cashflow_role: object = None,
    cashflow_type: object = None,
    economic_role: object = None,
    category: object = None,
    subcategory: object = None,
) -> DecisionRoleType:
    """Normalize a resolved decision role with semantic fallbacks."""
    normalized_cashflow_role = normalize_cashflow_role_value(cashflow_role or cashflow_type)
    normalized_economic_role = normalize_economic_role_value(economic_role)
    normalized_category = _normalized_text(category)
    normalized_subcategory = _normalized_text(subcategory)

    if normalized_cashflow_role == "transfer":
        return "not_applicable"
    if normalized_economic_role in {"exclude", "income"}:
        return "not_applicable"
    normalized = normalize_decision_role_value(value)
    if normalized is not None and normalized != "unknown":
        return normalized

    fallback: DecisionRoleType = "unknown"
    if normalized_category in _ESSENTIAL_CATEGORY_NAMES:
        fallback = "essential"
    elif normalized_category == "taxes":
        fallback = "tax"
    elif normalized_category in _DISCRETIONARY_CATEGORY_NAMES:
        fallback = "discretionary"
    elif normalized_category == "transfers" and any(
        marker in normalized_subcategory
        for marker, role in _TRANSFER_DECISION_ROLE_MARKERS
        if role == "savings"
    ):
        fallback = "savings"
    elif normalized_category == "transfers" and "investment" in normalized_subcategory:
        fallback = "investment"
    elif normalized_category == "transfers" and any(
        marker in normalized_subcategory
        for marker, role in _TRANSFER_DECISION_ROLE_MARKERS
        if role == "debt_service"
    ):
        fallback = "debt_service"
    elif normalized_category == "transfers" and "tax" in normalized_subcategory:
        fallback = "tax"
    return fallback


def default_cashflow_type_for_category(category: str) -> CashflowType | None:
    """Return the legacy cashflow default for a category label."""
    normalized = _normalized_text(category)
    if normalized == "income":
        return "in"
    if normalized == "transfers":
        return "transfer"
    if normalized:
        return "out"
    return None


def default_economic_role_for_category(
    category: str,
    *,
    cashflow_role: CashflowRoleType | None,
) -> EconomicRoleType | None:
    """Return the legacy economic-role default for a category label."""
    normalized = _normalized_text(category)
    if cashflow_role == "transfer":
        return None
    if normalized == "income":
        return "income"
    if normalized in {"non personal transactions", "pass-through", "excluded"}:
        return "exclude"
    return "variable_expense"


def default_decision_role_for_category(
    category: str,
    subcategory: str | None,
    *,
    cashflow_role: CashflowRoleType | None,
    economic_role: EconomicRoleType | None,
) -> DecisionRoleType:
    """Return the legacy planning default for a category label."""
    normalized_category = _normalized_text(category)
    if cashflow_role == "transfer" or economic_role == "exclude":
        return "not_applicable"
    if normalized_category in _NOT_APPLICABLE_CATEGORY_NAMES:
        return "not_applicable"
    if normalized_category in _ESSENTIAL_CATEGORY_NAMES:
        return "essential"
    if normalized_category == "taxes":
        return "tax"
    if normalized_category in _DISCRETIONARY_CATEGORY_NAMES:
        return "discretionary"
    return "unknown"


def resolve_planning_bucket(
    cashflow_role: object,
    economic_role: object,
    decision_role: object,
    amount_eur: object,
    *,
    category_id: object = None,
    category: object = None,
    subcategory: object = None,
) -> tuple[str, float]:
    """Resolve the planning bucket and planned amount from semantic fields."""
    normalized_cashflow_role = normalize_cashflow_role_value(cashflow_role)
    normalized_economic_role = normalize_economic_role_value(economic_role)
    _ = normalize_decision_role_value(decision_role)
    amount = 0.0
    if isinstance(amount_eur, bool):
        amount = float(int(amount_eur))
    elif isinstance(amount_eur, int | float):
        amount = float(amount_eur)
    elif isinstance(amount_eur, Decimal):
        amount = float(amount_eur)

    if normalized_cashflow_role == "transfer":
        transfer_bucket = _transfer_planning_bucket_for_row(
            category_id=category_id,
            category=category,
            subcategory=subcategory,
        )
        if transfer_bucket is not None:
            return transfer_bucket, abs(amount)
        return (
            "transfer",
            abs(amount),
        )
    if normalized_economic_role in EXPENSE_LIKE_ECONOMIC_ROLES:
        return "expense", -amount
    if normalized_economic_role == "income":
        return "income", (amount if amount > 0 else 0.0)
    if normalized_economic_role == "exclude":
        return "excluded", 0.0
    return "unknown", 0.0

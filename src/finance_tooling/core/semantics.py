"""Shared cashflow and economic role semantics."""

from __future__ import annotations

from typing import Literal

CashflowRoleType = Literal["in", "out", "transfer"]
CashflowType = CashflowRoleType
EconomicRoleType = Literal[
    "income",
    "fixed_expense",
    "variable_expense",
    "expense",
    "exclude",
]
DecisionRoleType = Literal[
    "essential",
    "discretionary",
    "savings",
    "investment",
    "debt_service",
    "tax",
    "not_applicable",
    "unknown",
]

VALID_CASHFLOW_ROLES = frozenset({"in", "out", "transfer"})
VALID_CASHFLOW_TYPES = VALID_CASHFLOW_ROLES
VALID_ECONOMIC_ROLES = frozenset(
    {"income", "fixed_expense", "variable_expense", "expense", "exclude"}
)
VALID_DECISION_ROLES = frozenset(
    {
        "essential",
        "discretionary",
        "savings",
        "investment",
        "debt_service",
        "tax",
        "not_applicable",
        "unknown",
    }
)
EXPENSE_LIKE_ECONOMIC_ROLES = frozenset({"expense", "fixed_expense", "variable_expense"})

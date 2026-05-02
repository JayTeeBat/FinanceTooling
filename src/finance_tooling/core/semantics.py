"""Shared cashflow and economic role semantics."""

from __future__ import annotations

from typing import Literal

CashflowType = Literal["in", "out", "transfer", "exclude"]
EconomicRoleType = Literal[
    "income",
    "fixed_expense",
    "variable_expense",
    "expense",
    "transfer",
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

VALID_CASHFLOW_TYPES = frozenset({"in", "out", "transfer", "exclude"})
VALID_ECONOMIC_ROLES = frozenset(
    {"income", "fixed_expense", "variable_expense", "expense", "transfer", "exclude"}
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

"""Transaction classification heuristics."""

from __future__ import annotations

from dataclasses import replace

from finance_tooling.models import Transaction

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Groceries": ("supermarket", "grocery", "carrefour", "spinneys", "market"),
    "Dining": ("restaurant", "cafe", "coffee", "bar", "food"),
    "Transport": ("uber", "careem", "taxi", "fuel", "gas", "metro", "bus"),
    "Housing": ("rent", "landlord", "mortgage", "maintenance", "utilities"),
    "Shopping": ("amazon", "store", "mall", "shop", "ecommerce"),
    "Income": ("salary", "payroll", "bonus", "refund", "interest"),
    "Fees": ("fee", "commission", "charge", "penalty", "service charge"),
    "Transfers": ("transfer", "swift", "wire", "internal transfer"),
}


def classify_description(description: str) -> str:
    """Classify a transaction description into a high-level category."""
    normalized = description.strip().lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return category
    return "Uncategorized"


def classify_transactions(transactions: list[Transaction]) -> list[Transaction]:
    """Return a new list of transactions with categories assigned."""
    return [replace(tx, category=classify_description(tx.description)) for tx in transactions]

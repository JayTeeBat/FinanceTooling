"""Transaction classification rules, taxonomy semantics, and override handling."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypedDict, cast

import yaml

from finance_tooling.core.models import Transaction
from finance_tooling.core.semantic_resolution import (
    default_cashflow_type_for_category,
    default_decision_role_for_category,
    default_economic_role_for_category,
)
from finance_tooling.core.semantics import (
    VALID_CASHFLOW_TYPES,
    VALID_DECISION_ROLES,
    VALID_ECONOMIC_ROLES,
    CashflowRoleType,
    CashflowType,
    DecisionRoleType,
    EconomicRoleType,
)

MatchType = Literal["contains", "exact", "regex"]


def _legacy_cashflow_type_for_category(category: str) -> CashflowType | None:
    return default_cashflow_type_for_category(category)


def _legacy_economic_role_for_category(
    category: str,
    *,
    cashflow_role: CashflowRoleType | None,
) -> EconomicRoleType | None:
    return default_economic_role_for_category(category, cashflow_role=cashflow_role)


def _legacy_decision_role_for_category(
    category: str,
    subcategory: str | None,
    *,
    cashflow_role: CashflowRoleType | None,
    economic_role: EconomicRoleType | None,
) -> DecisionRoleType:
    return default_decision_role_for_category(
        category,
        subcategory,
        cashflow_role=cashflow_role,
        economic_role=economic_role,
    )


def _normalize_category_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if not normalized:
        return None
    normalized = re.sub(r"[^a-z0-9.]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    normalized = re.sub(r"\.+", ".", normalized).strip("._")
    segments = [segment.strip("_") for segment in normalized.split(".") if segment.strip("_")]
    if not segments:
        return None
    return ".".join(segments)


def _build_legacy_category_id(category: str, subcategory: str | None) -> str:
    category_id = _normalize_category_id(category) or "uncategorized"
    subcategory_id = _normalize_category_id(subcategory) if subcategory else None
    return f"{category_id}.{subcategory_id}" if subcategory_id else category_id


def _normalize_economic_role(value: object) -> EconomicRoleType | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in VALID_ECONOMIC_ROLES:
        return cast(EconomicRoleType, normalized)
    return None


def _normalize_decision_role(value: object) -> DecisionRoleType | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in VALID_DECISION_ROLES:
        return cast(DecisionRoleType, normalized)
    return None


def _taxonomy_entries_by_id(rules: ClassificationRules) -> dict[str, TaxonomyCategory]:
    entries: dict[str, TaxonomyCategory] = {}
    for raw_key, raw_entry in rules.taxonomy.items():
        key = _normalize_category_id(raw_key)
        if key is None:
            continue

        if (
            raw_entry.category_label is not None
            or raw_entry.subcategory_label is not None
            or raw_entry.deprecated_to is not None
            or raw_entry.economic_role is not None
            or raw_entry.status != "active"
        ):
            category_label = raw_entry.category_label or raw_entry.name
            entries[key] = TaxonomyCategory(
                name=raw_entry.name,
                subcategories=raw_entry.subcategories,
                cashflow_type=raw_entry.cashflow_type,
                economic_role=raw_entry.economic_role
                or _legacy_economic_role_for_category(
                    category_label,
                    cashflow_role=raw_entry.cashflow_type,
                ),
                decision_role=raw_entry.decision_role
                or _legacy_decision_role_for_category(
                    category_label,
                    raw_entry.subcategory_label,
                    cashflow_role=raw_entry.cashflow_type,
                    economic_role=raw_entry.economic_role,
                ),
                category_label=category_label,
                subcategory_label=raw_entry.subcategory_label,
                deprecated_to=_normalize_category_id(raw_entry.deprecated_to),
                status=raw_entry.status,
            )
            continue

        if raw_entry.subcategories:
            for subcategory in raw_entry.subcategories:
                entry_id = _build_legacy_category_id(raw_entry.name, subcategory)
                entries[entry_id] = TaxonomyCategory(
                    name=raw_entry.name,
                    subcategories=(),
                    cashflow_type=raw_entry.cashflow_type,
                    economic_role=raw_entry.economic_role
                    or _legacy_economic_role_for_category(
                        raw_entry.name,
                        cashflow_role=raw_entry.cashflow_type,
                    ),
                    decision_role=raw_entry.decision_role
                    or _legacy_decision_role_for_category(
                        raw_entry.name,
                        subcategory,
                        cashflow_role=raw_entry.cashflow_type,
                        economic_role=raw_entry.economic_role,
                    ),
                    category_label=raw_entry.name,
                    subcategory_label=subcategory,
                )
        else:
            entries[key] = TaxonomyCategory(
                name=raw_entry.name,
                subcategories=(),
                cashflow_type=raw_entry.cashflow_type,
                economic_role=raw_entry.economic_role
                or _legacy_economic_role_for_category(
                    raw_entry.name,
                    cashflow_role=raw_entry.cashflow_type,
                ),
                decision_role=raw_entry.decision_role
                or _legacy_decision_role_for_category(
                    raw_entry.name,
                    None,
                    cashflow_role=raw_entry.cashflow_type,
                    economic_role=raw_entry.economic_role,
                ),
                category_label=raw_entry.name,
                subcategory_label=None,
            )
    return entries


def _taxonomy_label_index(
    rules: ClassificationRules,
    *,
    active_only: bool,
) -> dict[tuple[str, str | None], str]:
    index: dict[tuple[str, str | None], str] = {}
    for category_id, entry in _taxonomy_entries_by_id(rules).items():
        if active_only and entry.status != "active":
            continue
        category_label = (entry.category_label or entry.name).strip()
        if not category_label:
            continue
        subcategory_label = entry.subcategory_label.strip() if entry.subcategory_label else None
        label_key = (
            category_label.casefold(),
            subcategory_label.casefold() if subcategory_label else None,
        )
        index[label_key] = category_id
    return index


def resolve_reporting_category_id(
    category_id: str | None,
    *,
    rules: ClassificationRules,
) -> str | None:
    normalized = _normalize_category_id(category_id)
    if normalized is None:
        return None
    entries = _taxonomy_entries_by_id(rules)
    current = normalized
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        entry = entries.get(current)
        if entry is None or not entry.deprecated_to:
            return current
        current = entry.deprecated_to
    return current


def resolve_category_id_from_labels(
    category: str | None,
    subcategory: str | None,
    *,
    rules: ClassificationRules,
    prefer_active: bool = False,
) -> str | None:
    if category is None:
        return None
    normalized_category = category.strip()
    if not normalized_category or normalized_category.casefold() == "uncategorized":
        return None
    normalized_subcategory = subcategory.strip() if isinstance(subcategory, str) else None
    raw_key = (
        normalized_category.casefold(),
        normalized_subcategory.casefold() if normalized_subcategory else None,
    )
    index = _taxonomy_label_index(rules, active_only=prefer_active)
    resolved = index.get(raw_key)
    if resolved is not None:
        return resolved
    if prefer_active:
        resolved = _taxonomy_label_index(rules, active_only=False).get(raw_key)
        if resolved is not None:
            return resolve_reporting_category_id(resolved, rules=rules)
    return _build_legacy_category_id(normalized_category, normalized_subcategory)


def resolve_taxonomy_labels(
    category_id: str | None,
    *,
    rules: ClassificationRules,
) -> tuple[str | None, str | None]:
    reporting_id = resolve_reporting_category_id(category_id, rules=rules)
    if reporting_id is None:
        return None, None
    entry = _taxonomy_entries_by_id(rules).get(reporting_id)
    if entry is None:
        return None, None
    return entry.category_label or entry.name, entry.subcategory_label


def resolve_taxonomy_cashflow_type_for_category_id(
    category_id: str | None,
    *,
    rules: ClassificationRules,
) -> CashflowType | None:
    reporting_id = resolve_reporting_category_id(category_id, rules=rules)
    if reporting_id is None:
        return None
    entry = _taxonomy_entries_by_id(rules).get(reporting_id)
    if entry is None:
        return None
    return entry.cashflow_type


def resolve_taxonomy_economic_role_for_category_id(
    category_id: str | None,
    *,
    rules: ClassificationRules,
) -> EconomicRoleType | None:
    reporting_id = resolve_reporting_category_id(category_id, rules=rules)
    if reporting_id is None:
        return None
    entry = _taxonomy_entries_by_id(rules).get(reporting_id)
    if entry is None:
        return None
    return entry.economic_role


def resolve_taxonomy_decision_role_for_category_id(
    category_id: str | None,
    *,
    rules: ClassificationRules,
) -> DecisionRoleType | None:
    reporting_id = resolve_reporting_category_id(category_id, rules=rules)
    if reporting_id is None:
        return None
    entry = _taxonomy_entries_by_id(rules).get(reporting_id)
    if entry is None:
        return None
    return entry.decision_role


@dataclass(frozen=True)
class CategoryRule:
    """A single deterministic categorization rule."""

    rule_id: str
    priority: int
    category_id: str | None = None
    category: str = "Uncategorized"
    subcategory: str | None = None
    match_type: MatchType = "contains"
    patterns: tuple[str, ...] = ()
    expense_only: bool = False
    income_only: bool = False
    economic_role: EconomicRoleType | None = None
    decision_role: DecisionRoleType | None = None
    banks: tuple[str, ...] = ()
    account_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassificationRules:
    """Ordered rule set used by the categorizer."""

    rules: tuple[CategoryRule, ...]
    taxonomy: dict[str, TaxonomyCategory] = field(default_factory=dict)


@dataclass(frozen=True)
class TaxonomyCategory:
    """Structured taxonomy metadata for a category."""

    name: str
    subcategories: tuple[str, ...]
    cashflow_type: CashflowType | None
    economic_role: EconomicRoleType | None = None
    decision_role: DecisionRoleType | None = None
    category_label: str | None = None
    subcategory_label: str | None = None
    deprecated_to: str | None = None
    status: str = "active"


@dataclass(frozen=True)
class OverrideEntry:
    """Persistent user correction for a normalized description fingerprint."""

    fingerprint: str
    category: str
    subcategory: str | None
    bank: str | None
    account_label: str | None
    hit_count: int


@dataclass(frozen=True)
class OverrideStore:
    """Container for user overrides."""

    entries: tuple[OverrideEntry, ...]

    def lookup(
        self,
        *,
        fingerprint: str,
        bank: str,
        account_label: str | None,
    ) -> OverrideEntry | None:
        """Find best matching override for the transaction fingerprint."""
        normalized_bank = bank.strip().upper()
        normalized_account = (account_label or "").strip().upper() or None
        for entry in self.entries:
            if entry.fingerprint != fingerprint:
                continue
            if entry.bank is not None and entry.bank.strip().upper() != normalized_bank:
                continue
            if (
                entry.account_label is not None
                and entry.account_label.strip().upper() != normalized_account
            ):
                continue
            return entry
        return None


class UncategorizedDescriptionSummary(TypedDict):
    description: str
    count: int


class TopRuleHitSummary(TypedDict):
    rule_id: str
    count: int


@dataclass(frozen=True)
class ClassificationDiagnostics:
    """Summary statistics for a classification run."""

    categorized_count: int
    uncategorized_count: int
    uncategorized_ratio: float
    category_source_counts: dict[str, int]
    top_uncategorized_descriptions: list[UncategorizedDescriptionSummary]
    top_rules_by_hits: list[TopRuleHitSummary]


def normalize_description(description: str) -> str:
    """Normalize transaction descriptions for deterministic matching."""
    normalized = description.strip().lower()
    normalized = re.sub(r"\b\d{4,}\b", " ", normalized)
    normalized = re.sub(r"\b(ref|reference|txn|transaction|card|cb|pos)\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _default_rules() -> ClassificationRules:
    rules: list[CategoryRule] = []
    defaults: list[tuple[str, str, tuple[str, ...], str]] = [
        (
            "groceries.general",
            "Groceries",
            ("supermarket", "grocery", "carrefour", "market"),
            "General",
        ),
        ("dining.restaurants", "Dining", ("restaurant", "cafe", "coffee", "bar"), "Restaurants"),
        (
            "transport.mobility",
            "Transport",
            ("uber", "careem", "taxi", "metro", "bus", "fuel", "gas"),
            "Mobility",
        ),
        (
            "housing.housing_costs",
            "Housing",
            ("rent", "landlord", "mortgage", "utilities"),
            "Housing Costs",
        ),
        (
            "shopping.general",
            "Shopping",
            ("amazon", "shop", "store", "mall", "ecommerce"),
            "General",
        ),
        ("income.salary", "Income", ("salary", "payroll", "bonus"), "Salary"),
        ("income.refunds", "Income", ("refund", "interest"), "Refunds & Interest"),
        ("fees.bank_fees", "Fees", ("fee", "commission", "charge", "penalty"), "Bank Fees"),
        ("transfers.internal", "Transfers", ("transfer", "swift", "wire"), "Internal/External"),
    ]
    for index, (rule_id, category, patterns, subcategory) in enumerate(defaults):
        rules.append(
            CategoryRule(
                rule_id=rule_id,
                priority=100 - index,
                category_id=_build_legacy_category_id(category, subcategory),
                category=category,
                subcategory=subcategory,
                match_type="contains",
                patterns=patterns,
                expense_only=False,
                income_only=False,
                economic_role=None,
                banks=(),
                account_labels=(),
            )
        )
    default_taxonomy = {
        "groceries.general": TaxonomyCategory(
            name="Groceries",
            subcategories=(),
            cashflow_type="out",
            economic_role="variable_expense",
            decision_role="essential",
            category_label="Groceries",
            subcategory_label="General",
        ),
        "dining.restaurants": TaxonomyCategory(
            name="Dining",
            subcategories=(),
            cashflow_type="out",
            economic_role="variable_expense",
            decision_role="discretionary",
            category_label="Dining",
            subcategory_label="Restaurants",
        ),
        "transport.mobility": TaxonomyCategory(
            name="Transport",
            subcategories=(),
            cashflow_type="out",
            economic_role="variable_expense",
            decision_role="essential",
            category_label="Transport",
            subcategory_label="Mobility",
        ),
        "housing.housing_costs": TaxonomyCategory(
            name="Housing",
            subcategories=(),
            cashflow_type="out",
            economic_role="fixed_expense",
            decision_role="essential",
            category_label="Housing",
            subcategory_label="Housing Costs",
        ),
        "shopping.general": TaxonomyCategory(
            name="Shopping",
            subcategories=(),
            cashflow_type="out",
            economic_role="variable_expense",
            decision_role="discretionary",
            category_label="Shopping",
            subcategory_label="General",
        ),
        "income.salary": TaxonomyCategory(
            name="Income",
            subcategories=(),
            cashflow_type="in",
            economic_role="income",
            decision_role="not_applicable",
            category_label="Income",
            subcategory_label="Salary",
        ),
        "income.refunds": TaxonomyCategory(
            name="Income",
            subcategories=(),
            cashflow_type="in",
            economic_role="income",
            decision_role="not_applicable",
            category_label="Income",
            subcategory_label="Refunds & Interest",
        ),
        "fees.bank_fees": TaxonomyCategory(
            name="Fees",
            subcategories=(),
            cashflow_type="out",
            economic_role="variable_expense",
            decision_role="essential",
            category_label="Fees",
            subcategory_label="Bank Fees",
        ),
        "transfers.internal": TaxonomyCategory(
            name="Transfers",
            subcategories=(),
            cashflow_type="transfer",
            decision_role="not_applicable",
            category_label="Transfers",
            subcategory_label="Internal/External",
        ),
        "non_personal_transactions": TaxonomyCategory(
            name="Non Personal Transactions",
            subcategories=(),
            cashflow_type="out",
            economic_role="exclude",
            decision_role="not_applicable",
            category_label="Non Personal Transactions",
            subcategory_label=None,
        ),
        "pass_through": TaxonomyCategory(
            name="Pass-through",
            subcategories=(),
            cashflow_type="out",
            economic_role="exclude",
            decision_role="not_applicable",
            category_label="Pass-through",
            subcategory_label=None,
        ),
    }
    return ClassificationRules(rules=tuple(rules), taxonomy=default_taxonomy)


def _to_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _parse_rules_payload(payload: object) -> ClassificationRules:
    if not isinstance(payload, dict):
        raise ValueError("rules payload must be a JSON object")
    payload_object = cast(dict[str, object], payload)
    raw_rules = payload_object.get("rules")
    if not isinstance(raw_rules, list):
        raise ValueError("rules payload must include a list field named 'rules'")

    taxonomy = _parse_taxonomy(payload_object.get("taxonomy"))

    parsed: list[CategoryRule] = []
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            continue
        raw_rule = cast(dict[str, object], raw)
        match_type_raw = raw_rule.get("match_type", raw_rule.get("match"))
        match_type = (
            str(match_type_raw).lower()
            if isinstance(match_type_raw, str) and match_type_raw.strip()
            else "contains"
        )
        if match_type not in {"contains", "exact", "regex"}:
            continue
        typed_match_type = cast(MatchType, match_type)
        patterns_raw = raw_rule.get("patterns")
        if not isinstance(patterns_raw, list):
            continue
        raw_patterns = [str(item).strip() for item in patterns_raw if str(item).strip()]
        if typed_match_type in {"contains", "exact"}:
            normalized_patterns = [normalize_description(pattern) for pattern in raw_patterns]
            patterns = tuple(pattern for pattern in normalized_patterns if pattern)
        else:
            patterns = tuple(pattern.lower() for pattern in raw_patterns)
        if not patterns:
            continue
        rule_id_raw = raw_rule.get("rule_id", raw_rule.get("id"))
        category_id_raw = raw_rule.get("category_id")
        category_raw = raw_rule.get("category")
        subcategory_raw = raw_rule.get("subcategory")
        banks_raw = raw_rule.get("banks")
        account_labels_raw = raw_rule.get("account_labels")
        parsed.append(
            CategoryRule(
                rule_id=(
                    str(rule_id_raw).strip()
                    if isinstance(rule_id_raw, str) and str(rule_id_raw).strip()
                    else f"rule_{index + 1}"
                ),
                priority=_to_int(raw_rule.get("priority"), default=0),
                category_id=(
                    _normalize_category_id(category_id_raw)
                    if category_id_raw is not None
                    else (
                        _build_legacy_category_id(str(category_raw), str(subcategory_raw).strip())
                        if isinstance(category_raw, str)
                        and str(category_raw).strip()
                        and isinstance(subcategory_raw, str)
                        and str(subcategory_raw).strip()
                        else (
                            _build_legacy_category_id(str(category_raw), None)
                            if isinstance(category_raw, str) and str(category_raw).strip()
                            else None
                        )
                    )
                ),
                category=(
                    str(category_raw).strip()
                    if isinstance(category_raw, str) and str(category_raw).strip()
                    else "Uncategorized"
                ),
                subcategory=(
                    str(subcategory_raw).strip()
                    if isinstance(subcategory_raw, str) and str(subcategory_raw).strip()
                    else None
                ),
                match_type=typed_match_type,
                patterns=patterns,
                expense_only=bool(raw_rule.get("expense_only")),
                income_only=bool(raw_rule.get("income_only")),
                economic_role=_normalize_economic_role(raw_rule.get("economic_role")),
                decision_role=_normalize_decision_role(raw_rule.get("decision_role")),
                banks=tuple(
                    str(item).strip().upper()
                    for item in (banks_raw if isinstance(banks_raw, list) else [])
                    if str(item).strip()
                ),
                account_labels=tuple(
                    str(item).strip().upper()
                    for item in (account_labels_raw if isinstance(account_labels_raw, list) else [])
                    if str(item).strip()
                ),
            )
        )
    sorted_rules = sorted(parsed, key=lambda rule: (-rule.priority, rule.rule_id))
    return ClassificationRules(rules=tuple(sorted_rules), taxonomy=taxonomy)


def _normalize_cashflow_type(value: object) -> CashflowType | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in VALID_CASHFLOW_TYPES:
        return cast(CashflowType, normalized)
    return None


def _parse_taxonomy(raw_taxonomy: object) -> dict[str, TaxonomyCategory]:
    if not isinstance(raw_taxonomy, dict):
        return {}

    taxonomy: dict[str, TaxonomyCategory] = {}
    for raw_category, raw_value in cast(dict[object, object], raw_taxonomy).items():
        raw_key = str(raw_category).strip()
        if not raw_key:
            continue

        if isinstance(raw_value, list):
            category_label = raw_key
            subcategories = tuple(str(item).strip() for item in raw_value if str(item).strip())
            cashflow_type = _legacy_cashflow_type_for_category(category_label)
            taxonomy[category_label.casefold()] = TaxonomyCategory(
                name=category_label,
                subcategories=subcategories,
                cashflow_type=cashflow_type,
                economic_role=_legacy_economic_role_for_category(
                    category_label,
                    cashflow_role=cashflow_type,
                ),
                decision_role=_legacy_decision_role_for_category(
                    category_label,
                    None,
                    cashflow_role=cashflow_type,
                    economic_role=_legacy_economic_role_for_category(
                        category_label,
                        cashflow_role=cashflow_type,
                    ),
                ),
            )
            continue
        if not isinstance(raw_value, dict):
            continue

        typed_value = cast(dict[str, object], raw_value)
        raw_labels = typed_value.get("labels")
        if (
            isinstance(raw_labels, dict)
            or "deprecated_to" in typed_value
            or "status" in typed_value
            or "economic_role" in typed_value
            or "category_id" in typed_value
        ):
            label_object = (
                cast(dict[str, object], raw_labels) if isinstance(raw_labels, dict) else {}
            )
            category_label = (
                str(label_object.get("category")).strip()
                if isinstance(label_object.get("category"), str)
                and str(label_object.get("category")).strip()
                else (
                    str(typed_value.get("category")).strip()
                    if isinstance(typed_value.get("category"), str)
                    and str(typed_value.get("category")).strip()
                    else raw_key
                )
            )
            subcategory_label = (
                str(label_object.get("subcategory")).strip()
                if isinstance(label_object.get("subcategory"), str)
                and str(label_object.get("subcategory")).strip()
                else (
                    str(typed_value.get("subcategory")).strip()
                    if isinstance(typed_value.get("subcategory"), str)
                    and str(typed_value.get("subcategory")).strip()
                    else None
                )
            )
            cashflow_type = _normalize_cashflow_type(typed_value.get("cashflow_type"))
            economic_role = _normalize_economic_role(typed_value.get("economic_role"))
            decision_role = _normalize_decision_role(typed_value.get("decision_role"))
            taxonomy[_normalize_category_id(raw_key) or raw_key.casefold()] = TaxonomyCategory(
                name=category_label,
                subcategories=(),
                cashflow_type=cashflow_type,
                economic_role=economic_role
                or _legacy_economic_role_for_category(
                    category_label,
                    cashflow_role=cashflow_type,
                ),
                decision_role=decision_role
                or _legacy_decision_role_for_category(
                    category_label,
                    subcategory_label,
                    cashflow_role=cashflow_type,
                    economic_role=economic_role,
                ),
                category_label=category_label,
                subcategory_label=subcategory_label,
                deprecated_to=_normalize_category_id(typed_value.get("deprecated_to")),
                status=(
                    str(typed_value.get("status")).strip().casefold()
                    if isinstance(typed_value.get("status"), str)
                    and str(typed_value.get("status")).strip()
                    else "active"
                ),
            )
            continue

        raw_subcategories = typed_value.get("subcategories")
        subcategories = (
            tuple(str(item).strip() for item in raw_subcategories if str(item).strip())
            if isinstance(raw_subcategories, list)
            else ()
        )
        cashflow_type = _normalize_cashflow_type(typed_value.get("cashflow_type"))
        economic_role = _normalize_economic_role(typed_value.get("economic_role"))
        taxonomy[raw_key.casefold()] = TaxonomyCategory(
            name=raw_key,
            subcategories=subcategories,
            cashflow_type=cashflow_type,
            economic_role=economic_role
            or _legacy_economic_role_for_category(raw_key, cashflow_role=cashflow_type),
            decision_role=_normalize_decision_role(typed_value.get("decision_role"))
            or _legacy_decision_role_for_category(
                raw_key,
                None,
                cashflow_role=cashflow_type,
                economic_role=economic_role,
            ),
        )
    return taxonomy


def resolve_taxonomy_cashflow_type(
    category: str | None,
    *,
    rules: ClassificationRules,
) -> CashflowType | None:
    """Resolve a category's cashflow type from taxonomy metadata."""
    category_id = resolve_category_id_from_labels(category, None, rules=rules, prefer_active=True)
    if category_id is not None:
        direct = resolve_taxonomy_cashflow_type_for_category_id(category_id, rules=rules)
        if direct is not None:
            return direct

    normalized_category = (category or "").strip().casefold()
    matching_types = {
        entry.cashflow_type
        for entry in _taxonomy_entries_by_id(rules).values()
        if (entry.category_label or entry.name).strip().casefold() == normalized_category
        and entry.cashflow_type is not None
    }
    if len(matching_types) == 1:
        return next(iter(matching_types))
    return None


def _load_payload(path: Path) -> object:
    content = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(content)
    if suffix == ".json":
        return json.loads(content)
    # Backward-compatible fallback for unspecified extensions.
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return yaml.safe_load(content)


def load_classification_rules(path: Path) -> tuple[ClassificationRules, list[str]]:
    """Load categorization rules from YAML/JSON, falling back to bundled defaults."""
    if not path.exists():
        return _default_rules(), []
    try:
        payload = _load_payload(path)
        return _parse_rules_payload(payload), []
    except Exception as exc:
        return _default_rules(), [f"Failed to load classification rules from {path}: {exc}"]


def resolve_reporting_categories_for_dataframe(
    dataframe,
    *,
    rules: ClassificationRules,
):
    """Backfill durable and reporting category fields across the canonical dataframe."""
    if dataframe.empty:
        resolved = dataframe.copy()
        for column in ("category_id", "reporting_category_id", "category", "subcategory"):
            if column not in resolved.columns:
                resolved[column] = []
        return resolved

    resolved = dataframe.copy()
    category_ids: list[str | None] = []
    reporting_category_ids: list[str | None] = []
    categories: list[str] = []
    subcategories: list[str | None] = []

    for row in resolved.to_dict(orient="records"):
        existing_category_id = _normalize_category_id(row.get("category_id"))
        existing_category = (
            str(row.get("category")).strip()
            if row.get("category") is not None and str(row.get("category")).strip()
            else None
        )
        existing_subcategory = (
            str(row.get("subcategory")).strip()
            if row.get("subcategory") is not None and str(row.get("subcategory")).strip()
            else None
        )
        durable_category_id = existing_category_id or resolve_category_id_from_labels(
            existing_category,
            existing_subcategory,
            rules=rules,
            prefer_active=False,
        )
        reporting_category_id = resolve_reporting_category_id(durable_category_id, rules=rules)
        category_label, subcategory_label = resolve_taxonomy_labels(
            reporting_category_id or durable_category_id,
            rules=rules,
        )

        category_ids.append(durable_category_id)
        reporting_category_ids.append(reporting_category_id)
        categories.append(category_label or existing_category or "Uncategorized")
        subcategories.append(
            subcategory_label if category_label is not None else existing_subcategory
        )

    resolved["category_id"] = category_ids
    resolved["reporting_category_id"] = reporting_category_ids
    resolved["category"] = categories
    resolved["subcategory"] = subcategories
    return resolved


def load_override_store(path: Path) -> tuple[OverrideStore, list[str]]:
    """Load user categorization overrides from YAML/JSON."""
    if not path.exists():
        return OverrideStore(entries=()), []
    try:
        payload = _load_payload(path)
        if not isinstance(payload, dict):
            raise ValueError("override payload must be an object")
        payload_object = cast(dict[str, object], payload)
        raw_overrides = payload_object.get("overrides")
        if not isinstance(raw_overrides, list):
            raise ValueError("override payload must include a list field named 'overrides'")
        entries: list[OverrideEntry] = []
        for raw in raw_overrides:
            if not isinstance(raw, dict):
                continue
            raw_override = cast(dict[str, object], raw)
            fingerprint = normalize_description(str(raw_override.get("fingerprint", "")))
            if not fingerprint:
                continue
            category = str(raw_override.get("category", "")).strip()
            if not category:
                continue
            subcategory_raw = raw_override.get("subcategory")
            bank_raw = raw_override.get("bank")
            account_label_raw = raw_override.get("account_label")
            subcategory = (
                str(subcategory_raw).strip()
                if isinstance(subcategory_raw, str) and str(subcategory_raw).strip()
                else None
            )
            bank = (
                str(bank_raw).strip().upper()
                if isinstance(bank_raw, str) and str(bank_raw).strip()
                else None
            )
            account_label = (
                str(account_label_raw).strip().upper()
                if isinstance(account_label_raw, str) and str(account_label_raw).strip()
                else None
            )
            entries.append(
                OverrideEntry(
                    fingerprint=fingerprint,
                    category=category,
                    subcategory=subcategory,
                    bank=bank,
                    account_label=account_label,
                    hit_count=_to_int(raw_override.get("hit_count"), default=0),
                )
            )
        return OverrideStore(entries=tuple(entries)), []
    except Exception as exc:
        return OverrideStore(entries=()), [
            f"Failed to load classification overrides from {path}: {exc}"
        ]


def _rule_matches(rule: CategoryRule, tx: Transaction, normalized_description: str) -> bool:
    if rule.expense_only and tx.amount_native >= Decimal("0"):
        return False
    if rule.income_only and tx.amount_native <= Decimal("0"):
        return False
    if rule.banks and tx.bank.strip().upper() not in rule.banks:
        return False
    normalized_account = (tx.account_label or "").strip().upper()
    if rule.account_labels and normalized_account not in rule.account_labels:
        return False

    if rule.match_type == "contains":
        return any(pattern in normalized_description for pattern in rule.patterns)
    if rule.match_type == "exact":
        return any(pattern == normalized_description for pattern in rule.patterns)
    for pattern in rule.patterns:
        try:
            if re.search(pattern, normalized_description):
                return True
        except re.error:
            continue
    return False


def _rule_confidence(rule: CategoryRule) -> float:
    if rule.match_type == "exact":
        return 0.95
    if rule.match_type == "regex":
        return 0.85
    return 0.75


def resolve_matching_rule_economic_role(
    tx: Transaction,
    *,
    rules: ClassificationRules,
) -> EconomicRoleType | None:
    """Resolve a rule-level economic role override by matching the transaction."""
    normalized = normalize_description(tx.description)
    for rule in rules.rules:
        if rule.economic_role is not None and _rule_matches(rule, tx, normalized):
            return rule.economic_role
    return None


def resolve_matching_rule_decision_role(
    tx: Transaction,
    *,
    rules: ClassificationRules,
) -> DecisionRoleType | None:
    """Resolve a rule-level decision role override by matching the transaction."""
    normalized = normalize_description(tx.description)
    for rule in rules.rules:
        if rule.decision_role is not None and _rule_matches(rule, tx, normalized):
            return rule.decision_role
    return None


def build_classification_diagnostics(transactions: list[Transaction]) -> ClassificationDiagnostics:
    """Build summary diagnostics from already-classified transactions."""
    category_source_counts = Counter[str]()
    uncategorized_descriptions = Counter[str]()
    rule_hit_counts = Counter[str]()

    for tx in transactions:
        source = (tx.category_source or "").strip() or "unknown"
        category_source_counts[source] += 1
        if tx.category_rule_id:
            rule_hit_counts[tx.category_rule_id] += 1

        is_uncategorized = tx.category.strip().lower() == "uncategorized" or (
            (tx.category_source or "").strip().lower() == "uncategorized"
        )
        if is_uncategorized:
            normalized_description = normalize_description(tx.description) or "unknown"
            uncategorized_descriptions[normalized_description] += 1

    uncategorized_count = sum(uncategorized_descriptions.values())
    categorized_count = len(transactions) - uncategorized_count
    uncategorized_ratio = (uncategorized_count / len(transactions)) if transactions else 0.0
    top_uncategorized: list[UncategorizedDescriptionSummary] = [
        {"description": description, "count": count}
        for description, count in sorted(
            uncategorized_descriptions.items(),
            key=lambda item: (-item[1], item[0]),
        )[:10]
    ]
    top_rules: list[TopRuleHitSummary] = [
        {"rule_id": rule_id, "count": count}
        for rule_id, count in sorted(rule_hit_counts.items(), key=lambda item: (-item[1], item[0]))[
            :10
        ]
    ]
    return ClassificationDiagnostics(
        categorized_count=categorized_count,
        uncategorized_count=uncategorized_count,
        uncategorized_ratio=uncategorized_ratio,
        category_source_counts=dict(category_source_counts),
        top_uncategorized_descriptions=top_uncategorized,
        top_rules_by_hits=top_rules,
    )


def classify_transactions_with_diagnostics(
    transactions: list[Transaction],
    *,
    rules: ClassificationRules,
) -> tuple[list[Transaction], ClassificationDiagnostics]:
    """Classify transactions and return diagnostics for run summary."""
    classified: list[Transaction] = []

    for tx in transactions:
        normalized = normalize_description(tx.description)

        matched_rule: CategoryRule | None = None
        for rule in rules.rules:
            if _rule_matches(rule, tx, normalized):
                matched_rule = rule
                break

        if matched_rule is None:
            classified.append(
                replace(
                    tx,
                    category_id=None,
                    reporting_category_id=None,
                    category="Uncategorized",
                    subcategory=None,
                    category_confidence=0.0,
                    category_source="uncategorized",
                    category_rule_id=None,
                )
            )
            continue

        durable_category_id = matched_rule.category_id or resolve_category_id_from_labels(
            matched_rule.category,
            matched_rule.subcategory,
            rules=rules,
        )
        reporting_category_id = resolve_reporting_category_id(durable_category_id, rules=rules)
        category_label, subcategory_label = resolve_taxonomy_labels(
            reporting_category_id or durable_category_id,
            rules=rules,
        )
        classified.append(
            replace(
                tx,
                category_id=durable_category_id,
                reporting_category_id=reporting_category_id,
                category=category_label or matched_rule.category,
                subcategory=(
                    subcategory_label if category_label is not None else matched_rule.subcategory
                ),
                category_confidence=_rule_confidence(matched_rule),
                category_source="rule",
                category_rule_id=matched_rule.rule_id,
                economic_role=matched_rule.economic_role or tx.economic_role,
                decision_role=matched_rule.decision_role or tx.decision_role,
            )
        )
    diagnostics = build_classification_diagnostics(classified)
    return classified, diagnostics


def classify_transactions(
    transactions: list[Transaction],
    *,
    rules: ClassificationRules | None = None,
) -> list[Transaction]:
    """Return a new list of transactions with categories assigned."""
    active_rules = rules or _default_rules()
    classified, _ = classify_transactions_with_diagnostics(
        transactions,
        rules=active_rules,
    )
    return classified

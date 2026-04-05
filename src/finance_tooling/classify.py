"""Transaction classification rules, taxonomy semantics, and override handling."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import yaml

from finance_tooling.models import Transaction

MatchType = Literal["contains", "exact", "regex"]
CashflowType = Literal["in", "out", "transfer", "exclude"]
_VALID_CASHFLOW_TYPES = frozenset({"in", "out", "transfer", "exclude"})


def _legacy_cashflow_type_for_category(category: str) -> CashflowType | None:
    normalized = category.strip().casefold()
    if normalized == "income":
        return "in"
    if normalized == "transfers":
        return "transfer"
    if normalized == "non personal transactions":
        return "exclude"
    if normalized:
        return "out"
    return None


@dataclass(frozen=True)
class CategoryRule:
    """A single deterministic categorization rule."""

    rule_id: str
    priority: int
    category: str
    subcategory: str | None
    match_type: MatchType
    patterns: tuple[str, ...]
    expense_only: bool
    income_only: bool
    banks: tuple[str, ...]
    account_labels: tuple[str, ...]


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


@dataclass(frozen=True)
class ClassificationDiagnostics:
    """Summary statistics for a classification run."""

    categorized_count: int
    uncategorized_count: int
    uncategorized_ratio: float
    category_source_counts: dict[str, int]
    top_uncategorized_descriptions: list[dict[str, object]]
    top_rules_by_hits: list[dict[str, object]]


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
                category=category,
                subcategory=subcategory,
                match_type="contains",
                patterns=patterns,
                expense_only=False,
                income_only=False,
                banks=(),
                account_labels=(),
            )
        )
    default_taxonomy = {
        "groceries": TaxonomyCategory(
            name="Groceries",
            subcategories=("General",),
            cashflow_type="out",
        ),
        "dining": TaxonomyCategory(
            name="Dining",
            subcategories=("Restaurants",),
            cashflow_type="out",
        ),
        "transport": TaxonomyCategory(
            name="Transport",
            subcategories=("Mobility",),
            cashflow_type="out",
        ),
        "housing": TaxonomyCategory(
            name="Housing",
            subcategories=("Housing Costs",),
            cashflow_type="out",
        ),
        "shopping": TaxonomyCategory(
            name="Shopping",
            subcategories=("General",),
            cashflow_type="out",
        ),
        "income": TaxonomyCategory(
            name="Income",
            subcategories=("Salary", "Interest"),
            cashflow_type="in",
        ),
        "fees": TaxonomyCategory(
            name="Fees",
            subcategories=("Bank Fees",),
            cashflow_type="out",
        ),
        "transfers": TaxonomyCategory(
            name="Transfers",
            subcategories=("Internal/External",),
            cashflow_type="transfer",
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
    if normalized in _VALID_CASHFLOW_TYPES:
        return cast(CashflowType, normalized)
    return None


def _parse_taxonomy(raw_taxonomy: object) -> dict[str, TaxonomyCategory]:
    if not isinstance(raw_taxonomy, dict):
        return {}

    taxonomy: dict[str, TaxonomyCategory] = {}
    for raw_category, raw_value in cast(dict[object, object], raw_taxonomy).items():
        category = str(raw_category).strip()
        if not category:
            continue

        subcategories: tuple[str, ...] = ()
        cashflow_type: CashflowType | None = None
        if isinstance(raw_value, list):
            subcategories = tuple(str(item).strip() for item in raw_value if str(item).strip())
            cashflow_type = _legacy_cashflow_type_for_category(category)
        elif isinstance(raw_value, dict):
            typed_value = cast(dict[str, object], raw_value)
            raw_subcategories = typed_value.get("subcategories")
            if isinstance(raw_subcategories, list):
                subcategories = tuple(
                    str(item).strip() for item in raw_subcategories if str(item).strip()
                )
            cashflow_type = _normalize_cashflow_type(typed_value.get("cashflow_type"))
        else:
            continue

        taxonomy[category.casefold()] = TaxonomyCategory(
            name=category,
            subcategories=subcategories,
            cashflow_type=cashflow_type,
        )
    return taxonomy


def resolve_taxonomy_cashflow_type(
    category: str | None,
    *,
    rules: ClassificationRules,
) -> CashflowType | None:
    """Resolve a category's cashflow type from taxonomy metadata."""
    if category is None:
        return None
    normalized = category.strip().casefold()
    if not normalized:
        return None
    entry = rules.taxonomy.get(normalized)
    if entry is None:
        return None
    return entry.cashflow_type


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
    top_uncategorized = [
        {"description": description, "count": count}
        for description, count in sorted(
            uncategorized_descriptions.items(),
            key=lambda item: (-item[1], item[0]),
        )[:10]
    ]
    top_rules = [
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
                    category="Uncategorized",
                    subcategory=None,
                    category_confidence=0.0,
                    category_source="uncategorized",
                    category_rule_id=None,
                )
            )
            continue

        classified.append(
            replace(
                tx,
                category=matched_rule.category,
                subcategory=matched_rule.subcategory,
                category_confidence=_rule_confidence(matched_rule),
                category_source="rule",
                category_rule_id=matched_rule.rule_id,
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

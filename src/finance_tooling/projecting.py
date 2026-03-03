"""Project assignment rules and override handling for dashboard analytics."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import pandas as pd
import yaml

from finance_tooling.classify import normalize_description
from finance_tooling.models import Transaction

MatchType = Literal["contains", "exact", "regex"]


@dataclass(frozen=True)
class ProjectRule:
    """Single deterministic project assignment rule."""

    rule_id: str
    priority: int
    project: str
    match_type: MatchType
    patterns: tuple[str, ...]
    expense_only: bool
    income_only: bool
    banks: tuple[str, ...]
    account_labels: tuple[str, ...]
    categories: tuple[str, ...]
    project_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectOverride:
    """Manual project assignment override keyed by normalized fingerprint."""

    fingerprint: str
    project: str
    bank: str | None
    account_label: str | None
    project_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectConfig:
    """Loaded project assignment configuration."""

    fallback_project: str
    rules: tuple[ProjectRule, ...]
    overrides: tuple[ProjectOverride, ...]


def _default_project_config() -> ProjectConfig:
    return ProjectConfig(fallback_project="Unassigned", rules=(), overrides=())


def _to_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


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


def _normalize_upper(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized or None


def _normalize_lower(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_project_tags(
    tags_value: object,
    *,
    legacy_project: object,
) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(tags_value, list):
        values.extend(str(item).strip() for item in tags_value if str(item).strip())
    elif isinstance(tags_value, str) and tags_value.strip():
        text = tags_value.strip()
        if "|" in text:
            values.extend(part.strip() for part in text.split("|"))
        else:
            values.append(text)

    if not values and isinstance(legacy_project, str) and legacy_project.strip():
        values.append(legacy_project.strip())

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        marker = value.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        normalized.append(value)
    return tuple(normalized)


def _parse_project_payload(payload: object) -> ProjectConfig:
    if not isinstance(payload, dict):
        raise ValueError("project config payload must be an object")
    data = cast(dict[str, object], payload)

    defaults = data.get("defaults")
    fallback_project = "Unassigned"
    if isinstance(defaults, dict):
        defaults_obj = cast(dict[str, object], defaults)
        maybe_fallback = defaults_obj.get("fallback_project")
        if isinstance(maybe_fallback, str) and maybe_fallback.strip():
            fallback_project = maybe_fallback.strip()

    raw_rules = data.get("rules")
    if raw_rules is not None and not isinstance(raw_rules, list):
        raise ValueError("project config field `rules` must be a list")
    raw_overrides = data.get("overrides")
    if raw_overrides is not None and not isinstance(raw_overrides, list):
        raise ValueError("project config field `overrides` must be a list")

    parsed_rules: list[ProjectRule] = []
    for index, raw_rule in enumerate(raw_rules or []):
        if not isinstance(raw_rule, dict):
            continue
        rule = cast(dict[str, object], raw_rule)
        project_tags = _normalize_project_tags(
            rule.get("project_tags"),
            legacy_project=rule.get("project"),
        )
        if not project_tags:
            continue
        project = project_tags[0]
        match_type_raw = rule.get("match_type", rule.get("match"))
        match_type = (
            str(match_type_raw).strip().lower()
            if isinstance(match_type_raw, str) and str(match_type_raw).strip()
            else "contains"
        )
        if match_type not in {"contains", "exact", "regex"}:
            continue
        typed_match_type = cast(MatchType, match_type)
        patterns_raw = rule.get("patterns")
        if not isinstance(patterns_raw, list):
            continue
        patterns = tuple(str(item).strip().lower() for item in patterns_raw if str(item).strip())
        if not patterns:
            continue
        rule_id_raw = rule.get("id", rule.get("rule_id"))
        banks_raw = rule.get("banks")
        account_labels_raw = rule.get("account_labels")
        categories_raw = rule.get("categories")
        banks = banks_raw if isinstance(banks_raw, list) else []
        account_labels = account_labels_raw if isinstance(account_labels_raw, list) else []
        categories = categories_raw if isinstance(categories_raw, list) else []
        parsed_rules.append(
            ProjectRule(
                rule_id=(
                    str(rule_id_raw).strip()
                    if isinstance(rule_id_raw, str) and str(rule_id_raw).strip()
                    else f"project_rule_{index + 1}"
                ),
                priority=_to_int(rule.get("priority"), default=0),
                project=project,
                project_tags=project_tags,
                match_type=typed_match_type,
                patterns=patterns,
                expense_only=bool(rule.get("expense_only")),
                income_only=bool(rule.get("income_only")),
                banks=tuple(
                    normalized
                    for item in banks
                    if (normalized := _normalize_upper(item)) is not None
                ),
                account_labels=tuple(
                    normalized
                    for item in account_labels
                    if (normalized := _normalize_upper(item)) is not None
                ),
                categories=tuple(
                    normalized
                    for item in categories
                    if (normalized := _normalize_lower(item)) is not None
                ),
            )
        )
    parsed_rules.sort(key=lambda item: (-item.priority, item.rule_id))

    parsed_overrides: list[ProjectOverride] = []
    for raw_override in raw_overrides or []:
        if not isinstance(raw_override, dict):
            continue
        override = cast(dict[str, object], raw_override)
        fingerprint = normalize_description(str(override.get("fingerprint", "")))
        project_tags = _normalize_project_tags(
            override.get("project_tags"),
            legacy_project=override.get("project"),
        )
        if not fingerprint or not project_tags:
            continue
        parsed_overrides.append(
            ProjectOverride(
                fingerprint=fingerprint,
                project=project_tags[0],
                project_tags=project_tags,
                bank=_normalize_upper(override.get("bank")),
                account_label=_normalize_upper(override.get("account_label")),
            )
        )

    return ProjectConfig(
        fallback_project=fallback_project,
        rules=tuple(parsed_rules),
        overrides=tuple(parsed_overrides),
    )


def load_project_config(path: Path) -> tuple[ProjectConfig, list[str]]:
    """Load project assignment rules/overrides from YAML/JSON."""
    if not path.exists():
        return _default_project_config(), []
    try:
        payload = _load_payload(path)
        return _parse_project_payload(payload), []
    except Exception as exc:
        return _default_project_config(), [f"Failed to load project config from {path}: {exc}"]


def _parse_amount(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _rule_matches(
    rule: ProjectRule,
    *,
    normalized_description: str,
    amount_native: Decimal,
    bank: str,
    account_label: str | None,
    category: str,
) -> bool:
    if rule.expense_only and amount_native >= Decimal("0"):
        return False
    if rule.income_only and amount_native <= Decimal("0"):
        return False
    if rule.banks and bank not in rule.banks:
        return False
    if rule.account_labels and (account_label or "") not in rule.account_labels:
        return False
    if rule.categories and category not in rule.categories:
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


def assign_projects_to_dataframe(
    dataframe: pd.DataFrame,
    *,
    config: ProjectConfig,
) -> pd.DataFrame:
    """Assign project names to a transaction dataframe and return a copy."""
    assigned = dataframe.copy()
    if assigned.empty:
        assigned["project"] = []
        return assigned

    projects: list[str] = []
    for row in assigned.to_dict(orient="records"):
        normalized_description = normalize_description(str(row.get("description", "")))
        bank = _normalize_upper(row.get("bank")) or "UNKNOWN"
        account_label = _normalize_upper(row.get("account_label"))
        category = _normalize_lower(row.get("category")) or "uncategorized"
        amount_native = _parse_amount(row.get("amount_native"))

        matched_project: str | None = None
        for override in config.overrides:
            if override.fingerprint != normalized_description:
                continue
            if override.bank is not None and override.bank != bank:
                continue
            if override.account_label is not None and override.account_label != account_label:
                continue
            matched_project = override.project
            break

        if matched_project is None:
            for rule in config.rules:
                if _rule_matches(
                    rule,
                    normalized_description=normalized_description,
                    amount_native=amount_native,
                    bank=bank,
                    account_label=account_label,
                    category=category,
                ):
                    matched_project = rule.project
                    break

        projects.append(matched_project or config.fallback_project)

    assigned["project"] = projects
    return assigned


def assign_projects_to_transactions(
    transactions: list[Transaction],
    config: ProjectConfig,
) -> list[Transaction]:
    """Assign project tags to transactions with override-first precedence."""
    projected: list[Transaction] = []
    for tx in transactions:
        normalized_description = normalize_description(tx.description)
        bank = tx.bank.strip().upper() or "UNKNOWN"
        account_label = (tx.account_label or "").strip().upper() or None
        category = tx.category.strip().lower() if tx.category.strip() else "uncategorized"
        amount_native = tx.amount_native

        matched_project: str | None = None
        matched_tags: tuple[str, ...] | None = None
        matched_source: str | None = None

        for override in config.overrides:
            if override.fingerprint != normalized_description:
                continue
            if override.bank is not None and override.bank != bank:
                continue
            if override.account_label is not None and override.account_label != account_label:
                continue
            matched_project = override.project
            matched_tags = override.project_tags or (override.project,)
            matched_source = "project_override"
            break

        if matched_project is None:
            for rule in config.rules:
                if _rule_matches(
                    rule,
                    normalized_description=normalized_description,
                    amount_native=amount_native,
                    bank=bank,
                    account_label=account_label,
                    category=category,
                ):
                    matched_project = rule.project
                    matched_tags = rule.project_tags or (rule.project,)
                    matched_source = "project_rule"
                    break

        if matched_project is None:
            projected.append(
                replace(
                    tx,
                    project=tx.project,
                    project_tags=tx.project_tags,
                    project_source=tx.project_source or "project_fallback",
                )
            )
            continue

        projected.append(
            replace(
                tx,
                project=matched_project,
                project_tags=matched_tags or (matched_project,),
                project_source=matched_source,
            )
        )
    return projected

"""Account boundary inference for canonical finance reporting."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import yaml

from finance_tooling.classify import normalize_description
from finance_tooling.models import Transaction

MatchType = Literal["contains", "exact", "regex"]
AccountType = Literal["internal", "external", "unknown"]
_VALID_ACCOUNT_TYPES = frozenset({"internal", "external", "unknown"})


@dataclass(frozen=True)
class InternalAccount:
    """Registry entry for an internal/personal account."""

    account_ref: str
    bank: str
    account_labels: tuple[str, ...]

    def matches(self, *, bank: str, account_label: str | None) -> bool:
        if self.bank != bank.strip().upper():
            return False
        normalized_account_label = (account_label or "").strip().upper()
        if self.account_labels and normalized_account_label not in self.account_labels:
            return False
        return True


@dataclass(frozen=True)
class CounterpartyRule:
    """Ordered rule to infer counterparty-side account details."""

    rule_id: str
    priority: int
    match_type: MatchType
    patterns: tuple[str, ...]
    expense_only: bool
    income_only: bool
    banks: tuple[str, ...]
    account_labels: tuple[str, ...]
    categories: tuple[str, ...]
    from_account_ref: str | None
    to_account_ref: str | None
    from_account_type: AccountType | None
    to_account_type: AccountType | None


@dataclass(frozen=True)
class AccountInferenceConfig:
    """Loaded account registry and counterparty rules."""

    internal_accounts: tuple[InternalAccount, ...]
    counterparty_rules: tuple[CounterpartyRule, ...]


def _default_account_inference_config() -> AccountInferenceConfig:
    return AccountInferenceConfig(internal_accounts=(), counterparty_rules=())


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


def _normalize_account_ref(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_account_type(value: object) -> AccountType | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in _VALID_ACCOUNT_TYPES:
        return cast(AccountType, normalized)
    return None


def _normalize_match_type(value: object) -> MatchType | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in {"contains", "exact", "regex"}:
        return cast(MatchType, normalized)
    return None


def _match_pattern(
    *,
    match_type: MatchType,
    patterns: tuple[str, ...],
    description: str,
) -> bool:
    if not patterns:
        return False
    if match_type == "contains":
        return any(pattern in description for pattern in patterns)
    if match_type == "exact":
        return description in patterns
    return any(re.search(pattern, description) is not None for pattern in patterns)


def _parse_internal_accounts(raw_accounts: object) -> tuple[InternalAccount, ...]:
    if not isinstance(raw_accounts, list):
        return ()

    parsed: list[InternalAccount] = []
    for raw_entry in raw_accounts:
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, object], raw_entry)
        account_ref = _normalize_account_ref(entry.get("account_ref", entry.get("id")))
        bank = _normalize_upper(entry.get("bank"))
        if account_ref is None or bank is None:
            continue
        raw_account_labels = entry.get("account_labels")
        account_labels = raw_account_labels if isinstance(raw_account_labels, list) else []
        parsed.append(
            InternalAccount(
                account_ref=account_ref,
                bank=bank,
                account_labels=tuple(
                    normalized
                    for item in account_labels
                    if (normalized := _normalize_upper(item)) is not None
                ),
            )
        )
    return tuple(parsed)


def _parse_counterparty_rules(raw_rules: object) -> tuple[CounterpartyRule, ...]:
    if not isinstance(raw_rules, list):
        return ()

    parsed: list[CounterpartyRule] = []
    for index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, dict):
            continue
        rule = cast(dict[str, object], raw_rule)
        match_type = _normalize_match_type(rule.get("match_type", rule.get("match")))
        patterns_raw = rule.get("patterns")
        patterns = (
            tuple(str(item).strip().lower() for item in patterns_raw if str(item).strip())
            if isinstance(patterns_raw, list)
            else ()
        )
        if match_type is None or not patterns:
            continue

        banks_raw = rule.get("banks")
        account_labels_raw = rule.get("account_labels")
        categories_raw = rule.get("categories")
        parsed.append(
            CounterpartyRule(
                rule_id=(
                    str(rule.get("id")).strip()
                    if isinstance(rule.get("id"), str) and str(rule.get("id")).strip()
                    else f"account_rule_{index + 1}"
                ),
                priority=int(rule.get("priority", 0)),
                match_type=match_type,
                patterns=patterns,
                expense_only=bool(rule.get("expense_only")),
                income_only=bool(rule.get("income_only")),
                banks=tuple(
                    normalized
                    for item in (banks_raw if isinstance(banks_raw, list) else [])
                    if (normalized := _normalize_upper(item)) is not None
                ),
                account_labels=tuple(
                    normalized
                    for item in (account_labels_raw if isinstance(account_labels_raw, list) else [])
                    if (normalized := _normalize_upper(item)) is not None
                ),
                categories=tuple(
                    normalized
                    for item in (categories_raw if isinstance(categories_raw, list) else [])
                    if (normalized := _normalize_lower(item)) is not None
                ),
                from_account_ref=_normalize_account_ref(rule.get("from_account_ref")),
                to_account_ref=_normalize_account_ref(rule.get("to_account_ref")),
                from_account_type=_normalize_account_type(rule.get("from_account_type")),
                to_account_type=_normalize_account_type(rule.get("to_account_type")),
            )
        )
    parsed.sort(key=lambda item: (-item.priority, item.rule_id))
    return tuple(parsed)


def load_account_inference_config(path: Path | None) -> tuple[AccountInferenceConfig, list[str]]:
    """Load account registry and counterparty inference rules."""
    if path is None or not path.exists():
        return _default_account_inference_config(), []
    try:
        payload = _load_payload(path)
        if not isinstance(payload, dict):
            raise ValueError("account inference payload must be an object")
        payload_object = cast(dict[str, object], payload)
        return (
            AccountInferenceConfig(
                internal_accounts=_parse_internal_accounts(payload_object.get("internal_accounts")),
                counterparty_rules=_parse_counterparty_rules(
                    payload_object.get("counterparty_rules")
                ),
            ),
            [],
        )
    except Exception as exc:
        return (
            _default_account_inference_config(),
            [f"Failed to load account rules from {path}: {exc}"],
        )


def _find_internal_statement_account(
    transaction: Transaction,
    config: AccountInferenceConfig,
) -> InternalAccount | None:
    for account in config.internal_accounts:
        if account.matches(bank=transaction.bank, account_label=transaction.account_label):
            return account
    return None


def _rule_matches(transaction: Transaction, rule: CounterpartyRule) -> bool:
    description = normalize_description(transaction.description)
    if not _match_pattern(
        match_type=rule.match_type,
        patterns=rule.patterns,
        description=description,
    ):
        return False

    amount = transaction.amount_native
    if rule.expense_only and amount >= Decimal("0"):
        return False
    if rule.income_only and amount <= Decimal("0"):
        return False

    bank = transaction.bank.strip().upper()
    if rule.banks and bank not in rule.banks:
        return False

    account_label = (transaction.account_label or "").strip().upper()
    if rule.account_labels and account_label not in rule.account_labels:
        return False

    category = (transaction.category or "").strip().casefold()
    if rule.categories and category not in rule.categories:
        return False

    return True


def infer_accounts_for_transactions(
    transactions: list[Transaction],
    *,
    config: AccountInferenceConfig,
) -> list[Transaction]:
    """Infer from/to account sides without changing cashflow semantics."""
    if not transactions:
        return []

    updated: list[Transaction] = []
    for tx in transactions:
        from_account_ref = tx.from_account_ref
        to_account_ref = tx.to_account_ref
        from_account_type = tx.from_account_type
        to_account_type = tx.to_account_type
        account_inference_source = tx.account_inference_source

        statement_account = _find_internal_statement_account(tx, config)
        amount = tx.amount_native
        if statement_account is not None:
            if amount < Decimal("0"):
                from_account_ref = from_account_ref or statement_account.account_ref
                from_account_type = from_account_type or "internal"
            elif amount > Decimal("0"):
                to_account_ref = to_account_ref or statement_account.account_ref
                to_account_type = to_account_type or "internal"
            if account_inference_source is None and (from_account_type or to_account_type):
                account_inference_source = "statement_account"

        matching_rule = next(
            (rule for rule in config.counterparty_rules if _rule_matches(tx, rule)),
            None,
        )
        if matching_rule is not None:
            if matching_rule.from_account_ref is not None and from_account_ref is None:
                from_account_ref = matching_rule.from_account_ref
            if matching_rule.to_account_ref is not None and to_account_ref is None:
                to_account_ref = matching_rule.to_account_ref
            if matching_rule.from_account_type is not None and from_account_type is None:
                from_account_type = matching_rule.from_account_type
            if matching_rule.to_account_type is not None and to_account_type is None:
                to_account_type = matching_rule.to_account_type
            if (
                account_inference_source != "transaction_override"
                and any(
                    (
                        matching_rule.from_account_ref is not None,
                        matching_rule.to_account_ref is not None,
                        matching_rule.from_account_type is not None,
                        matching_rule.to_account_type is not None,
                    )
                )
            ):
                account_inference_source = "account_rule"

        from_account_type = from_account_type or "unknown"
        to_account_type = to_account_type or "unknown"
        account_inference_source = account_inference_source or "unknown"

        updated.append(
            replace(
                tx,
                from_account_ref=from_account_ref,
                to_account_ref=to_account_ref,
                from_account_type=from_account_type,
                to_account_type=to_account_type,
                account_inference_source=account_inference_source,
            )
        )

    return updated

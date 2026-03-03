"""Transaction-level overrides for category and project assignment."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

import yaml

from finance_tooling.classify import normalize_description
from finance_tooling.models import Transaction
from finance_tooling.store import compute_transaction_id


@dataclass(frozen=True)
class TransactionOverrideEntry:
    """Single transaction-level override entry."""

    override_id: str | None
    transaction_id: str | None
    fingerprint: str | None
    booking_date: date | None
    amount_native: Decimal | None
    currency: str | None
    bank: str | None
    account_label: str | None
    category: str | None
    set_category: bool
    subcategory: str | None
    set_subcategory: bool
    project: str | None
    set_project: bool
    project_tags: tuple[str, ...]
    set_project_tags: bool

    def matches(
        self,
        *,
        transaction: Transaction,
        transaction_id: str,
        fingerprint: str,
    ) -> bool:
        """Return True when this entry targets the provided transaction."""
        if self.transaction_id is not None and self.transaction_id != transaction_id:
            return False
        if self.fingerprint is not None and self.fingerprint != fingerprint:
            return False
        if self.booking_date is not None and self.booking_date != transaction.booking_date:
            return False
        if self.amount_native is not None and self.amount_native != transaction.amount_native:
            return False
        if self.currency is not None and self.currency != transaction.currency.strip().upper():
            return False
        if self.bank is not None and self.bank != transaction.bank.strip().upper():
            return False
        normalized_account = (transaction.account_label or "").strip().upper() or None
        if self.account_label is not None and self.account_label != normalized_account:
            return False
        return True


@dataclass(frozen=True)
class TransactionOverrideStore:
    """Container for transaction-level override entries."""

    entries: tuple[TransactionOverrideEntry, ...]


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


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _optional_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return date.fromisoformat(stripped)
    except ValueError:
        return None


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        value = stripped
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _normalized_project_tags(value: object) -> tuple[str, ...]:
    raw_values: list[str] = []
    if isinstance(value, list):
        raw_values.extend(str(item).strip() for item in value if str(item).strip())
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if "|" in text:
            raw_values.extend(part.strip() for part in text.split("|"))
        else:
            raw_values.append(text)
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        marker = raw.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        normalized.append(raw)
    return tuple(normalized)


def _parse_override_entry(raw_override: dict[str, object]) -> TransactionOverrideEntry | None:
    raw_match = raw_override.get("match")
    match_object = cast(dict[str, object], raw_match) if isinstance(raw_match, dict) else {}
    match_values: dict[str, object] = {**raw_override, **match_object}

    transaction_id = _optional_str(match_values.get("transaction_id"))
    fingerprint_raw = match_values.get("fingerprint", match_values.get("description_fingerprint"))
    fingerprint = (
        normalize_description(str(fingerprint_raw)) if fingerprint_raw is not None else None
    )
    if fingerprint == "":
        fingerprint = None

    booking_date = _optional_date(match_values.get("booking_date"))
    amount_native = _optional_decimal(match_values.get("amount_native"))
    currency_raw = _optional_str(match_values.get("currency"))
    bank_raw = _optional_str(match_values.get("bank"))
    account_label_raw = _optional_str(match_values.get("account_label"))

    selector_count = sum(
        (
            transaction_id is not None,
            fingerprint is not None,
            booking_date is not None,
            amount_native is not None,
            currency_raw is not None,
            bank_raw is not None,
            account_label_raw is not None,
        )
    )
    if selector_count == 0:
        return None

    set_category = "category" in raw_override
    set_subcategory = "subcategory" in raw_override
    set_project = "project" in raw_override
    set_project_tags = "project_tags" in raw_override
    if not any((set_category, set_subcategory, set_project, set_project_tags)):
        return None

    category_value = _optional_str(raw_override.get("category")) if set_category else None
    subcategory_value = _optional_str(raw_override.get("subcategory")) if set_subcategory else None
    project_value = _optional_str(raw_override.get("project")) if set_project else None
    project_tags = (
        _normalized_project_tags(raw_override.get("project_tags")) if set_project_tags else ()
    )

    return TransactionOverrideEntry(
        override_id=_optional_str(raw_override.get("id")),
        transaction_id=transaction_id,
        fingerprint=fingerprint,
        booking_date=booking_date,
        amount_native=amount_native,
        currency=currency_raw.upper() if currency_raw is not None else None,
        bank=bank_raw.upper() if bank_raw is not None else None,
        account_label=account_label_raw.upper() if account_label_raw is not None else None,
        category=category_value,
        set_category=set_category,
        subcategory=subcategory_value,
        set_subcategory=set_subcategory,
        project=project_value,
        set_project=set_project,
        project_tags=project_tags,
        set_project_tags=set_project_tags,
    )


def load_transaction_override_store(path: Path) -> tuple[TransactionOverrideStore, list[str]]:
    """Load transaction-level overrides from YAML/JSON configuration."""
    if not path.exists():
        return TransactionOverrideStore(entries=()), []

    try:
        payload = _load_payload(path)
        if not isinstance(payload, dict):
            raise ValueError("transaction override payload must be an object")
        payload_object = cast(dict[str, object], payload)
        raw_overrides = payload_object.get("overrides")
        if raw_overrides is None:
            return TransactionOverrideStore(entries=()), []
        if not isinstance(raw_overrides, list):
            raise ValueError("transaction override payload field 'overrides' must be a list")

        entries: list[TransactionOverrideEntry] = []
        for raw in raw_overrides:
            if not isinstance(raw, dict):
                continue
            parsed = _parse_override_entry(cast(dict[str, object], raw))
            if parsed is None:
                continue
            entries.append(parsed)
        return TransactionOverrideStore(entries=tuple(entries)), []
    except Exception as exc:
        return TransactionOverrideStore(entries=()), [
            f"Failed to load transaction overrides from {path}: {exc}"
        ]


def apply_transaction_overrides(
    transactions: list[Transaction],
    store: TransactionOverrideStore,
) -> list[Transaction]:
    """Apply transaction-level overrides with last-match-wins semantics."""
    if not store.entries:
        return list(transactions)

    updated: list[Transaction] = []
    for tx in transactions:
        tx_id = compute_transaction_id(tx)
        fingerprint = normalize_description(tx.description)
        current = tx
        for entry in store.entries:
            if not entry.matches(
                transaction=current,
                transaction_id=tx_id,
                fingerprint=fingerprint,
            ):
                continue

            category = current.category
            subcategory = current.subcategory
            category_confidence = current.category_confidence
            category_source = current.category_source
            category_rule_id = current.category_rule_id
            project = current.project
            project_tags = current.project_tags
            project_source = current.project_source

            category_override_applied = False
            if entry.set_category:
                category = entry.category or "Uncategorized"
                category_override_applied = True
            if entry.set_subcategory:
                subcategory = entry.subcategory
                category_override_applied = True
            if category_override_applied:
                category_confidence = 1.0
                category_source = "transaction_override"
                category_rule_id = None

            project_override_applied = False
            if entry.set_project:
                project = entry.project
                project_override_applied = True
            if entry.set_project_tags:
                project_tags = entry.project_tags
                if not entry.set_project:
                    project = entry.project_tags[0] if entry.project_tags else None
                project_override_applied = True
            if project_override_applied:
                project_source = "transaction_override"

            current = replace(
                current,
                category=category,
                subcategory=subcategory,
                category_confidence=category_confidence,
                category_source=category_source,
                category_rule_id=category_rule_id,
                project=project,
                project_tags=project_tags,
                project_source=project_source,
            )
        updated.append(current)

    return updated

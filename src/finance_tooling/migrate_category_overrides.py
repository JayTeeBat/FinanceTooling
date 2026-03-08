"""One-off migration from legacy category overrides to exact-match rules."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from finance_tooling.classify import OverrideEntry, load_override_store


@dataclass(frozen=True)
class CategoryOverrideMigrationResult:
    """Summary of a category-override migration run."""

    migrated_count: int
    skipped_count: int
    conflict_count: int
    rules_path: Path
    report_path: Path
    backup_path: Path | None


def _load_rules_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "rules": []}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {"version": 1, "rules": []}
    if not isinstance(payload, dict):
        raise ValueError(f"Rules payload must be an object: {path}")
    rules = payload.get("rules")
    if rules is None:
        payload["rules"] = []
    elif not isinstance(rules, list):
        raise ValueError(f"Rules payload must contain a list field named 'rules': {path}")
    return dict(payload)


def _default_backup_path(path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{path.name}.{timestamp}.bak")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "entry"


def _rule_key(rule: dict[str, object]) -> tuple[str, str | None, str | None]:
    patterns = rule.get("patterns")
    if not isinstance(patterns, list) or len(patterns) != 1:
        return ("", None, None)
    fingerprint = str(patterns[0]).strip().lower()
    banks = rule.get("banks")
    account_labels = rule.get("account_labels")
    bank = (
        str(banks[0]).strip().upper()
        if isinstance(banks, list) and len(banks) == 1 and str(banks[0]).strip()
        else None
    )
    account_label = (
        str(account_labels[0]).strip().upper()
        if isinstance(account_labels, list)
        and len(account_labels) == 1
        and str(account_labels[0]).strip()
        else None
    )
    return (fingerprint, bank, account_label)


def _entry_key(entry: OverrideEntry) -> tuple[str, str | None, str | None]:
    return (entry.fingerprint, entry.bank, entry.account_label)


def _migrated_rule(entry: OverrideEntry, *, index: int) -> dict[str, object]:
    bank_slug = _slugify(entry.bank or "any_bank")
    fingerprint_slug = _slugify(entry.fingerprint)
    rule: dict[str, object] = {
        "id": f"migrated.override.{bank_slug}.{fingerprint_slug}.{index}",
        "priority": 100000,
        "category": entry.category,
        "subcategory": entry.subcategory,
        "match": "exact",
        "patterns": [entry.fingerprint],
    }
    if entry.bank:
        rule["banks"] = [entry.bank]
    if entry.account_label:
        rule["account_labels"] = [entry.account_label]
    return rule


def migrate_category_overrides_to_rules(
    *,
    overrides_path: Path,
    rules_path: Path,
    report_path: Path,
    backup: bool = True,
    backup_path: Path | None = None,
) -> CategoryOverrideMigrationResult:
    """Convert legacy category overrides into exact-match rules."""
    store, warnings = load_override_store(overrides_path)
    if warnings:
        joined = "; ".join(warnings)
        raise ValueError(f"Failed to load category overrides: {joined}")

    payload = _load_rules_payload(rules_path)
    existing_rules = payload.get("rules")
    assert isinstance(existing_rules, list)

    existing_keys: dict[tuple[str, str | None, str | None], dict[str, object]] = {}
    for raw_rule in existing_rules:
        if not isinstance(raw_rule, dict):
            continue
        rule = {str(key): value for key, value in raw_rule.items()}
        existing_keys[_rule_key(rule)] = rule

    migrated_rules: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []

    for index, entry in enumerate(store.entries, start=1):
        key = _entry_key(entry)
        existing = existing_keys.get(key)
        if existing is not None:
            if (
                existing.get("category") == entry.category
                and existing.get("subcategory") == entry.subcategory
            ):
                skipped.append(
                    {
                        "reason": "already_present",
                        "fingerprint": entry.fingerprint,
                        "bank": entry.bank,
                        "account_label": entry.account_label,
                    }
                )
                continue
            conflicts.append(
                {
                    "reason": "conflicting_existing_rule",
                    "fingerprint": entry.fingerprint,
                    "bank": entry.bank,
                    "account_label": entry.account_label,
                    "override_category": entry.category,
                    "override_subcategory": entry.subcategory,
                    "rule_category": existing.get("category"),
                    "rule_subcategory": existing.get("subcategory"),
                }
            )
            continue
        migrated_rules.append(_migrated_rule(entry, index=index))

    created_backup: Path | None = None
    if backup and rules_path.exists():
        created_backup = backup_path or _default_backup_path(rules_path)
        created_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rules_path, created_backup)

    payload["rules"] = [*migrated_rules, *existing_rules]
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )

    report = {
        "migrated_count": len(migrated_rules),
        "skipped_count": len(skipped),
        "conflict_count": len(conflicts),
        "migrated_rules": migrated_rules,
        "skipped": skipped,
        "conflicts": conflicts,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return CategoryOverrideMigrationResult(
        migrated_count=len(migrated_rules),
        skipped_count=len(skipped),
        conflict_count=len(conflicts),
        rules_path=rules_path,
        report_path=report_path,
        backup_path=created_backup,
    )

from __future__ import annotations

from datetime import date
from typing import cast

import pandas as pd

from finance_tooling.audits.categorization import (
    build_categorization_audit,
    render_categorization_audit_markdown,
)
from finance_tooling.categorization.classify import ClassificationRules, TaxonomyCategory
from finance_tooling.categorization.transaction_overrides import (
    TransactionOverrideEntry,
    TransactionOverrideStore,
)


def _override_entry(transaction_id: str, category: str) -> TransactionOverrideEntry:
    return TransactionOverrideEntry(
        override_id=None,
        transaction_id=transaction_id,
        fingerprint=None,
        booking_date=None,
        amount_native=None,
        currency=None,
        bank=None,
        account_label=None,
        category=category,
        set_category=True,
        subcategory=None,
        set_subcategory=False,
        project=None,
        set_project=False,
        project_tags=(),
        set_project_tags=False,
    )


def test_build_categorization_audit_flags_review_state_and_taxonomy_drift() -> None:
    canonical = pd.DataFrame(
        [
            {
                "transaction_id": "tx-1",
                "booking_date": date(2024, 1, 3),
                "description": "Employer Salary",
                "category": "Income",
                "subcategory": "Salary",
                "category_source": "rule",
                "category_rule_id": "income.salary",
            },
            {
                "transaction_id": "tx-2",
                "booking_date": date(2024, 2, 4),
                "description": "Legacy mortgage",
                "category": "House",
                "subcategory": "Mortgage",
                "category_source": "transaction_override",
                "category_rule_id": None,
            },
            {
                "transaction_id": "tx-3",
                "booking_date": date(2025, 2, 4),
                "description": "Mystery expense",
                "category": "Uncategorized",
                "subcategory": None,
                "category_source": "uncategorized",
                "category_rule_id": None,
            },
        ]
    )
    rules = ClassificationRules(
        rules=(),
        taxonomy={
            "income": TaxonomyCategory(
                name="Income",
                subcategories=("Salary",),
                cashflow_type="in",
            ),
            "housing": TaxonomyCategory(
                name="Housing", subcategories=("Mortgage",), cashflow_type="out"
            ),
        },
    )
    overrides = TransactionOverrideStore(entries=(_override_entry("tx-2", "House"),))
    review_state = pd.DataFrame(
        [
            {"transaction_id": "tx-1", "reviewed": False},
            {"transaction_id": "tx-2", "reviewed": False},
        ]
    )

    audit = build_categorization_audit(
        canonical_transactions=canonical,
        classification_rules=rules,
        transaction_override_store=overrides,
        review_state=review_state,
    )

    assert audit.override_integrity["matched_entry_count"] == 1
    assert audit.override_integrity["unmatched_entry_count"] == 0
    assert audit.review_state_integrity["review_state_rows"] == 2
    assert audit.review_state_integrity["reviewed_true_count"] == 0
    missing_categories = audit.taxonomy_drift["missing_categories"]
    assert isinstance(missing_categories, list)
    typed_missing_categories = [cast(dict[str, object], row) for row in missing_categories]
    assert [row["category"] for row in typed_missing_categories] == ["House"]
    assert any(
        finding.classification == "likely lost manual state"
        and "review-state" in finding.title.lower()
        for finding in audit.findings
    )
    assert any(
        finding.classification == "likely taxonomy drift" and "Legacy categories" in finding.title
        for finding in audit.findings
    )


def test_build_categorization_audit_detects_unmatched_overrides() -> None:
    canonical = pd.DataFrame(
        [
            {
                "transaction_id": "tx-1",
                "booking_date": date(2024, 1, 3),
                "description": "Salary",
                "category": "Income",
                "subcategory": "Salary",
                "category_source": "rule",
                "category_rule_id": "income.salary",
            }
        ]
    )
    rules = ClassificationRules(
        rules=(),
        taxonomy={
            "income": TaxonomyCategory(name="Income", subcategories=("Salary",), cashflow_type="in")
        },
    )
    overrides = TransactionOverrideStore(entries=(_override_entry("tx-missing", "Shopping"),))
    review_state = pd.DataFrame(columns=["transaction_id", "reviewed"])

    audit = build_categorization_audit(
        canonical_transactions=canonical,
        classification_rules=rules,
        transaction_override_store=overrides,
        review_state=review_state,
    )

    assert audit.override_integrity["unmatched_entry_count"] == 1
    assert audit.override_integrity["sample_unmatched_transaction_ids"] == ["tx-missing"]
    assert any(
        finding.classification == "likely lost manual state"
        and "Unmatched transaction overrides" in finding.title
        for finding in audit.findings
    )


def test_render_categorization_audit_markdown_includes_sections() -> None:
    canonical = pd.DataFrame(
        [
            {
                "transaction_id": "tx-1",
                "booking_date": date(2024, 1, 3),
                "description": "Salary",
                "category": "Income",
                "subcategory": "Salary",
                "category_source": "rule",
                "category_rule_id": "income.salary",
            }
        ]
    )
    rules = ClassificationRules(
        rules=(),
        taxonomy={
            "income": TaxonomyCategory(name="Income", subcategories=("Salary",), cashflow_type="in")
        },
    )
    overrides = TransactionOverrideStore(entries=())
    review_state = pd.DataFrame(columns=["transaction_id", "reviewed"])

    audit = build_categorization_audit(
        canonical_transactions=canonical,
        classification_rules=rules,
        transaction_override_store=overrides,
        review_state=review_state,
    )

    report = render_categorization_audit_markdown(audit)

    assert "# Categorization Integrity Audit" in report
    assert "## Override Integrity" in report
    assert "## Review-State Integrity" in report
    assert "## Taxonomy Drift" in report
    assert "## Coverage Drift" in report
    assert "## Rule-Layer Consistency" in report
    assert "## Remediation Backlog" in report

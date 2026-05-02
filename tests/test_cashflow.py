from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.categorization.account_inference import (
    AccountInferenceConfig,
    CounterpartyRule,
)
from finance_tooling.categorization.classify import (
    CategoryRule,
    ClassificationRules,
    TaxonomyCategory,
)
from finance_tooling.categorization.transaction_overrides import load_transaction_override_store
from finance_tooling.core.models import Transaction
from finance_tooling.core.store import _frame_from_transactions
from finance_tooling.reporting.cashflow import (
    build_cashflow_yoy_summary,
    resolve_cashflow_types_for_dataframe,
    resolve_decision_roles_for_dataframe,
    resolve_economic_roles_for_dataframe,
)
from finance_tooling.workflow.types import CashflowYearRow


def _rules() -> ClassificationRules:
    return ClassificationRules(
        rules=(),
        taxonomy={
            "income": TaxonomyCategory(
                name="Income",
                subcategories=("Salary",),
                cashflow_type="in",
            ),
            "shopping": TaxonomyCategory(
                name="Shopping",
                subcategories=("General Retail",),
                cashflow_type="out",
            ),
            "transfers": TaxonomyCategory(
                name="Transfers",
                subcategories=("Bank Transfer",),
                cashflow_type="transfer",
            ),
            "non personal transactions": TaxonomyCategory(
                name="Non Personal Transactions",
                subcategories=(),
                cashflow_type="exclude",
            ),
        },
    )


def _dataframe_for(tx: Transaction):
    return _frame_from_transactions([tx])


def _account_config(*, employer_patterns: tuple[str, ...] = ()) -> AccountInferenceConfig:
    return AccountInferenceConfig(
        internal_accounts=(),
        counterparty_rules=(
            (
                CounterpartyRule(
                    rule_id="employer",
                    priority=100,
                    match_type="contains",
                    patterns=employer_patterns,
                    expense_only=False,
                    income_only=True,
                    banks=(),
                    account_labels=(),
                    categories=(),
                    is_employer=True,
                    from_account_ref=None,
                    to_account_ref=None,
                    from_account_type="external",
                    to_account_type=None,
                ),
            )
            if employer_patterns
            else ()
        ),
    )


def test_resolve_cashflow_types_internal_to_internal_becomes_transfer(tmp_path: Path) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Move to savings",
        amount_native=Decimal("-250.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Shopping",
        from_account_type="internal",
        to_account_type="internal",
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text("overrides: []\n", encoding="utf-8")
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "transfer"
    assert result.account_transfer_override_count == 1
    assert result.account_transfer_conflict_count == 0


def test_resolve_cashflow_types_explicit_override_beats_internal_transfer(tmp_path: Path) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Move to savings",
        amount_native=Decimal("-250.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Shopping",
        from_account_type="internal",
        to_account_type="internal",
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text(
        "\n".join(
            [
                "overrides:",
                "  - match:",
                "      booking_date: '2026-01-03'",
                "      amount_native: -250.00",
                "      currency: EUR",
                "      bank: HSBC",
                "    cashflow_type: out",
            ]
        ),
        encoding="utf-8",
    )
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "out"
    assert result.account_transfer_override_count == 0
    assert result.account_transfer_conflict_count == 0


def test_build_cashflow_yoy_summary_excludes_exclude_rows_from_metrics() -> None:
    transactions = [
        Transaction(
            booking_date=date(2025, 1, 3),
            description="Salary",
            amount_native=Decimal("1000.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Income",
            cashflow_type="in",
            amount_eur=Decimal("1000.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 10),
            description="Groceries",
            amount_native=Decimal("-200.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Shopping",
            cashflow_type="out",
            amount_eur=Decimal("-200.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 11),
            description="Pass-through spend",
            amount_native=Decimal("-300.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Non Personal Transactions",
            cashflow_type="exclude",
            amount_eur=Decimal("-300.00"),
        ),
    ]

    dataframe = _frame_from_transactions(transactions)
    summary = build_cashflow_yoy_summary(dataframe)
    years: list[CashflowYearRow] = summary["years"]

    assert len(years) == 1
    assert years[0]["year"] == 2025
    assert years[0]["income"] == 1000.0
    assert years[0]["expenses"] == 200.0
    assert years[0]["net_cashflow"] == 800.0


def test_build_cashflow_yoy_summary_includes_transfer_and_uncategorized_volumes() -> None:
    transactions = [
        Transaction(
            booking_date=date(2025, 1, 3),
            description="Salary",
            amount_native=Decimal("1000.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Income",
            cashflow_type="in",
            amount_eur=Decimal("1000.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 10),
            description="Groceries",
            amount_native=Decimal("-200.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Shopping",
            cashflow_type="out",
            amount_eur=Decimal("-200.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 11),
            description="Transfer to savings",
            amount_native=Decimal("-300.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Transfers",
            cashflow_type="transfer",
            amount_eur=Decimal("-300.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 12),
            description="Mystery debit",
            amount_native=Decimal("-75.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Uncategorized",
            cashflow_type="out",
            amount_eur=Decimal("-75.00"),
        ),
    ]

    summary = build_cashflow_yoy_summary(_frame_from_transactions(transactions))
    years: list[CashflowYearRow] = summary["years"]

    assert years[0]["transfer_volume"] == 300.0
    assert years[0]["uncategorized_volume"] == 75.0


def test_resolve_cashflow_types_falls_back_to_sign_for_positive_unmapped_rows(
    tmp_path: Path,
) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Misc credit",
        amount_native=Decimal("125.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Work",
        amount_eur=Decimal("125.00"),
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text("overrides: []\n", encoding="utf-8")
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "in"
    assert result.unknown_count == 0


def test_resolve_cashflow_types_uses_sign_for_positive_income_category_rows(
    tmp_path: Path,
) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Salary credit",
        amount_native=Decimal("125.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Income",
        subcategory="Salary",
        amount_eur=Decimal("125.00"),
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text("overrides: []\n", encoding="utf-8")
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "in"


def test_resolve_cashflow_types_uses_sign_for_positive_refund_rows(
    tmp_path: Path,
) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Health insurance reimbursement",
        amount_native=Decimal("42.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Refunds",
        subcategory="Unmapped Refund",
        amount_eur=Decimal("42.00"),
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text("overrides: []\n", encoding="utf-8")
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "in"


def test_resolve_cashflow_types_falls_back_to_sign_for_negative_unmapped_rows(
    tmp_path: Path,
) -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Misc debit",
        amount_native=Decimal("-25.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="House",
        amount_eur=Decimal("-25.00"),
    )
    override_path = tmp_path / "transaction_overrides.yaml"
    override_path.write_text("overrides: []\n", encoding="utf-8")
    override_store, warnings = load_transaction_override_store(override_path)

    result = resolve_cashflow_types_for_dataframe(
        _dataframe_for(tx),
        classification_rules=_rules(),
        transaction_override_store=override_store,
    )

    assert warnings == []
    assert result.dataframe.loc[0, "cashflow_type"] == "out"
    assert result.unknown_count == 0


def test_resolve_economic_roles_marks_employer_as_income() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Acme salary payment",
        amount_native=Decimal("1250.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Uncategorized",
        cashflow_type="in",
        amount_eur=Decimal("1250.00"),
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(employer_patterns=("acme",)),
    )

    assert result.dataframe.loc[0, "economic_role"] == "income"
    assert result.role_counts == {
        "income": 1,
        "fixed_expense": 0,
        "variable_expense": 0,
        "expense": 0,
        "transfer": 0,
        "exclude": 0,
    }


def test_resolve_economic_roles_marks_interest_as_income() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Monthly interest",
        amount_native=Decimal("5.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Income",
        subcategory="Interest",
        cashflow_type="in",
        amount_eur=Decimal("5.00"),
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(),
    )

    assert result.dataframe.loc[0, "economic_role"] == "income"


def test_resolve_economic_roles_marks_salary_subcategory_as_income() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Employer payment",
        amount_native=Decimal("1250.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Income",
        subcategory="Salary",
        cashflow_type="in",
        amount_eur=Decimal("1250.00"),
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(),
    )

    assert result.dataframe.loc[0, "economic_role"] == "income"


def test_resolve_economic_roles_marks_legacy_interest_bucket_income_by_description() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="*INTER.BRUTS31/12/24",
        amount_native=Decimal("5.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Income",
        subcategory="Refunds & Interest",
        cashflow_type="in",
        amount_eur=Decimal("5.00"),
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(),
    )

    assert result.dataframe.loc[0, "economic_role"] == "income"


def test_resolve_economic_roles_keeps_legacy_refund_bucket_as_expense_when_not_interest() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Refund from Amz*amazon.co.uk",
        amount_native=Decimal("11.85"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Income",
        subcategory="Refunds & Interest",
        cashflow_type="in",
        amount_eur=Decimal("11.85"),
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(),
    )

    assert result.dataframe.loc[0, "economic_role"] == "expense"


def test_resolve_economic_roles_keeps_positive_health_refund_as_expense() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Health insurance reimbursement",
        amount_native=Decimal("11.85"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Refunds",
        subcategory="Unmapped Refund",
        cashflow_type="in",
        amount_eur=Decimal("11.85"),
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(),
        classification_rules=_rules(),
    )

    assert result.dataframe.loc[0, "economic_role"] == "expense"


def test_resolve_economic_roles_uses_rule_level_fixed_expense_override() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Spotify monthly subscription",
        amount_native=Decimal("-11.99"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Leisure",
        subcategory="Entertainment",
        category_rule_id="leisure.subscription",
        cashflow_type="out",
        amount_eur=Decimal("-11.99"),
    )
    rules = ClassificationRules(
        rules=(
            CategoryRule(
                rule_id="leisure.subscription",
                priority=100,
                category="Leisure",
                subcategory="Entertainment",
                match_type="contains",
                patterns=("spotify",),
                economic_role="fixed_expense",
            ),
        ),
        taxonomy={
            "leisure.entertainment": TaxonomyCategory(
                name="Leisure",
                subcategories=(),
                cashflow_type="out",
                economic_role="variable_expense",
                category_label="Leisure",
                subcategory_label="Entertainment",
            )
        },
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(),
        classification_rules=rules,
    )

    assert result.dataframe.loc[0, "economic_role"] == "fixed_expense"


def test_resolve_economic_roles_matches_rule_override_without_category_rule_id() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Card 06/01/26 Audible FR",
        amount_native=Decimal("-11.99"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Leisure",
        subcategory="Other Leisure",
        cashflow_type="out",
        amount_eur=Decimal("-11.99"),
    )
    rules = ClassificationRules(
        rules=(
            CategoryRule(
                rule_id="leisure.subscription",
                priority=100,
                category_id="leisure.entertainment",
                category="Leisure",
                subcategory="Entertainment",
                match_type="contains",
                patterns=("audible",),
                economic_role="fixed_expense",
                expense_only=True,
            ),
        ),
        taxonomy={
            "leisure.other_leisure": TaxonomyCategory(
                name="Leisure",
                subcategories=(),
                cashflow_type="out",
                economic_role="variable_expense",
                category_label="Leisure",
                subcategory_label="Other Leisure",
            )
        },
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(),
        classification_rules=rules,
    )

    assert result.dataframe.loc[0, "economic_role"] == "fixed_expense"


def test_resolve_economic_roles_defaults_unmapped_outgoing_rows_to_variable_expense() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Unknown merchant",
        amount_native=Decimal("-25.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Uncategorized",
        cashflow_type="out",
        amount_eur=Decimal("-25.00"),
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(),
        classification_rules=ClassificationRules(rules=(), taxonomy={}),
    )

    assert result.dataframe.loc[0, "economic_role"] == "variable_expense"


def test_resolve_economic_roles_marks_transfer_and_exclude_before_income() -> None:
    transactions = [
        Transaction(
            booking_date=date(2026, 1, 3),
            description="Acme salary payment",
            amount_native=Decimal("1250.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Income",
            subcategory="Salary",
            cashflow_type="transfer",
            amount_eur=Decimal("1250.00"),
        ),
        Transaction(
            booking_date=date(2026, 1, 4),
            description="Acme salary payment",
            amount_native=Decimal("1250.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Income",
            subcategory="Interest",
            cashflow_type="exclude",
            amount_eur=Decimal("1250.00"),
        ),
    ]

    result = resolve_economic_roles_for_dataframe(
        _frame_from_transactions(transactions),
        account_inference_config=_account_config(employer_patterns=("acme",)),
    )

    assert list(result.dataframe["economic_role"]) == ["transfer", "exclude"]


def test_resolve_decision_roles_uses_taxonomy_and_transfer_defaults() -> None:
    transactions = [
        Transaction(
            booking_date=date(2025, 1, 3),
            description="Groceries",
            amount_native=Decimal("-100.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Groceries",
            cashflow_type="out",
            economic_role="variable_expense",
        ),
        Transaction(
            booking_date=date(2025, 1, 3),
            description="Salary",
            amount_native=Decimal("1250.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Income",
            cashflow_type="in",
            economic_role="income",
        ),
        Transaction(
            booking_date=date(2025, 1, 4),
            description="Savings transfer",
            amount_native=Decimal("-200.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Transfers",
            subcategory="Savings Transfer",
            cashflow_type="transfer",
            economic_role="transfer",
        ),
    ]

    dataframe = _frame_from_transactions(transactions)
    rules = ClassificationRules(
        rules=(),
        taxonomy={
            "transfers.savings_transfer": TaxonomyCategory(
                name="Transfers",
                subcategories=(),
                cashflow_type="transfer",
                decision_role="savings",
                category_label="Transfers",
                subcategory_label="Savings Transfer",
            )
        },
    )
    result = resolve_decision_roles_for_dataframe(dataframe, classification_rules=rules)

    assert list(result.dataframe["decision_role"]) == [
        "essential",
        "not_applicable",
        "not_applicable",
    ]


def test_resolve_decision_roles_marks_excluded_rows_as_not_applicable() -> None:
    tx = Transaction(
        booking_date=date(2025, 1, 7),
        description="Pass-through adjustment",
        amount_native=Decimal("-42.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Non Personal Transactions",
        cashflow_type="exclude",
        economic_role="exclude",
        amount_eur=Decimal("-42.00"),
    )

    result = resolve_decision_roles_for_dataframe(_frame_from_transactions([tx]))

    assert result.dataframe.loc[0, "decision_role"] == "not_applicable"


def test_resolve_decision_roles_marks_transfer_rows_as_not_applicable() -> None:
    tx = Transaction(
        booking_date=date(2025, 1, 8),
        description="Mortgage transfer",
        amount_native=Decimal("-250.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Transfers",
        subcategory="Mortgage payment",
        cashflow_type="transfer",
        economic_role="transfer",
        amount_eur=Decimal("-250.00"),
    )

    result = resolve_decision_roles_for_dataframe(_frame_from_transactions([tx]))

    assert result.dataframe.loc[0, "decision_role"] == "not_applicable"


def test_resolve_economic_roles_falls_back_to_expense_for_non_employer_positive_inflow() -> None:
    tx = Transaction(
        booking_date=date(2026, 1, 3),
        description="Refund from merchant",
        amount_native=Decimal("25.00"),
        currency="EUR",
        source_file=Path("stmt.pdf"),
        bank="HSBC",
        parser="hsbc",
        category="Refunds",
        cashflow_type="in",
        amount_eur=Decimal("25.00"),
    )

    result = resolve_economic_roles_for_dataframe(
        _dataframe_for(tx),
        account_inference_config=_account_config(),
    )

    assert result.dataframe.loc[0, "economic_role"] == "expense"


def test_cashflow_summary_treats_all_expense_roles_as_expenses() -> None:
    transactions = [
        Transaction(
            booking_date=date(2025, 1, 3),
            description="Salary",
            amount_native=Decimal("1000.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Income",
            cashflow_type="in",
            economic_role="income",
            amount_eur=Decimal("1000.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 4),
            description="Rent",
            amount_native=Decimal("-400.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Housing",
            cashflow_type="out",
            economic_role="fixed_expense",
            amount_eur=Decimal("-400.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 5),
            description="Groceries",
            amount_native=Decimal("-150.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Groceries",
            cashflow_type="out",
            economic_role="variable_expense",
            amount_eur=Decimal("-150.00"),
        ),
        Transaction(
            booking_date=date(2025, 1, 6),
            description="Legacy refund bucket",
            amount_native=Decimal("-25.00"),
            currency="EUR",
            source_file=Path("stmt.pdf"),
            bank="HSBC",
            parser="hsbc",
            category="Refunds",
            cashflow_type="out",
            economic_role="expense",
            amount_eur=Decimal("-25.00"),
        ),
    ]

    summary = build_cashflow_yoy_summary(
        _frame_from_transactions(transactions),
        as_of_date=date(2026, 1, 1),
    )

    assert summary["years"][0]["expenses"] == 575.0
    assert summary["years"][0]["net_cashflow"] == 425.0

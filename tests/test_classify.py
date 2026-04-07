from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.classify import (
    CategoryRule,
    ClassificationRules,
    classify_transactions,
    classify_transactions_with_diagnostics,
    load_classification_rules,
    load_override_store,
    normalize_description,
    resolve_taxonomy_cashflow_type,
)
from finance_tooling.models import Transaction


def test_classify_transactions_assigns_keyword_category() -> None:
    tx = Transaction(
        booking_date=date(2026, 2, 1),
        description="CARD PAYMENT UBER TRIP",
        amount_native=Decimal("-17.50"),
        currency="USD",
        source_file=Path("stmt.pdf"),
        bank="Revolut",
        parser="revolut",
    )

    classified = classify_transactions([tx])

    assert classified[0].category == "Transport"
    assert classified[0].subcategory == "Mobility"
    assert classified[0].category_source == "rule"
    assert classified[0].category_rule_id == "transport.mobility"
    assert classified[0].amount_native == Decimal("-17.50")


def test_classify_transactions_with_diagnostics_tracks_uncategorized() -> None:
    tx = Transaction(
        booking_date=date(2026, 2, 1),
        description="UNKNOWN MERCHANT 123456",
        amount_native=Decimal("-17.50"),
        currency="USD",
        source_file=Path("stmt.pdf"),
        bank="Revolut",
        parser="revolut",
    )

    classified, diagnostics = classify_transactions_with_diagnostics(
        [tx],
        rules=ClassificationRules(rules=()),
    )

    assert classified[0].category == "Uncategorized"
    assert classified[0].category_source == "uncategorized"
    assert diagnostics.categorized_count == 0
    assert diagnostics.uncategorized_count == 1
    assert diagnostics.uncategorized_ratio == 1.0
    assert diagnostics.category_source_counts["uncategorized"] == 1
    assert diagnostics.top_uncategorized_descriptions == [
        {"description": "unknown merchant", "count": 1}
    ]


def test_classify_transactions_prefers_rule_over_no_match() -> None:
    tx = Transaction(
        booking_date=date(2026, 2, 1),
        description="PAYPAL PAYMENT",
        amount_native=Decimal("-10.00"),
        currency="USD",
        source_file=Path("stmt.pdf"),
        bank="Revolut",
        parser="revolut",
    )
    rules = ClassificationRules(
        rules=(
            CategoryRule(
                rule_id="transfers.paypal",
                priority=100,
                category="Transfers",
                subcategory="Wallet Transfer",
                match_type="exact",
                patterns=(normalize_description("PAYPAL PAYMENT"),),
                expense_only=False,
                income_only=False,
                banks=(),
                account_labels=(),
            ),
        )
    )

    classified = classify_transactions([tx], rules=rules)

    assert classified[0].category == "Transfers"
    assert classified[0].subcategory == "Wallet Transfer"
    assert classified[0].category_source == "rule"


def test_load_classification_rules_supports_yaml_schema_aliases(tmp_path: Path) -> None:
    rules_path = tmp_path / "category_rules.yaml"
    rules_path.write_text(
        "\n".join(
            [
                "version: 1",
                "taxonomy:",
                "  Transfers:",
                "    cashflow_type: transfer",
                "    subcategories:",
                "      - FX Exchange",
                "rules:",
                "  - id: transfers.fx.exchange_to_gbp",
                "    priority: 200",
                "    category: Transfers",
                "    subcategory: FX Exchange",
                "    match: contains",
                "    patterns:",
                "      - exchanged to gbp",
                "      - exchange to gbp",
            ]
        ),
        encoding="utf-8",
    )

    rules, warnings = load_classification_rules(rules_path)

    assert warnings == []
    assert len(rules.rules) == 1
    assert rules.rules[0].rule_id == "transfers.fx.exchange_to_gbp"
    assert rules.rules[0].match_type == "contains"
    assert rules.rules[0].patterns == ("exchanged to gbp", "exchange to gbp")
    assert resolve_taxonomy_cashflow_type("Transfers", rules=rules) == "transfer"


def test_load_classification_rules_normalizes_contains_and_exact_patterns(tmp_path: Path) -> None:
    rules_path = tmp_path / "category_rules.yaml"
    rules_path.write_text(
        "\n".join(
            [
                "version: 1",
                "rules:",
                "  - id: housing.mortgage",
                "    priority: 200",
                "    category: Housing",
                "    subcategory: Mortgage",
                "    match: contains",
                "    patterns:",
                "      - PRELEVEMENT DE ECHEANCE PRET REF",
                "  - id: transfers.paypal",
                "    priority: 100",
                "    category: Transfers",
                "    subcategory: Wallet Transfer",
                "    match: exact",
                "    patterns:",
                "      - PAYPAL PAYMENT REF : 123456",
            ]
        ),
        encoding="utf-8",
    )

    rules, warnings = load_classification_rules(rules_path)

    assert warnings == []
    assert rules.rules[0].patterns == (normalize_description("PRELEVEMENT DE ECHEANCE PRET REF"),)
    assert rules.rules[1].patterns == (normalize_description("PAYPAL PAYMENT REF : 123456"),)


def test_load_override_store_supports_yaml_for_migration_use(tmp_path: Path) -> None:
    overrides_path = tmp_path / "category_overrides.yaml"
    overrides_path.write_text(
        "\n".join(
            [
                "version: 1",
                "overrides:",
                "  - fingerprint: paypal payment",
                "    category: Transfers",
                "    subcategory: Wallet Transfer",
                "    bank: revolut",
                "    account_label: null",
                "    hit_count: 2",
            ]
        ),
        encoding="utf-8",
    )

    overrides, warnings = load_override_store(overrides_path)

    assert warnings == []
    assert len(overrides.entries) == 1
    assert overrides.entries[0].fingerprint == "paypal payment"
    assert overrides.entries[0].category == "Transfers"
    assert overrides.entries[0].subcategory == "Wallet Transfer"
    assert overrides.entries[0].bank == "REVOLUT"
    assert overrides.entries[0].hit_count == 2


def test_resolve_taxonomy_cashflow_type_returns_none_when_missing() -> None:
    assert resolve_taxonomy_cashflow_type("Shopping", rules=ClassificationRules(rules=())) is None


def test_default_rules_include_exclude_categories() -> None:
    rules, warnings = load_classification_rules(Path("/tmp/does-not-exist-category-rules.yaml"))

    assert warnings == []
    assert resolve_taxonomy_cashflow_type("Non Personal Transactions", rules=rules) == "exclude"
    assert resolve_taxonomy_cashflow_type("Pass-through", rules=rules) == "exclude"


def test_load_classification_rules_infers_cashflow_type_from_legacy_taxonomy_lists(
    tmp_path: Path,
) -> None:
    rules_path = tmp_path / "category_rules.yaml"
    rules_path.write_text(
        "\n".join(
            [
                "version: 1",
                "taxonomy:",
                "  Income:",
                "    - Salary",
                "  Transfers:",
                "    - Bank Transfer",
                "  Shopping:",
                "    - General Retail",
                "rules: []",
            ]
        ),
        encoding="utf-8",
    )

    rules, warnings = load_classification_rules(rules_path)

    assert warnings == []
    assert resolve_taxonomy_cashflow_type("Income", rules=rules) == "in"
    assert resolve_taxonomy_cashflow_type("Transfers", rules=rules) == "transfer"
    assert resolve_taxonomy_cashflow_type("Shopping", rules=rules) == "out"


def test_repo_example_config_categorizes_generic_example_fingerprints() -> None:
    rules, warnings = load_classification_rules(Path("config/category_rules.yaml"))

    assert warnings == []

    cases = [
        ("ACME PAYROLL APRIL", "income.salary", "Income", "Salary"),
        ("Benefits Office Payment", "income.benefits", "Income", "Benefits"),
        (
            "Freelance Client Ltd Invoice 42",
            "income.business_income",
            "Income",
            "Business Income",
        ),
        (
            "Internal Account Transfer to Savings",
            "transfers.account_transfer",
            "Transfers",
            "Account Transfer",
        ),
        (
            "Broker Funding Transfer",
            "transfers.investment_transfer",
            "Transfers",
            "Investment Transfer",
        ),
        ("City Energy Monthly Bill", "utilities.energy_water", "Utilities", "Energy & Water"),
        (
            "Home Broadband Direct Debit",
            "utilities.telecom_internet",
            "Utilities",
            "Telecom & Internet",
        ),
        ("Neighborhood Market", "groceries.food_at_home", "Groceries", "Food at Home"),
        ("Pizza Place Friday Night", "dining.dining_out", "Dining", "Dining Out"),
        ("Online Marketplace Order", "shopping.marketplace", "Shopping", "Marketplace"),
        ("Clothing Store Purchase", "shopping.clothing", "Shopping", "Clothing"),
        ("City Metro Reload", "transport.public_transport", "Transport", "Public Transport"),
        ("Auto Payment Annual Service", "transport.car", "Transport", "Car"),
        ("Rent Agency August", "housing.rent", "Housing", "Rent"),
        (
            "Renovation Contractor Deposit",
            "housing.home_improvements",
            "Housing",
            "Home Improvements",
        ),
        ("Property Manager Monthly Fee", "housing.home_services", "Housing", "Home Services"),
        ("School Tuition Term 1", "family.education", "Family", "Education"),
        ("Tax Free Childcare Credit", "family.childcare", "Family", "Childcare"),
        ("Revenue Agency Rebate", "taxes.other_taxes", "Taxes", "Other Taxes"),
        ("Car Insurance Renewal", "insurance.property_vehicle", "Insurance", "Property & Vehicle"),
        ("Streaming Service Subscription", "leisure.entertainment", "Leisure", "Entertainment"),
        (
            "Home Insurance Premium",
            "insurance.property_vehicle",
            "Insurance",
            "Property & Vehicle",
        ),
    ]

    transactions = []
    for description, category_id, _category, _subcategory in cases:
        transactions.append(
            Transaction(
                booking_date=date(2026, 2, 1),
                description=description,
                amount_native=(
                    Decimal("17.50")
                    if (
                        category_id.startswith("income.")
                        or description == "Benefits Office Payment"
                        or description == "Tax Free Childcare Credit"
                        or description == "Revenue Agency Rebate"
                    )
                    else Decimal("-17.50")
                ),
                currency="EUR",
                source_file=Path("stmt.pdf"),
                bank="Boursobank",
                parser="boursobank",
            )
        )

    classified = classify_transactions(transactions, rules=rules)

    paired_results = zip(classified, cases, strict=True)
    for tx, (_description, category_id, category, subcategory) in paired_results:
        assert tx.category_id == category_id
        assert tx.reporting_category_id == category_id
        assert tx.category == category
        assert tx.subcategory == subcategory
        assert tx.category_source == "rule"

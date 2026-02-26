from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.classify import (
    CategoryRule,
    ClassificationRules,
    OverrideEntry,
    OverrideStore,
    classify_transactions,
    classify_transactions_with_diagnostics,
    load_classification_rules,
    load_override_store,
    normalize_description,
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


def test_classify_transactions_override_takes_precedence() -> None:
    tx = Transaction(
        booking_date=date(2026, 2, 1),
        description="CARD PAYMENT UBER TRIP",
        amount_native=Decimal("-17.50"),
        currency="USD",
        source_file=Path("stmt.pdf"),
        bank="Revolut",
        parser="revolut",
    )
    rules = ClassificationRules(
        rules=(
            CategoryRule(
                rule_id="transport.uber",
                priority=10,
                category="Transport",
                subcategory="Ride-hailing",
                match_type="contains",
                patterns=("uber",),
                expense_only=False,
                income_only=False,
                banks=(),
                account_labels=(),
            ),
        )
    )
    overrides = OverrideStore(
        entries=(
            OverrideEntry(
                fingerprint=normalize_description("CARD PAYMENT UBER TRIP"),
                category="Transfers",
                subcategory="Manual override",
                bank="REVOLUT",
                account_label=None,
                hit_count=0,
            ),
        )
    )

    classified = classify_transactions([tx], rules=rules, overrides=overrides)

    assert classified[0].category == "Transfers"
    assert classified[0].subcategory == "Manual override"
    assert classified[0].category_source == "override"
    assert classified[0].category_confidence == 1.0
    assert classified[0].category_rule_id is None


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
        overrides=OverrideStore(entries=()),
    )

    assert classified[0].category == "Uncategorized"
    assert classified[0].category_source == "fallback"
    assert diagnostics.categorized_count == 0
    assert diagnostics.uncategorized_count == 1
    assert diagnostics.uncategorized_ratio == 1.0
    assert diagnostics.category_source_counts["fallback"] == 1
    assert diagnostics.top_uncategorized_descriptions == [
        {"description": "unknown merchant", "count": 1}
    ]


def test_load_classification_rules_supports_yaml_schema_aliases(tmp_path: Path) -> None:
    rules_path = tmp_path / "category_rules.yaml"
    rules_path.write_text(
        "\n".join(
            [
                "version: 1",
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


def test_load_override_store_supports_yaml(tmp_path: Path) -> None:
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

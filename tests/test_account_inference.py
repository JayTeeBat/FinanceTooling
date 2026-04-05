from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.account_inference import (
    AccountInferenceConfig,
    CounterpartyRule,
    InternalAccount,
    infer_accounts_for_transactions,
    load_account_inference_config,
)
from finance_tooling.models import Transaction


def _tx(description: str, *, amount: str) -> Transaction:
    return Transaction(
        booking_date=date(2026, 2, 1),
        description=description,
        amount_native=Decimal(amount),
        currency="EUR",
        source_file=Path("/tmp/statement.pdf"),
        bank="REVOLUT",
        parser="revolut",
        category="Uncategorized",
        account_label="Main",
    )


def test_load_account_inference_config_supports_internal_accounts_and_rules(tmp_path: Path) -> None:
    path = tmp_path / "account_rules.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "internal_accounts:",
                "  - account_ref: revolut_main",
                "    bank: REVOLUT",
                "    account_labels: [MAIN]",
                "counterparty_rules:",
                "  - id: salary",
                "    priority: 100",
                "    match: contains",
                "    income_only: true",
                "    patterns: [salary]",
                "    from_account_type: external",
            ]
        ),
        encoding="utf-8",
    )

    config, warnings = load_account_inference_config(path)

    assert warnings == []
    assert config.internal_accounts[0].account_ref == "revolut_main"
    assert config.counterparty_rules[0].rule_id == "salary"
    assert config.counterparty_rules[0].from_account_type == "external"


def test_infer_accounts_assigns_statement_side_and_counterparty_rule() -> None:
    config = AccountInferenceConfig(
        internal_accounts=(
            InternalAccount(account_ref="revolut_main", bank="REVOLUT", account_labels=("MAIN",)),
        ),
        counterparty_rules=(
            CounterpartyRule(
                rule_id="salary",
                priority=100,
                match_type="contains",
                patterns=("salary",),
                expense_only=False,
                income_only=True,
                banks=(),
                account_labels=(),
                categories=(),
                from_account_ref=None,
                to_account_ref=None,
                from_account_type="external",
                to_account_type=None,
            ),
        ),
    )

    inferred = infer_accounts_for_transactions(
        [_tx("Salary payment", amount="1000.00")],
        config=config,
    )

    assert inferred[0].from_account_type == "external"
    assert inferred[0].to_account_type == "internal"
    assert inferred[0].to_account_ref == "revolut_main"
    assert inferred[0].account_inference_source == "account_rule"


def test_infer_accounts_keeps_override_seed_values() -> None:
    config = AccountInferenceConfig(
        internal_accounts=(
            InternalAccount(account_ref="revolut_main", bank="REVOLUT", account_labels=("MAIN",)),
        ),
        counterparty_rules=(),
    )
    seeded = _tx("Mystery", amount="-10.00")
    seeded = Transaction(
        booking_date=seeded.booking_date,
        description=seeded.description,
        amount_native=seeded.amount_native,
        currency=seeded.currency,
        source_file=seeded.source_file,
        bank=seeded.bank,
        parser=seeded.parser,
        category=seeded.category,
        subcategory=seeded.subcategory,
        category_confidence=seeded.category_confidence,
        category_source=seeded.category_source,
        category_rule_id=seeded.category_rule_id,
        cashflow_type=seeded.cashflow_type,
        from_account_ref="manual_source",
        to_account_ref=seeded.to_account_ref,
        from_account_type="external",
        to_account_type=seeded.to_account_type,
        account_inference_source="transaction_override",
        project=seeded.project,
        project_tags=seeded.project_tags,
        project_source=seeded.project_source,
        reviewed=seeded.reviewed,
        account_label=seeded.account_label,
        source_document_id=seeded.source_document_id,
        fx_rate_to_eur=seeded.fx_rate_to_eur,
        fx_rate_date=seeded.fx_rate_date,
        fx_source=seeded.fx_source,
        amount_eur=seeded.amount_eur,
        source_record_index=seeded.source_record_index,
        source_file_mtime=seeded.source_file_mtime,
    )

    inferred = infer_accounts_for_transactions([seeded], config=config)

    assert inferred[0].from_account_ref == "manual_source"
    assert inferred[0].from_account_type == "external"
    assert inferred[0].account_inference_source == "transaction_override"

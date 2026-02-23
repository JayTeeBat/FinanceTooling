import pandas as pd

from finance_tooling.metrics import (
    build_base_currency_summary,
    build_spend_by_category_eur,
    build_summary_by_currency,
)


def test_build_summary_by_currency() -> None:
    frame = pd.DataFrame(
        [
            {
                "currency": "USD",
                "amount_native": 2000.0,
                "category": "Income",
                "amount_eur": 1800.0,
            },
            {
                "currency": "USD",
                "amount_native": -125.5,
                "category": "Groceries",
                "amount_eur": -113.0,
            },
            {
                "currency": "EUR",
                "amount_native": -700.0,
                "category": "Housing",
                "amount_eur": -700.0,
            },
        ]
    )

    summary = build_summary_by_currency(frame)

    assert list(summary["currency"]) == ["EUR", "USD"]
    usd_row = summary[summary["currency"] == "USD"].iloc[0]
    assert float(usd_row["income"]) == 2000.0
    assert float(usd_row["expense"]) == -125.5
    assert float(usd_row["net"]) == 1874.5


def test_build_spend_by_category_and_base_summary() -> None:
    frame = pd.DataFrame(
        [
            {
                "currency": "USD",
                "amount_native": -125.5,
                "category": "Groceries",
                "amount_eur": -113.0,
            },
            {
                "currency": "EUR",
                "amount_native": -700.0,
                "category": "Housing",
                "amount_eur": -700.0,
            },
            {
                "currency": "EUR",
                "amount_native": 500.0,
                "category": "Income",
                "amount_eur": 500.0,
            },
        ]
    )

    spend = build_spend_by_category_eur(frame)
    summary = build_base_currency_summary(frame)

    assert list(spend["category"]) == ["Housing", "Groceries"]
    assert list(spend["spend_eur"]) == [700.0, 113.0]
    assert summary["net"] == -313.0

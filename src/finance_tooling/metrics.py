"""Metrics computation for transaction datasets."""

from __future__ import annotations

import pandas as pd

SUMMARY_COLUMNS = ["currency", "income", "expense", "net", "transactions"]


def build_summary_by_currency(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Compute income/expense/net per currency from canonical dataframe."""
    if dataframe.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    grouped = dataframe.groupby("currency")
    income = grouped["amount_native"].apply(lambda values: values[values > 0].sum())
    expense = grouped["amount_native"].apply(lambda values: values[values < 0].sum())
    transactions_count = grouped["amount_native"].count()

    summary = pd.DataFrame(
        {
            "income": income,
            "expense": expense,
            "transactions": transactions_count,
        }
    )
    summary["net"] = summary["income"] + summary["expense"]
    summary = summary.reset_index()[SUMMARY_COLUMNS]
    return summary.sort_values(by="currency", ascending=True).reset_index(drop=True)


def build_spend_by_category_native(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Aggregate spending by category (native amounts as absolute values)."""
    if dataframe.empty:
        return pd.DataFrame(columns=["category", "spend_native"])

    spend = (
        dataframe[dataframe["amount_native"] < 0]
        .assign(spend_native=lambda frame: frame["amount_native"].abs())
        .groupby("category")["spend_native"]
        .sum()
        .reset_index()
        .sort_values(by="spend_native", ascending=False)
        .reset_index(drop=True)
    )
    return spend


def build_spend_by_category_eur(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Aggregate spending by category in EUR using converted values."""
    if dataframe.empty:
        return pd.DataFrame(columns=["category", "spend_eur"])

    filtered = dataframe[dataframe["amount_eur"].notna() & (dataframe["amount_eur"] < 0)]
    if filtered.empty:
        return pd.DataFrame(columns=["category", "spend_eur"])

    spend = (
        filtered.assign(spend_eur=lambda frame: frame["amount_eur"].abs())
        .groupby("category")["spend_eur"]
        .sum()
        .reset_index()
        .sort_values(by="spend_eur", ascending=False)
        .reset_index(drop=True)
    )
    return spend


def build_base_currency_summary(dataframe: pd.DataFrame) -> dict[str, float]:
    """Compute aggregate income/expense/net in base currency from amount_eur column."""
    if dataframe.empty:
        return {"income": 0.0, "expense": 0.0, "net": 0.0}

    converted = dataframe[dataframe["amount_eur"].notna()]["amount_eur"]
    income = float(converted[converted > 0].sum())
    expense = float(converted[converted < 0].sum())
    return {"income": income, "expense": expense, "net": income + expense}


def build_monthly_net_eur(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Compute monthly EUR net trend."""
    if dataframe.empty:
        return pd.DataFrame(columns=["month", "net_eur"])

    converted = dataframe[dataframe["amount_eur"].notna()].copy()
    if converted.empty:
        return pd.DataFrame(columns=["month", "net_eur"])

    converted["month"] = pd.to_datetime(converted["booking_date"]).dt.to_period("M").astype(str)
    monthly = (
        converted.groupby("month")["amount_eur"]
        .sum()
        .reset_index()
        .rename(columns={"amount_eur": "net_eur"})
        .sort_values(by="month")
        .reset_index(drop=True)
    )
    return monthly

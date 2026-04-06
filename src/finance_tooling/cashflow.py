"""Cashflow aggregation helpers for finance-facing reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast

import pandas as pd

from finance_tooling.canonical import (
    CANONICAL_TRANSACTION_COLUMNS,
    canonical_transactions_from_dataframe,
    ensure_canonical_dataframe_schema,
)
from finance_tooling.classify import ClassificationRules, resolve_taxonomy_cashflow_type
from finance_tooling.transaction_overrides import (
    TransactionOverrideStore,
    iter_matching_override_entries,
)

_VALID_CASHFLOW_TYPES = frozenset({"in", "out", "transfer", "exclude"})
_TRACKED_SAVINGS_CATEGORIES = frozenset({"Retirement", "House"})
_TRACKED_SAVINGS_TRANSFER_SUBCATEGORIES = frozenset(
    {
        "savings transfer",
        "transfer / savings",
        "savings",
        "investment",
        "transfer / investment",
    }
)
_TRACKED_SAVINGS_KEYWORDS = frozenset({"retirement", "education", "house", "emergency"})


@dataclass(frozen=True)
class CashflowResolutionResult:
    """Resolved cashflow semantics for a dataframe."""

    dataframe: pd.DataFrame
    unknown_count: int
    unknown_categories: list[str]
    account_transfer_override_count: int
    account_transfer_conflict_count: int


def _normalized_string_series(dataframe: pd.DataFrame, column: str, *, default: str) -> pd.Series:
    values = dataframe.get(column, pd.Series("", index=dataframe.index, dtype="object"))
    return values.astype("string").fillna("").str.strip().replace("", default)


def _normalize_cashflow_type_series(dataframe: pd.DataFrame) -> pd.Series:
    values = dataframe.get("cashflow_type", pd.Series("", index=dataframe.index, dtype="object"))
    normalized = values.astype("string").fillna("").str.strip().str.casefold()
    return normalized.where(normalized.isin(_VALID_CASHFLOW_TYPES), "unknown")


def _contains_keyword(value: str) -> bool:
    normalized = value.strip().casefold()
    return any(keyword in normalized for keyword in _TRACKED_SAVINGS_KEYWORDS)


def _project_tags_series(dataframe: pd.DataFrame) -> pd.Series:
    raw = dataframe.get("project_tags", pd.Series("", index=dataframe.index, dtype="object"))

    def _normalize(value: object) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple, set, frozenset)):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return ",".join(parts)
        return str(value)

    return raw.map(_normalize).astype("string").fillna("")


def resolve_cashflow_types_for_dataframe(
    dataframe: pd.DataFrame,
    *,
    classification_rules: ClassificationRules,
    transaction_override_store: TransactionOverrideStore,
) -> CashflowResolutionResult:
    """Backfill or resolve cashflow_type for every canonical row."""
    if dataframe.empty:
        resolved = dataframe.copy()
        resolved["cashflow_type"] = pd.Series(dtype="object")
        return CashflowResolutionResult(
            dataframe=resolved,
            unknown_count=0,
            unknown_categories=[],
            account_transfer_override_count=0,
            account_transfer_conflict_count=0,
        )

    normalized_frame = ensure_canonical_dataframe_schema(dataframe)
    transactions = canonical_transactions_from_dataframe(
        normalized_frame[list(CANONICAL_TRANSACTION_COLUMNS)]
    )
    resolved_types: list[str] = []
    account_transfer_override_count = 0
    account_transfer_conflict_count = 0
    for tx in transactions:
        override_cashflow_type: str | None = None
        for entry in iter_matching_override_entries(tx, transaction_override_store):
            if entry.set_cashflow_type and entry.cashflow_type is not None:
                override_cashflow_type = cast(str, entry.cashflow_type)

        taxonomy_type = resolve_taxonomy_cashflow_type(tx.category, rules=classification_rules)
        from_account_type = (tx.from_account_type or "").strip().casefold()
        to_account_type = (tx.to_account_type or "").strip().casefold()
        internal_to_internal = from_account_type == "internal" and to_account_type == "internal"

        if override_cashflow_type is not None:
            resolved_type = override_cashflow_type
        elif internal_to_internal:
            resolved_type = "transfer"
            account_transfer_override_count += 1
            if taxonomy_type not in {None, "transfer"}:
                account_transfer_conflict_count += 1
        elif taxonomy_type is not None:
            resolved_type = taxonomy_type
        elif tx.amount_eur is not None and tx.amount_eur > 0:
            resolved_type = "in"
        elif tx.amount_eur is not None and tx.amount_eur < 0:
            resolved_type = "out"
        else:
            resolved_type = None

        resolved_types.append(resolved_type or "unknown")

    resolved = normalized_frame.copy()
    resolved["cashflow_type"] = resolved_types
    normalized = _normalize_cashflow_type_series(resolved)
    unknown_categories = sorted(
        {
            str(category).strip() or "Uncategorized"
            for category, cashflow_type in zip(
                resolved.get("category", pd.Series("", index=resolved.index, dtype="object")),
                normalized,
                strict=False,
            )
            if cashflow_type == "unknown"
        }
    )
    resolved["cashflow_type"] = normalized.astype(object)
    return CashflowResolutionResult(
        dataframe=resolved,
        unknown_count=int((normalized == "unknown").sum()),
        unknown_categories=unknown_categories,
        account_transfer_override_count=account_transfer_override_count,
        account_transfer_conflict_count=account_transfer_conflict_count,
    )


def build_cashflow_rows_frame(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Normalize canonical transaction rows for cashflow reporting."""
    if dataframe.empty:
        return pd.DataFrame(
            columns=[
                "booking_date",
                "booking_date_dt",
                "year",
                "month",
                "amount_eur",
                "category",
                "description",
                "project",
                "subcategory",
                "cashflow_type",
                "tracked_savings",
                "neutral_transfer",
            ]
        )

    working = dataframe.copy()
    booking_dates = pd.to_datetime(working.get("booking_date"), errors="coerce")
    working["booking_date_dt"] = booking_dates
    working["booking_date"] = booking_dates.dt.strftime("%Y-%m-%d")
    working = working.loc[working["booking_date"].notna()].copy()
    if working.empty:
        return pd.DataFrame(
            columns=[
                "booking_date",
                "booking_date_dt",
                "year",
                "month",
                "amount_eur",
                "category",
                "description",
                "project",
                "subcategory",
                "cashflow_type",
                "tracked_savings",
                "neutral_transfer",
            ]
        )

    working["year"] = working["booking_date_dt"].dt.year.astype(int)
    working["month"] = working["booking_date"].str.slice(0, 7)
    working["category"] = _normalized_string_series(working, "category", default="Uncategorized")
    working["project"] = _normalized_string_series(working, "project", default="")
    working["subcategory"] = _normalized_string_series(working, "subcategory", default="")
    working["description"] = _normalized_string_series(working, "description", default="unknown")
    working["cashflow_type"] = _normalize_cashflow_type_series(working)
    working["amount_eur"] = pd.to_numeric(working.get("amount_eur"), errors="coerce").fillna(0.0)
    project_tags = _project_tags_series(working)
    category_casefold = working["category"].str.casefold()
    subcategory_casefold = working["subcategory"].str.casefold()
    project_casefold = working["project"].str.casefold()
    tags_casefold = project_tags.str.casefold()
    amount_is_outflow = working["amount_eur"] < 0
    tracked_savings = amount_is_outflow & (
        working["category"].isin(_TRACKED_SAVINGS_CATEGORIES)
        | (
            category_casefold.eq("transfers")
            & subcategory_casefold.isin(_TRACKED_SAVINGS_TRANSFER_SUBCATEGORIES)
        )
        | project_casefold.map(_contains_keyword)
        | tags_casefold.map(_contains_keyword)
    )
    working["tracked_savings"] = tracked_savings
    working["neutral_transfer"] = working["cashflow_type"].eq("transfer")

    return working[
        [
            "booking_date",
            "booking_date_dt",
            "year",
            "month",
            "amount_eur",
            "category",
            "description",
            "project",
            "subcategory",
            "cashflow_type",
            "tracked_savings",
            "neutral_transfer",
        ]
    ].sort_values("booking_date", kind="stable", ignore_index=True)


def _period_metrics(rows: pd.DataFrame) -> dict[str, float | None]:
    if rows.empty:
        return {
            "income": 0.0,
            "expenses": 0.0,
            "net_cashflow": 0.0,
            "cashflow_margin": None,
        }

    cashflow_type = _normalize_cashflow_type_series(rows)
    income_total = float(rows.loc[cashflow_type.eq("in"), "amount_eur"].sum())
    expense_total = float((-rows.loc[cashflow_type.eq("out"), "amount_eur"]).sum())
    net_cashflow = income_total - expense_total
    return {
        "income": round(income_total, 2),
        "expenses": round(expense_total, 2),
        "net_cashflow": round(net_cashflow, 2),
        "cashflow_margin": round(net_cashflow / income_total, 4) if income_total else None,
    }


def build_cashflow_yoy_summary(
    dataframe: pd.DataFrame,
    *,
    as_of_date: date | None = None,
) -> dict[str, object]:
    """Build full-year and YTD cashflow reporting metrics."""
    rows = build_cashflow_rows_frame(dataframe)
    effective_as_of = as_of_date or datetime.now(UTC).date()
    payload: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of_date": effective_as_of.isoformat(),
        "covered_start_date": None,
        "covered_end_date": None,
        "years": [],
        "current_ytd": None,
    }
    if rows.empty:
        return payload

    payload["covered_start_date"] = str(rows["booking_date"].iloc[0])
    payload["covered_end_date"] = str(rows["booking_date"].iloc[-1])

    yearly_rows: list[dict[str, object]] = []
    completed_years = sorted(
        year for year in rows["year"].unique() if int(year) < effective_as_of.year
    )
    previous_metrics: dict[str, float | None] | None = None
    for year in completed_years:
        year_rows = rows.loc[rows["year"] == int(year)]
        metrics = _period_metrics(year_rows)
        yearly_row = {
            "year": int(year),
            **metrics,
            "income_yoy_delta": (
                round(float(metrics["income"]) - float(previous_metrics["income"]), 2)
                if previous_metrics is not None
                else None
            ),
            "expenses_yoy_delta": (
                round(float(metrics["expenses"]) - float(previous_metrics["expenses"]), 2)
                if previous_metrics is not None
                else None
            ),
            "net_cashflow_yoy_delta": (
                round(
                    float(metrics["net_cashflow"]) - float(previous_metrics["net_cashflow"]),
                    2,
                )
                if previous_metrics is not None
                else None
            ),
            "cashflow_margin_yoy_delta": (
                round(
                    float(metrics["cashflow_margin"]) - float(previous_metrics["cashflow_margin"]),
                    4,
                )
                if previous_metrics is not None
                and metrics["cashflow_margin"] is not None
                and previous_metrics["cashflow_margin"] is not None
                else None
            ),
        }
        yearly_rows.append(yearly_row)
        previous_metrics = metrics
    payload["years"] = yearly_rows

    current_year_rows = rows.loc[rows["year"] == effective_as_of.year]
    previous_year_rows = rows.loc[rows["year"] == (effective_as_of.year - 1)]
    if current_year_rows.empty or previous_year_rows.empty:
        return payload

    current_latest_ts = cast(pd.Timestamp, current_year_rows["booking_date_dt"].max())
    current_period_end = min(current_latest_ts.date(), effective_as_of)
    prior_period_end = date(
        effective_as_of.year - 1,
        current_period_end.month,
        current_period_end.day,
    )

    current_ytd_rows = current_year_rows.loc[
        current_year_rows["booking_date_dt"] <= pd.Timestamp(current_period_end)
    ]
    previous_ytd_rows = previous_year_rows.loc[
        previous_year_rows["booking_date_dt"] <= pd.Timestamp(prior_period_end)
    ]
    current_metrics = _period_metrics(current_ytd_rows)
    previous_metrics = _period_metrics(previous_ytd_rows)
    payload["current_ytd"] = {
        "label": f"{effective_as_of.year} YTD vs {effective_as_of.year - 1} YTD",
        "current_period_start": f"{effective_as_of.year}-01-01",
        "current_period_end": current_period_end.isoformat(),
        "prior_period_start": f"{effective_as_of.year - 1}-01-01",
        "prior_period_end": prior_period_end.isoformat(),
        "current": current_metrics,
        "prior": previous_metrics,
        "delta": {
            "income": round(
                float(current_metrics["income"]) - float(previous_metrics["income"]),
                2,
            ),
            "expenses": round(
                float(current_metrics["expenses"]) - float(previous_metrics["expenses"]), 2
            ),
            "net_cashflow": round(
                float(current_metrics["net_cashflow"])
                - float(previous_metrics["net_cashflow"]),
                2,
            ),
            "cashflow_margin": (
                round(
                    float(current_metrics["cashflow_margin"])
                    - float(previous_metrics["cashflow_margin"]),
                    4,
                )
                if current_metrics["cashflow_margin"] is not None
                and previous_metrics["cashflow_margin"] is not None
                else None
            ),
        },
    }
    return payload

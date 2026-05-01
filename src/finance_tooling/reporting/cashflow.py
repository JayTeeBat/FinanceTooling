"""Cashflow aggregation helpers for finance-facing reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast

import pandas as pd

from finance_tooling.categorization.account_inference import (
    AccountInferenceConfig,
    transaction_matches_identified_employer,
)
from finance_tooling.categorization.classify import (
    CategoryRule,
    ClassificationRules,
    resolve_category_id_from_labels,
    resolve_matching_rule_decision_role,
    resolve_matching_rule_economic_role,
    resolve_taxonomy_cashflow_type_for_category_id,
    resolve_taxonomy_decision_role_for_category_id,
    resolve_taxonomy_economic_role_for_category_id,
)
from finance_tooling.categorization.transaction_overrides import (
    TransactionOverrideStore,
    iter_matching_override_entries,
)
from finance_tooling.core.models import CANONICAL_TRANSACTION_COLUMNS
from finance_tooling.core.semantics import (
    EXPENSE_LIKE_ECONOMIC_ROLES,
    VALID_CASHFLOW_TYPES,
    VALID_DECISION_ROLES,
    VALID_ECONOMIC_ROLES,
)
from finance_tooling.core.store import transactions_from_dataframe
from finance_tooling.workflow.types import (
    CashflowCurrentYtd,
    CashflowPeriodMetrics,
    CashflowYearRow,
    CashflowYoYSummary,
    CashflowYtdDelta,
)

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
_INTEREST_DESCRIPTION_MARKERS = (
    "interest",
    "inter bruts",
    "inter.bruts",
    "interets",
    "interet",
)


@dataclass(frozen=True)
class CashflowResolutionResult:
    """Resolved cashflow semantics for a dataframe."""

    dataframe: pd.DataFrame
    unknown_count: int
    unknown_categories: list[str]
    account_transfer_override_count: int
    account_transfer_conflict_count: int


@dataclass(frozen=True)
class EconomicRoleResolutionResult:
    """Resolved economic roles for a dataframe."""

    dataframe: pd.DataFrame
    role_counts: dict[str, int]


@dataclass(frozen=True)
class DecisionRoleResolutionResult:
    """Resolved decision roles for a dataframe."""

    dataframe: pd.DataFrame
    role_counts: dict[str, int]


def _normalized_string_series(dataframe: pd.DataFrame, column: str, *, default: str) -> pd.Series:
    values = dataframe.get(column, pd.Series("", index=dataframe.index, dtype="object"))
    return values.astype("string").fillna("").str.strip().replace("", default)


def _normalize_cashflow_type_series(dataframe: pd.DataFrame) -> pd.Series:
    values = dataframe.get("cashflow_type", pd.Series("", index=dataframe.index, dtype="object"))
    normalized = values.astype("string").fillna("").str.strip().str.casefold()
    return normalized.where(normalized.isin(VALID_CASHFLOW_TYPES), "unknown")


def _normalize_economic_role_series(dataframe: pd.DataFrame) -> pd.Series:
    values = dataframe.get("economic_role", pd.Series("", index=dataframe.index, dtype="object"))
    normalized = values.astype("string").fillna("").str.strip().str.casefold()
    valid = normalized.where(normalized.isin(VALID_ECONOMIC_ROLES))
    cashflow_type = _normalize_cashflow_type_series(dataframe)
    category = _normalized_string_series(dataframe, "category", default="").str.casefold()
    subcategory = _normalized_string_series(dataframe, "subcategory", default="").str.casefold()
    fallback = pd.Series("expense", index=dataframe.index, dtype="string")
    fallback = fallback.mask(cashflow_type.eq("out"), "variable_expense")
    fallback = fallback.mask(cashflow_type.eq("transfer"), "transfer")
    fallback = fallback.mask(cashflow_type.eq("exclude"), "exclude")
    fallback = fallback.mask(category.eq("transfers"), "transfer")
    fallback = fallback.mask(
        category.isin({"non personal transactions", "pass-through", "excluded"}),
        "exclude",
    )
    fallback = fallback.mask(category.eq("income"), "income")
    fallback = fallback.mask(subcategory.isin({"salary", "interest"}), "income")
    return valid.fillna(fallback)


def _normalize_decision_role_series(dataframe: pd.DataFrame) -> pd.Series:
    values = dataframe.get("decision_role", pd.Series("", index=dataframe.index, dtype="object"))
    normalized = values.astype("string").fillna("").str.strip().str.casefold()
    valid = normalized.where(normalized.isin(VALID_DECISION_ROLES))
    if dataframe.empty:
        return valid
    economic_role = _normalize_economic_role_series(dataframe)
    cashflow_type = _normalize_cashflow_type_series(dataframe)
    category = _normalized_string_series(dataframe, "category", default="").str.casefold()
    subcategory = _normalized_string_series(dataframe, "subcategory", default="").str.casefold()

    fallback = pd.Series("unknown", index=dataframe.index, dtype="string")
    fallback = fallback.mask(economic_role.eq("exclude") | cashflow_type.eq("exclude"), "excluded")
    fallback = fallback.mask(
        category.isin({"groceries", "housing", "utilities", "family", "insurance", "transport"}),
        "essential",
    )
    fallback = fallback.mask(category.eq("taxes"), "tax")
    fallback = fallback.mask(category.isin({"dining", "shopping", "leisure"}), "discretionary")
    fallback = fallback.mask(
        category.eq("transfers")
        & subcategory.str.contains("savings|retirement|house|emergency", regex=True, na=False),
        "savings",
    )
    fallback = fallback.mask(
        category.eq("transfers") & subcategory.str.contains("investment", regex=True, na=False),
        "investment",
    )
    fallback = fallback.mask(
        category.eq("transfers")
        & subcategory.str.contains("loan|debt|mortgage", regex=True, na=False),
        "debt_service",
    )
    fallback = fallback.mask(
        category.eq("transfers") & subcategory.str.contains("tax", regex=True, na=False),
        "tax",
    )
    return valid.fillna(fallback)


def _contains_keyword(value: str) -> bool:
    normalized = value.strip().casefold()
    return any(keyword in normalized for keyword in _TRACKED_SAVINGS_KEYWORDS)


def _looks_like_interest_payment(description: str) -> bool:
    normalized = description.strip().casefold()
    return any(marker in normalized for marker in _INTEREST_DESCRIPTION_MARKERS)


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

    normalized_frame = dataframe.copy()
    active_rules = classification_rules
    for column in CANONICAL_TRANSACTION_COLUMNS:
        if column not in normalized_frame.columns:
            normalized_frame[column] = None

    transactions = transactions_from_dataframe(normalized_frame[CANONICAL_TRANSACTION_COLUMNS])
    resolved_types: list[str] = []
    account_transfer_override_count = 0
    account_transfer_conflict_count = 0
    for tx in transactions:
        override_cashflow_type: str | None = None
        for entry in iter_matching_override_entries(tx, transaction_override_store):
            if entry.set_cashflow_type and entry.cashflow_type is not None:
                override_cashflow_type = entry.cashflow_type

        category_id = (
            tx.reporting_category_id
            or tx.category_id
            or resolve_category_id_from_labels(
                tx.category,
                tx.subcategory,
                rules=active_rules,
                prefer_active=False,
            )
        )
        taxonomy_type = resolve_taxonomy_cashflow_type_for_category_id(
            category_id,
            rules=active_rules,
        )
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
        elif taxonomy_type == "exclude":
            resolved_type = "exclude"
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


def resolve_economic_roles_for_dataframe(
    dataframe: pd.DataFrame,
    *,
    account_inference_config: AccountInferenceConfig,
    classification_rules: ClassificationRules | None = None,
) -> EconomicRoleResolutionResult:
    """Resolve persisted economic roles from account rules, interest, and cashflow semantics."""
    if dataframe.empty:
        resolved = dataframe.copy()
        resolved["economic_role"] = pd.Series(dtype="object")
        return EconomicRoleResolutionResult(
            dataframe=resolved,
            role_counts={
                "income": 0,
                "fixed_expense": 0,
                "variable_expense": 0,
                "expense": 0,
                "transfer": 0,
                "exclude": 0,
            },
        )

    normalized_frame = dataframe.copy()
    active_rules = classification_rules or ClassificationRules(rules=(), taxonomy={})
    for column in CANONICAL_TRANSACTION_COLUMNS:
        if column not in normalized_frame.columns:
            normalized_frame[column] = None

    transactions = transactions_from_dataframe(normalized_frame[CANONICAL_TRANSACTION_COLUMNS])
    rules_by_id: dict[str, CategoryRule] = {
        rule.rule_id: rule for rule in active_rules.rules if rule.economic_role is not None
    }
    resolved_roles: list[str] = []
    for tx in transactions:
        cashflow_type = (tx.cashflow_type or "").strip().casefold()
        category_id = (
            tx.reporting_category_id
            or tx.category_id
            or resolve_category_id_from_labels(
                tx.category,
                tx.subcategory,
                rules=active_rules,
                prefer_active=False,
            )
        )
        if cashflow_type == "transfer":
            resolved_role = "transfer"
        elif cashflow_type == "exclude":
            resolved_role = "exclude"
        else:
            rule_role = None
            if tx.category_rule_id:
                rule = rules_by_id.get(tx.category_rule_id)
                rule_role = rule.economic_role if rule is not None else None
            if rule_role is None:
                rule_role = resolve_matching_rule_economic_role(tx, rules=active_rules)
            taxonomy_role = resolve_taxonomy_economic_role_for_category_id(
                category_id,
                rules=active_rules,
            )
            category = (tx.category or "").strip().casefold()
            subcategory = (tx.subcategory or "").strip().casefold()
            if rule_role is not None:
                resolved_role = rule_role
            elif taxonomy_role is not None:
                resolved_role = taxonomy_role
            elif subcategory == "salary":
                resolved_role = "income"
            elif transaction_matches_identified_employer(tx, config=account_inference_config):
                resolved_role = "income"
            elif category == "income" and subcategory == "interest":
                resolved_role = "income"
            elif subcategory == "refunds & interest" and _looks_like_interest_payment(
                tx.description
            ):
                resolved_role = "income"
            elif cashflow_type == "out":
                resolved_role = "variable_expense"
            else:
                resolved_role = "expense"
        resolved_roles.append(resolved_role)

    resolved = normalized_frame.copy()
    resolved["economic_role"] = resolved_roles
    normalized = _normalize_economic_role_series(resolved)
    resolved["economic_role"] = normalized.astype(object)
    role_counts = {
        role: int((normalized == role).sum())
        for role in (
            "income",
            "fixed_expense",
            "variable_expense",
            "expense",
            "transfer",
            "exclude",
        )
    }
    return EconomicRoleResolutionResult(dataframe=resolved, role_counts=role_counts)


def resolve_decision_roles_for_dataframe(
    dataframe: pd.DataFrame,
    *,
    classification_rules: ClassificationRules | None = None,
) -> DecisionRoleResolutionResult:
    """Resolve planning decision roles from taxonomy, rules, and semantic defaults."""
    if dataframe.empty:
        resolved = dataframe.copy()
        resolved["decision_role"] = pd.Series(dtype="object")
        return DecisionRoleResolutionResult(
            dataframe=resolved,
            role_counts={
                "essential": 0,
                "discretionary": 0,
                "savings": 0,
                "investment": 0,
                "debt_service": 0,
                "tax": 0,
                "excluded": 0,
                "unknown": 0,
            },
        )

    normalized_frame = dataframe.copy()
    active_rules = classification_rules or ClassificationRules(rules=(), taxonomy={})
    for column in CANONICAL_TRANSACTION_COLUMNS:
        if column not in normalized_frame.columns:
            normalized_frame[column] = None

    transactions = transactions_from_dataframe(normalized_frame[CANONICAL_TRANSACTION_COLUMNS])
    rules_by_id: dict[str, CategoryRule] = {
        rule.rule_id: rule for rule in active_rules.rules if rule.decision_role is not None
    }
    resolved_roles: list[str] = []
    for tx in transactions:
        cashflow_type = (tx.cashflow_type or "").strip().casefold()
        economic_role = (tx.economic_role or "").strip().casefold()
        category_id = (
            tx.reporting_category_id
            or tx.category_id
            or resolve_category_id_from_labels(
                tx.category,
                tx.subcategory,
                rules=active_rules,
                prefer_active=False,
            )
        )
        if cashflow_type == "exclude" or economic_role == "exclude":
            resolved_role = "excluded"
        else:
            rule_role = None
            if tx.category_rule_id:
                rule = rules_by_id.get(tx.category_rule_id)
                rule_role = rule.decision_role if rule is not None else None
            if rule_role is None:
                rule_role = resolve_matching_rule_decision_role(tx, rules=active_rules)
            taxonomy_role = resolve_taxonomy_decision_role_for_category_id(
                category_id,
                rules=active_rules,
            )
            category = (tx.category or "").strip().casefold()
            subcategory = (tx.subcategory or "").strip().casefold()
            if rule_role is not None:
                resolved_role = rule_role
            elif taxonomy_role is not None:
                resolved_role = taxonomy_role
            elif category in {
                "groceries",
                "housing",
                "utilities",
                "family",
                "insurance",
                "transport",
            }:
                resolved_role = "essential"
            elif category == "taxes":
                resolved_role = "tax"
            elif category in {"dining", "shopping", "leisure"}:
                resolved_role = "discretionary"
            elif category == "transfers" and any(
                marker in subcategory for marker in ("savings", "retirement", "house", "emergency")
            ):
                resolved_role = "savings"
            elif category == "transfers" and "investment" in subcategory:
                resolved_role = "investment"
            elif category == "transfers" and any(
                marker in subcategory for marker in ("loan", "debt", "mortgage")
            ):
                resolved_role = "debt_service"
            elif category == "transfers" and "tax" in subcategory:
                resolved_role = "tax"
            else:
                resolved_role = "unknown"
        resolved_roles.append(resolved_role)

    resolved = normalized_frame.copy()
    resolved["decision_role"] = resolved_roles
    normalized = _normalize_decision_role_series(resolved)
    resolved["decision_role"] = normalized.astype(object)
    role_counts = {
        role: int((normalized == role).sum())
        for role in (
            "essential",
            "discretionary",
            "savings",
            "investment",
            "debt_service",
            "tax",
            "excluded",
            "unknown",
        )
    }
    return DecisionRoleResolutionResult(dataframe=resolved, role_counts=role_counts)


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
                "economic_role",
                "decision_role",
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
                "economic_role",
                "decision_role",
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
    working["economic_role"] = _normalize_economic_role_series(working)
    working["decision_role"] = _normalize_decision_role_series(working)
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
            "economic_role",
            "decision_role",
            "tracked_savings",
            "neutral_transfer",
        ]
    ].sort_values("booking_date", kind="stable", ignore_index=True)


def _period_metrics(rows: pd.DataFrame) -> CashflowPeriodMetrics:
    if rows.empty:
        return {
            "income": 0.0,
            "expenses": 0.0,
            "net_cashflow": 0.0,
            "cashflow_margin": None,
            "transfer_volume": 0.0,
            "uncategorized_volume": 0.0,
        }

    economic_role = _normalize_economic_role_series(rows)
    cashflow_type = _normalize_cashflow_type_series(rows)
    category = _normalized_string_series(rows, "category", default="Uncategorized").str.casefold()
    income_total = float(rows.loc[economic_role.eq("income"), "amount_eur"].sum())
    expense_total = float(
        (-rows.loc[economic_role.isin(EXPENSE_LIKE_ECONOMIC_ROLES), "amount_eur"]).sum()
    )
    transfer_total = float(rows.loc[cashflow_type.eq("transfer"), "amount_eur"].abs().sum())
    uncategorized_total = float(rows.loc[category.eq("uncategorized"), "amount_eur"].abs().sum())
    net_cashflow = income_total - expense_total
    return {
        "income": round(income_total, 2),
        "expenses": round(expense_total, 2),
        "net_cashflow": round(net_cashflow, 2),
        "cashflow_margin": round(net_cashflow / income_total, 4) if income_total else None,
        "transfer_volume": round(transfer_total, 2),
        "uncategorized_volume": round(uncategorized_total, 2),
    }


def _metric_delta(current: float, previous: float, digits: int) -> float:
    return round(current - previous, digits)


def build_cashflow_yoy_summary(
    dataframe: pd.DataFrame,
    *,
    as_of_date: date | None = None,
) -> CashflowYoYSummary:
    """Build full-year and YTD cashflow reporting metrics."""
    rows = build_cashflow_rows_frame(dataframe)
    effective_as_of = as_of_date or datetime.now(UTC).date()
    payload: CashflowYoYSummary = {
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

    yearly_rows: list[CashflowYearRow] = []
    completed_years = sorted(
        int(year) for year in rows["year"].unique() if int(year) < effective_as_of.year
    )
    previous_metrics: CashflowPeriodMetrics | None = None
    for year in completed_years:
        year_rows = rows.loc[rows["year"] == year]
        metrics = _period_metrics(year_rows)
        yearly_row: CashflowYearRow = {
            "year": year,
            "income": metrics["income"],
            "expenses": metrics["expenses"],
            "net_cashflow": metrics["net_cashflow"],
            "cashflow_margin": metrics["cashflow_margin"],
            "transfer_volume": metrics["transfer_volume"],
            "uncategorized_volume": metrics["uncategorized_volume"],
            "income_yoy_delta": (
                _metric_delta(metrics["income"], previous_metrics["income"], 2)
                if previous_metrics is not None
                else None
            ),
            "expenses_yoy_delta": (
                _metric_delta(metrics["expenses"], previous_metrics["expenses"], 2)
                if previous_metrics is not None
                else None
            ),
            "net_cashflow_yoy_delta": (
                _metric_delta(metrics["net_cashflow"], previous_metrics["net_cashflow"], 2)
                if previous_metrics is not None
                else None
            ),
            "cashflow_margin_yoy_delta": (
                _metric_delta(metrics["cashflow_margin"], previous_metrics["cashflow_margin"], 4)
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
    ytd_delta: CashflowYtdDelta = {
        "income": _metric_delta(current_metrics["income"], previous_metrics["income"], 2),
        "expenses": _metric_delta(current_metrics["expenses"], previous_metrics["expenses"], 2),
        "net_cashflow": _metric_delta(
            current_metrics["net_cashflow"],
            previous_metrics["net_cashflow"],
            2,
        ),
        "cashflow_margin": (
            _metric_delta(
                current_metrics["cashflow_margin"],
                previous_metrics["cashflow_margin"],
                4,
            )
            if current_metrics["cashflow_margin"] is not None
            and previous_metrics["cashflow_margin"] is not None
            else None
        ),
    }
    payload["current_ytd"] = CashflowCurrentYtd(
        {
            "label": f"{effective_as_of.year} YTD vs {effective_as_of.year - 1} YTD",
            "current_period_start": f"{effective_as_of.year}-01-01",
            "current_period_end": current_period_end.isoformat(),
            "prior_period_start": f"{effective_as_of.year - 1}-01-01",
            "prior_period_end": prior_period_end.isoformat(),
            "current": current_metrics,
            "prior": previous_metrics,
            "delta": ytd_delta,
        }
    )
    return payload

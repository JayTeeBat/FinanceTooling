"""Category and subcategory consolidation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from finance_tooling.categorization.classify import ClassificationRules
from finance_tooling.core.config import Settings

_DEFAULT_REFERENCE_RELATIVE_PATH = Path(
    "backup/processed_backups/20260311-232233/processed/transactions_master.parquet"
)
_DELTA_FILENAME = "categorization_consolidation_delta.csv"

_CATEGORY_ALIASES: dict[str, str] = {
    "House": "Housing",
    "Mobility": "Transport",
    "Work": "Non Personal Transactions",
    "Dining": "Leisure",
    "Tax": "Taxes",
}

_PAIR_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    ("Dining", "Restaurants"): ("Leisure", "Dining out"),
    ("House", "Mortgage"): ("Housing", "Mortgage"),
    ("House", "Cleaning"): ("Housing", "Cleaning"),
    ("Mobility", "Car"): ("Transport", "Car"),
    ("Work", "Expenses"): ("Non Personal Transactions", "Work"),
    ("Tax", "Penalties"): ("Taxes", "Penalties"),
}

_SUBCATEGORY_ALIASES: dict[tuple[str, str], str] = {
    ("Transfers", "Bank Transfers"): "Bank Transfer",
    ("Transfers", "Wallet Transfers"): "Wallet Transfer",
    ("Transfers", "Savings"): "Savings Transfer",
    ("Leisure", "Dining Out"): "Dining out",
    ("Transport", "Bike"): "Bikes",
    ("Non Personal Transactions", "Expenses"): "Work",
}


@dataclass(frozen=True)
class CategoryNormalizationResult:
    """Normalized dataframe plus simple audit counters."""

    dataframe: pd.DataFrame
    changed_row_count: int
    changed_category_count: int
    changed_subcategory_count: int


def _normalize_text_series(dataframe: pd.DataFrame, column: str) -> pd.Series:
    return (
        dataframe.get(column, pd.Series("", index=dataframe.index, dtype="object"))
        .astype("string")
        .fillna("")
        .str.strip()
    )


def _valid_subcategory_lookup(rules: ClassificationRules) -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = {}
    for key, entry in rules.taxonomy.items():
        lookup[key] = {subcategory for subcategory in entry.subcategories}
    return lookup


def _resolve_normalized_pair(
    category: str,
    subcategory: str,
    *,
    rules: ClassificationRules,
    valid_subcategories: dict[str, set[str]],
) -> tuple[str, str]:
    category_value = category.strip()
    subcategory_value = subcategory.strip()
    if not category_value:
        return category_value, subcategory_value

    if (category_value, subcategory_value) in _PAIR_ALIASES:
        candidate_category, candidate_subcategory = _PAIR_ALIASES[
            (category_value, subcategory_value)
        ]
    else:
        candidate_category = _CATEGORY_ALIASES.get(category_value, category_value)
        candidate_subcategory = _SUBCATEGORY_ALIASES.get(
            (candidate_category, subcategory_value),
            subcategory_value,
        )

    taxonomy_entry = rules.taxonomy.get(candidate_category.casefold())
    if taxonomy_entry is None:
        return category_value, subcategory_value
    if not candidate_subcategory:
        return taxonomy_entry.name, ""

    valid_names = valid_subcategories.get(candidate_category.casefold(), set())
    if candidate_subcategory not in valid_names:
        return category_value, subcategory_value
    return taxonomy_entry.name, candidate_subcategory


def normalize_categories_for_dataframe(
    dataframe: pd.DataFrame,
    *,
    rules: ClassificationRules,
) -> CategoryNormalizationResult:
    """Normalize legacy category labels against the active taxonomy."""
    if dataframe.empty:
        return CategoryNormalizationResult(
            dataframe=dataframe.copy(),
            changed_row_count=0,
            changed_category_count=0,
            changed_subcategory_count=0,
        )

    normalized = dataframe.copy()
    categories = _normalize_text_series(normalized, "category")
    subcategories = _normalize_text_series(normalized, "subcategory")
    valid_subcategories = _valid_subcategory_lookup(rules)

    new_categories: list[str] = []
    new_subcategories: list[str] = []
    changed_category_count = 0
    changed_subcategory_count = 0
    changed_row_count = 0

    for category, subcategory in zip(categories.tolist(), subcategories.tolist(), strict=False):
        normalized_category, normalized_subcategory = _resolve_normalized_pair(
            category,
            subcategory,
            rules=rules,
            valid_subcategories=valid_subcategories,
        )
        if normalized_category != category or normalized_subcategory != subcategory:
            changed_row_count += 1
            if normalized_category != category:
                changed_category_count += 1
            if normalized_subcategory != subcategory:
                changed_subcategory_count += 1
        new_categories.append(normalized_category)
        new_subcategories.append(normalized_subcategory)

    normalized["category"] = pd.Series(new_categories, index=normalized.index, dtype="object")
    normalized["subcategory"] = pd.Series(new_subcategories, index=normalized.index).replace(
        "",
        pd.NA,
    )
    return CategoryNormalizationResult(
        dataframe=normalized,
        changed_row_count=changed_row_count,
        changed_category_count=changed_category_count,
        changed_subcategory_count=changed_subcategory_count,
    )


def _normalize_snapshot_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    normalized = dataframe.copy()
    normalized["booking_date_norm"] = pd.to_datetime(
        normalized.get("booking_date"),
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")
    normalized["description_norm"] = _normalize_text_series(normalized, "description")
    normalized["bank_norm"] = _normalize_text_series(normalized, "bank")
    normalized["currency_norm"] = _normalize_text_series(normalized, "currency")
    normalized["amount_native_norm"] = pd.to_numeric(
        normalized.get("amount_native"),
        errors="coerce",
    ).round(6)
    normalized["category_norm"] = _normalize_text_series(normalized, "category")
    normalized["subcategory_norm"] = _normalize_text_series(normalized, "subcategory")
    normalized["category_source_norm"] = _normalize_text_series(normalized, "category_source")
    normalized["signature"] = list(
        zip(
            normalized["booking_date_norm"],
            normalized["description_norm"],
            normalized["amount_native_norm"],
            normalized["currency_norm"],
            normalized["bank_norm"],
            strict=False,
        )
    )
    return normalized


def _proposed_action(
    before_category: str,
    before_subcategory: str,
    after_category: str,
    after_subcategory: str,
) -> str:
    if (before_category, before_subcategory) in _PAIR_ALIASES:
        target = _PAIR_ALIASES[(before_category, before_subcategory)]
        if target == (after_category, after_subcategory):
            return "merge_to_current_target"
    if _CATEGORY_ALIASES.get(before_category) == after_category:
        return "accept_current"
    if (
        before_category == after_category
        and _SUBCATEGORY_ALIASES.get((after_category, before_subcategory)) == after_subcategory
    ):
        return "merge_to_current_target"
    if before_category.casefold() == after_category.casefold() and (
        before_subcategory.casefold() == after_subcategory.casefold()
    ):
        return "merge_to_current_target"
    if before_category not in {after_category, "Uncategorized"}:
        return "manual_decision"
    return "accept_current"


def _dominant_mode(values: pd.Series) -> str:
    mode = values.mode()
    if mode.empty:
        return ""
    return str(mode.iloc[0])


def build_categorization_consolidation_delta(
    current_dataframe: pd.DataFrame,
    *,
    reference_dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Build a grouped delta of categorization changes vs the reference snapshot."""
    current = _normalize_snapshot_dataframe(current_dataframe)
    reference = _normalize_snapshot_dataframe(reference_dataframe)

    current_counts = current["signature"].value_counts()
    reference_counts = reference["signature"].value_counts()
    shared_signatures = set(current_counts.index).intersection(set(reference_counts.index))
    one_to_one = {
        signature
        for signature in shared_signatures
        if current_counts[signature] == 1 and reference_counts[signature] == 1
    }
    if not one_to_one:
        return pd.DataFrame(
            columns=[
                "before_category",
                "before_subcategory",
                "after_category",
                "after_subcategory",
                "count",
                "total_abs_amount_eur",
                "dominant_before_source",
                "dominant_after_source",
                "sample_description",
                "proposed_action",
            ]
        )

    merged = (
        reference[reference["signature"].isin(one_to_one)]
        .sort_values("signature")
        .merge(
            current[current["signature"].isin(one_to_one)].sort_values("signature"),
            on="signature",
            suffixes=("_before", "_after"),
        )
    )
    before_categorized = merged["category_norm_before"].str.casefold().ne("uncategorized")
    after_categorized = merged["category_norm_after"].str.casefold().ne("uncategorized")
    changed = merged.loc[
        before_categorized
        & after_categorized
        & (
            merged["category_norm_before"].ne(merged["category_norm_after"])
            | merged["subcategory_norm_before"].ne(merged["subcategory_norm_after"])
        )
    ].copy()
    if changed.empty:
        return pd.DataFrame()

    changed["abs_amount_eur_after"] = (
        pd.to_numeric(
            changed.get("amount_eur_after"),
            errors="coerce",
        )
        .abs()
        .fillna(0.0)
    )
    grouped = (
        changed.groupby(
            [
                "category_norm_before",
                "subcategory_norm_before",
                "category_norm_after",
                "subcategory_norm_after",
            ],
            dropna=False,
        )
        .agg(
            count=("signature", "size"),
            total_abs_amount_eur=("abs_amount_eur_after", "sum"),
            sample_description=("description_norm_after", "first"),
            dominant_before_source=("category_source_norm_before", _dominant_mode),
            dominant_after_source=("category_source_norm_after", _dominant_mode),
        )
        .reset_index()
        .rename(
            columns={
                "category_norm_before": "before_category",
                "subcategory_norm_before": "before_subcategory",
                "category_norm_after": "after_category",
                "subcategory_norm_after": "after_subcategory",
            }
        )
    )
    grouped["before_subcategory"] = grouped["before_subcategory"].replace("", pd.NA)
    grouped["after_subcategory"] = grouped["after_subcategory"].replace("", pd.NA)
    grouped["proposed_action"] = [
        _proposed_action(
            str(before_category),
            "" if pd.isna(before_subcategory) else str(before_subcategory),
            str(after_category),
            "" if pd.isna(after_subcategory) else str(after_subcategory),
        )
        for before_category, before_subcategory, after_category, after_subcategory in zip(
            grouped["before_category"],
            grouped["before_subcategory"],
            grouped["after_category"],
            grouped["after_subcategory"],
            strict=False,
        )
    ]
    return grouped.sort_values(
        ["count", "total_abs_amount_eur", "before_category", "after_category"],
        ascending=[False, False, True, True],
    ).reset_index(drop=True)


def write_categorization_consolidation_delta(
    *,
    settings: Settings,
    current_dataframe: pd.DataFrame,
) -> Path | None:
    """Write the grouped consolidation delta when the reference snapshot exists."""
    data_root = settings.processed_path.parent
    reference_path = data_root / _DEFAULT_REFERENCE_RELATIVE_PATH
    try:
        reference_exists = reference_path.exists()
    except OSError:
        return None
    if not reference_exists:
        return None
    try:
        reference_dataframe = pd.read_parquet(reference_path)
    except OSError:
        return None
    delta = build_categorization_consolidation_delta(
        current_dataframe,
        reference_dataframe=reference_dataframe,
    )
    output_path = settings.export_csv_path.parent / _DELTA_FILENAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    delta.to_csv(output_path, index=False)
    return output_path

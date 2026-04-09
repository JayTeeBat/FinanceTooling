"""Categorization integrity audit for live canonical outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import pandas as pd

from finance_tooling.categorization.classify import ClassificationRules, load_classification_rules
from finance_tooling.categorization.transaction_overrides import (
    TransactionOverrideStore,
    load_transaction_override_store,
)
from finance_tooling.core.config import Settings, load_settings_from_env

_AUDIT_FILENAME = "categorization_audit.md"


class AuditSampleRow(TypedDict, total=False):
    booking_date: object
    description: object
    bank: object
    amount_native: object
    currency: object
    category_source: object


class AuditYearlyOverrideRow(TypedDict):
    year: int
    row_count: int
    override_row_count: int


class OverrideIntegrity(TypedDict):
    override_entries: int
    matched_entry_count: int
    unmatched_entry_count: int
    override_row_count: int
    unmatched_categories: dict[str, int]
    sample_unmatched_transaction_ids: list[str]
    yearly_rows: list[AuditYearlyOverrideRow]


class ReviewStateIntegrity(TypedDict):
    review_state_rows: int
    reviewed_true_count: int
    reviewed_false_count: int
    matched_transaction_count: int
    unmatched_transaction_count: int


class MissingCategoryRow(TypedDict):
    category: str
    count: int
    source_counts: dict[str, int]
    subcategory_counts: dict[str, int]
    samples: list[AuditSampleRow]


class TaxonomyDrift(TypedDict):
    missing_categories: list[MissingCategoryRow]


class CoverageDriftRow(TypedDict):
    year: int
    row_count: int
    categorized_count: int
    uncategorized_count: int
    override_row_count: int


class CoverageDrift(TypedDict):
    yearly_rows: list[CoverageDriftRow]


class MixedSourceCategoryRow(TypedDict):
    category: str
    total_count: int
    source_counts: dict[str, int]


class RuleLayerConsistency(TypedDict):
    rule_rows_missing_rule_id: int
    mixed_source_categories: list[MixedSourceCategoryRow]


@dataclass(frozen=True)
class AuditFinding:
    """Single audit finding with a root-cause classification."""

    title: str
    classification: str
    detail: str


@dataclass(frozen=True)
class CategorizationAudit:
    """Audit result payload used for rendering and tests."""

    override_integrity: OverrideIntegrity
    review_state_integrity: ReviewStateIntegrity
    taxonomy_drift: TaxonomyDrift
    coverage_drift: CoverageDrift
    rule_layer_consistency: RuleLayerConsistency
    findings: list[AuditFinding]
    remediation_backlog: dict[str, list[str]]


def _string_series(
    dataframe: pd.DataFrame,
    column: str,
    *,
    default: str = "",
) -> pd.Series:
    series = dataframe.get(
        column,
        pd.Series(default, index=dataframe.index, dtype="object"),
    )
    return series.astype("string").fillna(default)


def _bool_series(dataframe: pd.DataFrame, column: str) -> pd.Series:
    return (
        dataframe.get(column, pd.Series(False, index=dataframe.index))
        .fillna(False)
        .astype(bool)
    )


def _year_series(dataframe: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(
        dataframe.get("booking_date", pd.Series(pd.NaT, index=dataframe.index)),
        errors="coerce",
    ).dt.year


def _sample_rows(dataframe: pd.DataFrame, mask: pd.Series) -> list[AuditSampleRow]:
    sample_columns = [
        column
        for column in (
            "booking_date",
            "description",
            "bank",
            "amount_native",
            "currency",
            "category_source",
        )
        if column in dataframe.columns
    ]
    if not sample_columns:
        return []
    return dataframe.loc[mask, sample_columns].head(10).to_dict(orient="records")


def _build_override_integrity(
    dataframe: pd.DataFrame,
    override_store: TransactionOverrideStore,
) -> OverrideIntegrity:
    transaction_ids = set(_string_series(dataframe, "transaction_id").tolist())
    entries = [entry for entry in override_store.entries if entry.transaction_id is not None]
    matched_entries = [
        entry for entry in entries if cast(str, entry.transaction_id) in transaction_ids
    ]
    unmatched_entries = [
        entry for entry in entries if cast(str, entry.transaction_id) not in transaction_ids
    ]

    override_mask = _string_series(dataframe, "category_source").str.strip().eq(
        "transaction_override"
    )
    years = _year_series(dataframe)
    yearly_rows: list[AuditYearlyOverrideRow] = []
    for raw_year in sorted(year for year in years.dropna().astype(int).unique()):
        year_mask = years.eq(raw_year)
        yearly_rows.append(
            {
                "year": int(raw_year),
                "row_count": int(year_mask.sum()),
                "override_row_count": int((override_mask & year_mask).sum()),
            }
        )

    unmatched_categories: dict[str, int] = {}
    for entry in unmatched_entries:
        if entry.set_category and entry.category:
            unmatched_categories[entry.category] = (
                unmatched_categories.get(entry.category, 0) + 1
            )

    return {
        "override_entries": len(entries),
        "matched_entry_count": len(matched_entries),
        "unmatched_entry_count": len(unmatched_entries),
        "override_row_count": int(override_mask.sum()),
        "unmatched_categories": dict(
            sorted(
                unmatched_categories.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "sample_unmatched_transaction_ids": [
            cast(str, entry.transaction_id) for entry in unmatched_entries[:10]
        ],
        "yearly_rows": yearly_rows,
    }


def _build_review_state_integrity(
    dataframe: pd.DataFrame,
    review_state: pd.DataFrame,
) -> ReviewStateIntegrity:
    if review_state.empty:
        return {
            "review_state_rows": 0,
            "reviewed_true_count": 0,
            "reviewed_false_count": 0,
            "matched_transaction_count": 0,
            "unmatched_transaction_count": 0,
        }

    canonical_ids = set(_string_series(dataframe, "transaction_id").tolist())
    review_ids = _string_series(review_state, "transaction_id").tolist()
    matched_transaction_count = sum(
        1 for transaction_id in review_ids if transaction_id in canonical_ids
    )
    unmatched_transaction_count = len(review_ids) - matched_transaction_count
    reviewed = _bool_series(review_state, "reviewed")
    return {
        "review_state_rows": len(review_state),
        "reviewed_true_count": int(reviewed.sum()),
        "reviewed_false_count": int((~reviewed).sum()),
        "matched_transaction_count": matched_transaction_count,
        "unmatched_transaction_count": unmatched_transaction_count,
    }


def _build_taxonomy_drift(
    dataframe: pd.DataFrame,
    rules: ClassificationRules,
) -> TaxonomyDrift:
    category = _string_series(dataframe, "category").str.strip()
    subcategory = _string_series(dataframe, "subcategory")
    category_source = _string_series(dataframe, "category_source")
    missing_categories: list[MissingCategoryRow] = []
    missing_names = {
        value
        for value in category.tolist()
        if value
        and value.casefold() != "uncategorized"
        and value.casefold() not in rules.taxonomy
    }
    for category_name in sorted(missing_names):
        mask = category.eq(category_name)
        source_counts = {
            str(index): int(value)
            for index, value in category_source.loc[mask].value_counts().items()
        }
        subcategory_counts = {
            str(index): int(value)
            for index, value in (
                subcategory.loc[mask].replace("", "<NA>").value_counts().head(10).items()
            )
        }
        missing_categories.append(
            {
                "category": category_name,
                "count": int(mask.sum()),
                "source_counts": source_counts,
                "subcategory_counts": subcategory_counts,
                "samples": _sample_rows(dataframe, mask),
            }
        )
    return {"missing_categories": missing_categories}


def _build_coverage_drift(dataframe: pd.DataFrame) -> CoverageDrift:
    years = _year_series(dataframe)
    category = _string_series(dataframe, "category").str.strip().str.casefold()
    category_source = _string_series(dataframe, "category_source").str.strip()
    yearly_rows: list[CoverageDriftRow] = []
    for raw_year in sorted(year for year in years.dropna().astype(int).unique()):
        year_mask = years.eq(raw_year)
        yearly_rows.append(
            {
                "year": int(raw_year),
                "row_count": int(year_mask.sum()),
                "categorized_count": int((year_mask & ~category.eq("uncategorized")).sum()),
                "uncategorized_count": int((year_mask & category.eq("uncategorized")).sum()),
                "override_row_count": int(
                    (year_mask & category_source.eq("transaction_override")).sum()
                ),
            }
        )
    return {"yearly_rows": yearly_rows}


def _build_rule_layer_consistency(dataframe: pd.DataFrame) -> RuleLayerConsistency:
    category_source = _string_series(dataframe, "category_source").str.strip()
    category_rule_id = _string_series(dataframe, "category_rule_id").str.strip()
    category = _string_series(dataframe, "category").str.strip()

    missing_rule_id_mask = category_source.eq("rule") & category_rule_id.eq("")
    mixed_source_categories: list[MixedSourceCategoryRow] = []
    crosstab = pd.crosstab(category, category_source)
    for category_name, row in crosstab.iterrows():
        nonzero = {str(index): int(value) for index, value in row.items() if int(value) > 0}
        if len(nonzero) > 1:
            mixed_source_categories.append(
                {
                    "category": str(category_name),
                    "total_count": int(row.sum()),
                    "source_counts": nonzero,
                }
            )
    mixed_source_categories.sort(
        key=lambda item: (-cast(int, item["total_count"]), cast(str, item["category"]))
    )

    return {
        "rule_rows_missing_rule_id": int(missing_rule_id_mask.sum()),
        "mixed_source_categories": mixed_source_categories[:20],
    }


def _classify_findings(
    override_integrity: OverrideIntegrity,
    review_state_integrity: ReviewStateIntegrity,
    taxonomy_drift: TaxonomyDrift,
    coverage_drift: CoverageDrift,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []

    if override_integrity["unmatched_entry_count"] > 0:
        findings.append(
            AuditFinding(
                title="Unmatched transaction overrides",
                classification="likely lost manual state",
                detail=(
                    f"{override_integrity['unmatched_entry_count']} override entries "
                    "no longer match current canonical transaction IDs."
                ),
            )
        )
    else:
        findings.append(
            AuditFinding(
                title="Transaction override coverage intact",
                classification="likely expected historical workflow difference",
                detail=(
                    "All "
                    f"{override_integrity['matched_entry_count']} transaction "
                    "override entries still match current canonical transaction IDs."
                ),
            )
        )

    review_rows = review_state_integrity["review_state_rows"]
    reviewed_true_count = review_state_integrity["reviewed_true_count"]
    if review_rows > 0 and reviewed_true_count == 0:
        findings.append(
            AuditFinding(
                title="Review-state semantics appear degraded",
                classification="likely lost manual state",
                detail=(
                    f"Review state contains {review_rows} rows, but 0 rows "
                    "are marked reviewed=True."
                ),
            )
        )

    missing_categories = taxonomy_drift["missing_categories"]
    if missing_categories:
        category_names = ", ".join(row["category"] for row in missing_categories[:10])
        findings.append(
            AuditFinding(
                title="Legacy categories missing from taxonomy",
                classification="likely taxonomy drift",
                detail=(
                    "Canonical data still contains categories absent from "
                    f"taxonomy: {category_names}."
                ),
            )
        )

    yearly_rows = coverage_drift["yearly_rows"]
    if yearly_rows:
        peak = max(yearly_rows, key=lambda row: row["override_row_count"])
        tail_rows = [row for row in yearly_rows if row["year"] >= 2022]
        if tail_rows and peak["override_row_count"] > 0:
            tail_peak = max(row["override_row_count"] for row in tail_rows)
            if tail_peak * 5 < peak["override_row_count"]:
                findings.append(
                    AuditFinding(
                        title="Override footprint drops sharply after early years",
                        classification="needs manual inspection",
                        detail=(
                            "Override row count peaks at "
                            f"{peak['override_row_count']} in {peak['year']} "
                            f"but is at most {tail_peak} from 2022 onward."
                        ),
                    )
                )

    return findings


def _build_remediation_backlog(
    override_integrity: OverrideIntegrity,
    review_state_integrity: ReviewStateIntegrity,
    taxonomy_drift: TaxonomyDrift,
    findings: list[AuditFinding],
) -> dict[str, list[str]]:
    safe_fixes: list[str] = []
    state_semantics: list[str] = []
    manual_inspection: list[str] = []

    missing_categories = taxonomy_drift["missing_categories"]
    if missing_categories:
        safe_fixes.append(
            "Restore or alias legacy taxonomy categories still present in "
            "canonical data, starting with House, Mobility, and Work."
        )
        safe_fixes.append(
            "Normalize override-backed legacy categories into live taxonomy "
            "names without rewriting matched transaction IDs."
        )

    if (
        review_state_integrity["review_state_rows"] > 0
        and review_state_integrity["reviewed_true_count"] == 0
    ):
        state_semantics.append(
            "Audit review-state write/import semantics to determine when "
            "reviewed=True markers were flattened to False."
        )
        state_semantics.append(
            "Compare review-export/review-import expectations against the "
            "live review-state parquet before modifying any categorization data."
        )

    if override_integrity["unmatched_entry_count"] > 0:
        state_semantics.append(
            "Investigate transaction-id migration history for unmatched manual "
            "overrides before editing overrides."
        )

    if any(finding.classification == "needs manual inspection" for finding in findings):
        manual_inspection.append(
            "Inspect the post-2021 yearly drop in override-sourced "
            "categorization to confirm workflow change versus migration-side regression."
        )
    manual_inspection.append(
        "Review the largest uncategorized fingerprints in 2016-2025 to "
        "separate ordinary rule gaps from suspected migration drift."
    )

    return {
        "safe_data_preserving_fixes": safe_fixes,
        "state_semantics_fixes": state_semantics,
        "manual_inspection": manual_inspection,
    }


def build_categorization_audit(
    *,
    canonical_transactions: pd.DataFrame,
    classification_rules: ClassificationRules,
    transaction_override_store: TransactionOverrideStore,
    review_state: pd.DataFrame,
) -> CategorizationAudit:
    """Build the categorization integrity audit from live workflow inputs."""
    override_integrity = _build_override_integrity(
        canonical_transactions,
        transaction_override_store,
    )
    review_state_integrity = _build_review_state_integrity(
        canonical_transactions,
        review_state,
    )
    taxonomy_drift = _build_taxonomy_drift(canonical_transactions, classification_rules)
    coverage_drift = _build_coverage_drift(canonical_transactions)
    rule_layer_consistency = _build_rule_layer_consistency(canonical_transactions)
    findings = _classify_findings(
        override_integrity,
        review_state_integrity,
        taxonomy_drift,
        coverage_drift,
    )
    remediation_backlog = _build_remediation_backlog(
        override_integrity,
        review_state_integrity,
        taxonomy_drift,
        findings,
    )
    return CategorizationAudit(
        override_integrity=override_integrity,
        review_state_integrity=review_state_integrity,
        taxonomy_drift=taxonomy_drift,
        coverage_drift=coverage_drift,
        rule_layer_consistency=rule_layer_consistency,
        findings=findings,
        remediation_backlog=remediation_backlog,
    )


def _markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return "_None_"
    header_line = "| " + " | ".join(headers) + " |"
    divider_line = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join(
        "| " + " | ".join(str(value) for value in row) + " |" for row in rows
    )
    return "\n".join([header_line, divider_line, body])


def render_categorization_audit_markdown(audit: CategorizationAudit) -> str:
    """Render a human-readable audit report."""
    findings_lines = [
        f"- `{finding.classification}`: {finding.title}. {finding.detail}"
        for finding in audit.findings
    ] or ["- No material findings detected."]

    override_year_rows = [
        [row["year"], row["row_count"], row["override_row_count"]]
        for row in audit.override_integrity["yearly_rows"]
    ]
    coverage_rows = [
        [
            row["year"],
            row["row_count"],
            row["categorized_count"],
            row["uncategorized_count"],
            row["override_row_count"],
        ]
        for row in audit.coverage_drift["yearly_rows"]
    ]
    taxonomy_rows = [
        [
            row["category"],
            row["count"],
            ", ".join(
                f"{key}={value}"
                for key, value in row["source_counts"].items()
            ),
            ", ".join(
                f"{key}={value}"
                for key, value in row["subcategory_counts"].items()
            ),
        ]
        for row in audit.taxonomy_drift["missing_categories"]
    ]
    mixed_source_rows = [
        [
            row["category"],
            row["total_count"],
            ", ".join(
                f"{key}={value}"
                for key, value in row["source_counts"].items()
            ),
        ]
        for row in audit.rule_layer_consistency["mixed_source_categories"]
    ]

    safe_fixes = "\n".join(
        f"- {item}" for item in audit.remediation_backlog["safe_data_preserving_fixes"]
    ) or "- None"
    state_fixes = "\n".join(
        f"- {item}" for item in audit.remediation_backlog["state_semantics_fixes"]
    ) or "- None"
    inspection_items = "\n".join(
        f"- {item}" for item in audit.remediation_backlog["manual_inspection"]
    ) or "- None"

    return "\n".join(
        [
            "# Categorization Integrity Audit",
            "",
            "## Findings",
            *findings_lines,
            "",
            "## Override Integrity",
            f"- Override entries: {audit.override_integrity['override_entries']}",
            (
                "- Matched override entries: "
                f"{audit.override_integrity['matched_entry_count']}"
            ),
            (
                "- Unmatched override entries: "
                f"{audit.override_integrity['unmatched_entry_count']}"
            ),
            (
                "- Canonical rows sourced from transaction overrides: "
                f"{audit.override_integrity['override_row_count']}"
            ),
            "",
            _markdown_table(["Year", "Rows", "Override Rows"], override_year_rows),
            "",
            "## Review-State Integrity",
            f"- Review-state rows: {audit.review_state_integrity['review_state_rows']}",
            (
                "- Reviewed=True rows: "
                f"{audit.review_state_integrity['reviewed_true_count']}"
            ),
            (
                "- Reviewed=False rows: "
                f"{audit.review_state_integrity['reviewed_false_count']}"
            ),
            (
                "- Review-state rows matching canonical transaction IDs: "
                f"{audit.review_state_integrity['matched_transaction_count']}"
            ),
            (
                "- Review-state rows missing from canonical data: "
                f"{audit.review_state_integrity['unmatched_transaction_count']}"
            ),
            "",
            "## Taxonomy Drift",
            _markdown_table(["Category", "Count", "Sources", "Subcategories"], taxonomy_rows),
            "",
            "## Coverage Drift",
            _markdown_table(
                ["Year", "Rows", "Categorized", "Uncategorized", "Override Rows"],
                coverage_rows,
            ),
            "",
            "## Rule-Layer Consistency",
            (
                "- Rule rows missing `category_rule_id`: "
                f"{audit.rule_layer_consistency['rule_rows_missing_rule_id']}"
            ),
            "",
            _markdown_table(["Category", "Total", "Sources"], mixed_source_rows),
            "",
            "## Remediation Backlog",
            "### Safe data-preserving fixes",
            safe_fixes,
            "",
            "### State semantics fixes",
            state_fixes,
            "",
            "### Manual inspection",
            inspection_items,
            "",
        ]
    )


def run_categorization_audit(settings: Settings) -> Path:
    """Run the live categorization audit and write a Markdown report."""
    canonical_transactions = pd.read_parquet(settings.master_parquet_path)
    classification_rules, rule_warnings = load_classification_rules(
        settings.category_rules_path
    )
    transaction_override_store, override_warnings = load_transaction_override_store(
        settings.transaction_overrides_path
    )
    if settings.review_state_path.exists():
        review_state = pd.read_parquet(settings.review_state_path)
    else:
        review_state = pd.DataFrame(
            columns=["transaction_id", "reviewed", "review_comment", "updated_at"]
        )

    audit = build_categorization_audit(
        canonical_transactions=canonical_transactions,
        classification_rules=classification_rules,
        transaction_override_store=transaction_override_store,
        review_state=review_state,
    )
    report = render_categorization_audit_markdown(audit)
    warnings_block: list[str] = []
    if rule_warnings or override_warnings:
        warnings_block.extend(["## Loader Warnings", ""])
        warnings_block.extend(f"- {warning}" for warning in [*rule_warnings, *override_warnings])
        warnings_block.append("")
        report = "\n".join([report.rstrip(), "", *warnings_block])

    output_path = settings.output_path.parent / _AUDIT_FILENAME
    output_path.write_text(report, encoding="utf-8")
    return output_path


def main() -> int:
    """Run the live categorization audit from current environment settings."""
    settings = load_settings_from_env()
    output_path = run_categorization_audit(settings)
    print(f"Categorization audit: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

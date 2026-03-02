"""Workflow orchestration for scanning, extracting, classifying, and reporting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pandas as pd

from finance_tooling.config import Settings
from finance_tooling.dashboard import render_dashboard_html
from finance_tooling.extract import extract_text_from_pdf
from finance_tooling.importers import load_hsbc_csv_transactions
from finance_tooling.models import Transaction, WorkflowResult
from finance_tooling.parsers import select_parser_with_diagnostics
from finance_tooling.scanner import discover_csv_files, discover_statement_pdfs
from finance_tooling.store import upsert_transactions
from finance_tooling.workflow.enrichment import enrich_transactions
from finance_tooling.workflow.guardrails import evaluate_guardrails
from finance_tooling.workflow.hsbc_merge import (
    assign_hsbc_csv_transactions_to_statement_dates,
    merge_hsbc_sources,
)
from finance_tooling.workflow.incremental_state import (
    build_state_entry,
    classify_source,
    compute_source_signature,
    load_ingest_state,
    save_ingest_state,
)
from finance_tooling.workflow.ingest import ingest_statements as ingest_workflow_stage
from finance_tooling.workflow.ingest import parse_hsbc_statement_period
from finance_tooling.workflow.periods import is_closed, load_period_statuses
from finance_tooling.workflow.reporting import persist_and_report
from finance_tooling.workflow.restatement import append_restatement_log, month_range
from finance_tooling.workflow.snapshots import create_run_snapshot

_MONTH_TOKEN = re.compile(r"((?:19|20)\d{2}-(?:0[1-9]|1[0-2]))(?:-(?:0[1-9]|[12]\d|3[01]))?")


@dataclass(frozen=True)
class RestatementExecution:
    """Restatement command result."""

    from_month: str
    to_month: str
    selected_files: tuple[Path, ...]
    dry_run: bool
    workflow_result: WorkflowResult | None


def _parse_hsbc_statement_period(full_text: str) -> tuple[date, date] | None:
    """Compatibility wrapper for HSBC statement period parser."""
    return parse_hsbc_statement_period(full_text)


def _assign_hsbc_csv_transactions_to_statement_dates(
    csv_transactions: list[Transaction],
    statement_periods_by_date: dict[str, tuple[date, date]],
) -> tuple[dict[str, list[Transaction]], list[Transaction], dict[str, int]]:
    """Compatibility wrapper for HSBC CSV month assignment helper."""
    return assign_hsbc_csv_transactions_to_statement_dates(
        csv_transactions,
        statement_periods_by_date,
    )


def _run_id(prefix: str = "run") -> str:
    return f"{prefix}_{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"


def _month_from_path(path: Path) -> str | None:
    match = _MONTH_TOKEN.search(path.name)
    if match is None:
        return None
    return match.group(1)


def _select_statuses_for_mode(mode: str) -> set[str]:
    if mode == "new":
        return {"new"}
    if mode == "changed":
        return {"changed"}
    if mode == "new-or-changed":
        return {"new", "changed"}
    return {"new", "changed", "unchanged"}


def _existing_row_count(parquet_path: Path) -> int:
    if not parquet_path.exists():
        return 0
    try:
        return len(pd.read_parquet(parquet_path))
    except Exception:
        return 0


def _upsert_adapter(parquet_path: Path, transactions: list[Transaction], replace_source_files):
    return upsert_transactions(
        parquet_path,
        transactions,
        replace_source_files=replace_source_files,
    )


def _run_incremental(
    settings: Settings,
    *,
    run_id: str,
    selected_files_override: list[Path] | None = None,
    allow_closed_period_override: bool = False,
    dry_run: bool = False,
    restatement_context: dict[str, object] | None = None,
) -> WorkflowResult:
    all_files = discover_statement_pdfs(settings.input_path)
    state = load_ingest_state(settings.ingest_state_path)
    period_statuses = load_period_statuses(settings.period_status_path)

    signatures = {str(path.resolve()): compute_source_signature(path) for path in all_files}
    statuses_by_path: dict[str, str] = {}
    for canonical_path, signature in signatures.items():
        statuses_by_path[canonical_path] = classify_source(signature, state.get(canonical_path))

    selected_paths = (
        {str(path.resolve()) for path in selected_files_override}
        if selected_files_override is not None
        else {
            path
            for path, status in statuses_by_path.items()
            if status in _select_statuses_for_mode(settings.ingest_mode)
        }
    )
    selected_files_raw = [path for path in all_files if str(path.resolve()) in selected_paths]

    allow_closed = settings.allow_closed_period_ingest or allow_closed_period_override
    selected_files: list[Path] = []
    skipped_closed = 0
    for path in selected_files_raw:
        canonical = str(path.resolve())
        existing = state.get(canonical)
        month_guess = existing.statement_month if existing is not None else _month_from_path(path)
        if not allow_closed and is_closed(period_statuses, month_guess):
            skipped_closed += 1
            continue
        selected_files.append(path)

    changed_paths = {
        canonical
        for canonical, status in statuses_by_path.items()
        if status == "changed" and canonical in {str(path.resolve()) for path in selected_files}
    }
    replace_sources: set[str] = set()
    if settings.replace_source_on_reingest:
        if settings.ingest_mode == "all":
            replace_sources = {str(path.resolve()) for path in selected_files}
        else:
            replace_sources = set(changed_paths)

    snapshot_path: Path | None = None
    if settings.snapshot_before_run and not dry_run:
        snapshot_path = create_run_snapshot(
            snapshot_root=settings.snapshot_dir,
            run_id=run_id,
            master_parquet_path=settings.master_parquet_path,
            ingest_state_path=settings.ingest_state_path,
            period_status_path=settings.period_status_path,
            category_rules_path=settings.category_rules_path,
            category_overrides_path=settings.category_overrides_path,
        )

    if dry_run:
        return WorkflowResult(
            dashboard_path=settings.output_path,
            parquet_path=settings.master_parquet_path,
            csv_path=settings.export_csv_path,
            json_path=settings.export_json_path,
            summary_path=settings.summary_json_path,
            completeness_path=settings.completeness_json_path,
            files_scanned=len(selected_files),
            files_failed=0,
            transactions_parsed=0,
            new_rows=0,
            total_rows=_existing_row_count(settings.master_parquet_path),
            completeness_status="not_run",
            completeness_coverage_ratio=0.0,
            missing_source_file_count=0,
            reconciliation_checkable_file_count=0,
            reconciliation_fail_count=0,
            reconciliation_uncheckable_file_count=0,
            reconciliation_pass_ratio=None,
            warnings=(),
        )

    ingest = ingest_workflow_stage(
        settings,
        discover_statement_pdfs=discover_statement_pdfs,
        extract_text_from_pdf=extract_text_from_pdf,
        select_parser_with_diagnostics=select_parser_with_diagnostics,
        discover_csv_files=discover_csv_files,
        load_hsbc_csv_transactions=load_hsbc_csv_transactions,
        selected_source_files=selected_files,
    )
    hsbc_merge = merge_hsbc_sources(
        ingest.transactions,
        ingest.validations,
        ingest.source_files,
        ingest.hsbc_statement_periods_by_date,
    )
    enrichment = enrich_transactions(hsbc_merge.transactions, settings)

    warnings = [
        *ingest.warnings,
        *hsbc_merge.warnings,
        *enrichment.warnings,
    ]
    selection_counters = {
        "files_discovered": len(all_files),
        "files_selected": len(selected_files),
        "files_skipped_closed_period": skipped_closed,
        "files_new": sum(1 for value in statuses_by_path.values() if value == "new"),
        "files_changed": sum(1 for value in statuses_by_path.values() if value == "changed"),
        "files_unchanged": sum(1 for value in statuses_by_path.values() if value == "unchanged"),
    }
    ingest_controls = {
        "ingest_mode": settings.ingest_mode,
        "replace_source_on_reingest": settings.replace_source_on_reingest,
        "metrics_scope": settings.metrics_scope,
        "allow_closed_period_ingest": settings.allow_closed_period_ingest,
        "snapshot_before_run": settings.snapshot_before_run,
        "strict_guardrails": settings.strict_guardrails,
    }

    result, summary_payload = persist_and_report(
        settings=settings,
        source_files=ingest.source_files,
        files_failed=ingest.files_failed,
        transactions=enrichment.transactions,
        validations=hsbc_merge.validations,
        parser_selection_diagnostics=ingest.parser_selection_diagnostics,
        parser_low_confidence_file_count=ingest.parser_low_confidence_file_count,
        hsbc_csv_files_scanned=ingest.hsbc_csv_files_scanned,
        hsbc_merge_metrics=hsbc_merge.metrics,
        hsbc_period_parse_variant_match_count=ingest.hsbc_period_parse_variant_match_count,
        hsbc_boundary_metrics=ingest.hsbc_boundary_metrics,
        hsbc_boundary_diagnostics=ingest.hsbc_boundary_diagnostics,
        hsbc_sign_metrics=ingest.hsbc_sign_metrics,
        hsbc_sign_diagnostics=ingest.hsbc_sign_diagnostics,
        hsbc_selection_diagnostics=hsbc_merge.selection_diagnostics,
        ingest_parser_duration_seconds_by_parser=ingest.parser_duration_seconds_by_parser,
        ingest_duration_seconds_by_bank=ingest.duration_seconds_by_bank,
        ingest_text_cache_enabled=ingest.text_cache_enabled,
        ingest_text_cache_hits=ingest.text_cache_hits,
        ingest_text_cache_misses=ingest.text_cache_misses,
        ingest_text_cache_write_count=ingest.text_cache_write_count,
        classification_diagnostics=enrichment.classification_diagnostics,
        warnings=warnings,
        replace_source_files=replace_sources,
        ingest_controls=ingest_controls,
        selection_counters=selection_counters,
        state_path=settings.ingest_state_path,
        period_status_path=settings.period_status_path,
        snapshot_path=snapshot_path,
        restatement_context=restatement_context,
        upsert_transactions_fn=_upsert_adapter,
        render_dashboard_html_fn=render_dashboard_html,
    )

    scopes_to_check = (
        ("run", summary_payload["run_scope"]),
        ("global", summary_payload["global_scope"]),
    )
    if settings.metrics_scope == "run":
        scopes_to_check = (("run", summary_payload["run_scope"]),)
    elif settings.metrics_scope == "global":
        scopes_to_check = (("global", summary_payload["global_scope"]),)

    guardrail_violations: list[str] = []
    for scope_name, scope_payload in scopes_to_check:
        guardrail = evaluate_guardrails(
            reconciliation_pass_ratio=result.reconciliation_pass_ratio,
            uncategorized_ratio=cast(float, scope_payload["uncategorized_ratio"]),
            new_rows=result.new_rows,
            replaced_rows=summary_payload["replaced_rows"],
        )
        guardrail_violations.extend(f"{scope_name}: {item}" for item in guardrail.violations)
    if guardrail_violations and settings.strict_guardrails:
        raise RuntimeError("Guardrail violation(s): " + "; ".join(guardrail_violations))

    next_state = dict(state)
    transactions_by_source: dict[str, list[Transaction]] = {}
    for transaction in hsbc_merge.transactions:
        transactions_by_source.setdefault(str(transaction.source_file.resolve()), []).append(
            transaction
        )

    for selected in selected_files:
        canonical = str(selected.resolve())
        signature = signatures[canonical]
        existing_entry = state.get(canonical)
        txs = transactions_by_source.get(canonical, [])
        bank_guess = txs[0].bank if txs else (existing_entry.bank_guess if existing_entry else None)
        month_guess = (
            existing_entry.statement_month
            if existing_entry is not None
            else _month_from_path(selected)
        )
        if month_guess is None and txs:
            latest_booking_date = max(tx.booking_date for tx in txs)
            month_guess = f"{latest_booking_date.year:04d}-{latest_booking_date.month:02d}"
        next_state[canonical] = build_state_entry(
            signature=signature,
            existing=existing_entry,
            last_status="success",
            last_error=None,
            last_run_id=run_id,
            bank_guess=bank_guess,
            statement_month=month_guess,
        )
    save_ingest_state(settings.ingest_state_path, next_state)
    return result


def run_workflow(settings: Settings) -> WorkflowResult:
    """Execute incremental workflow using configured ingestion controls."""
    return _run_incremental(settings, run_id=_run_id("run"))


def run_restatement(
    settings: Settings,
    *,
    from_month: str,
    to_month: str,
    reason: str,
    dry_run: bool = False,
) -> RestatementExecution:
    """Execute explicit restatement over a month range."""
    range_value = month_range(from_month, to_month)
    target_months = set(range_value.months)
    state = load_ingest_state(settings.ingest_state_path)
    all_files = discover_statement_pdfs(settings.input_path)
    selected_files = [
        path
        for path in all_files
        if ((state_entry := state.get(str(path.resolve()))) and state_entry.statement_month)
        or _month_from_path(path)
        in target_months
    ]

    if dry_run:
        return RestatementExecution(
            from_month=range_value.from_month,
            to_month=range_value.to_month,
            selected_files=tuple(selected_files),
            dry_run=True,
            workflow_result=None,
        )

    run_id = _run_id("restate")
    rows_before = _existing_row_count(settings.master_parquet_path)
    result = _run_incremental(
        settings,
        run_id=run_id,
        selected_files_override=selected_files,
        allow_closed_period_override=True,
        dry_run=False,
        restatement_context={
            "from_month": range_value.from_month,
            "to_month": range_value.to_month,
            "reason": reason,
            "dry_run": False,
        },
    )
    append_restatement_log(
        path=settings.restatement_log_path,
        run_id=run_id,
        month_range_value=range_value,
        reason=reason,
        dry_run=False,
        rows_before=rows_before,
        rows_after=result.total_rows,
    )
    return RestatementExecution(
        from_month=range_value.from_month,
        to_month=range_value.to_month,
        selected_files=tuple(selected_files),
        dry_run=False,
        workflow_result=result,
    )

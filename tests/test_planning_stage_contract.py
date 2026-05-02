from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from finance_tooling.__main__ import _build_parser


def _import_or_xfail(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            pytest.xfail(f"Planned module not implemented yet: {module_name}")
        raise


def _attr_or_xfail(module: Any, attr_name: str) -> Any:
    if not hasattr(module, attr_name):
        pytest.xfail(f"Planned API not implemented yet: {module.__name__}.{attr_name}")
    return getattr(module, attr_name)


def _settings_stub(tmp_path: Path) -> SimpleNamespace:
    processed_dir = tmp_path / "processed"
    outputs_dir = processed_dir / "outputs"
    state_dir = processed_dir / "state"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        processed_path=processed_dir,
        output_path=outputs_dir / "transform_dashboard.html",
        master_parquet_path=outputs_dir / "transform_transactions.parquet",
        budget_targets_path=config_dir / "budget_targets.yaml",
        category_rules_path=config_dir / "category_rules.yaml",
        project_rules_path=config_dir / "project_rules.yaml",
        account_rules_path=config_dir / "account_rules.yaml",
        project_overrides_path=config_dir / "project_overrides.yaml",
        transaction_overrides_path=config_dir / "transaction_overrides.yaml",
    )


def test_stage_root_helpers_default_to_processed_layout_and_legacy_fallbacks(
    tmp_path: Path,
) -> None:
    config = _import_or_xfail("finance_tooling.core.config")
    ingest_root_path = _attr_or_xfail(config, "ingest_root_path")
    transform_root_path = _attr_or_xfail(config, "transform_root_path")
    planning_root_path = _attr_or_xfail(config, "planning_root_path")
    resolve_transform_artifact_path = _attr_or_xfail(config, "resolve_transform_artifact_path")

    settings = _settings_stub(tmp_path)

    assert ingest_root_path(settings) == settings.processed_path / "ingest"
    assert transform_root_path(settings) == settings.processed_path / "transform"
    assert planning_root_path(settings) == settings.processed_path / "planning"

    legacy_settings = SimpleNamespace(
        staged_transactions_path=settings.processed_path
        / "ingest"
        / "ingest_staged_transactions.parquet",
        master_parquet_path=settings.processed_path
        / "transform"
        / "transform_transactions.parquet",
        output_path=settings.processed_path / "transform" / "transform_dashboard.html",
    )

    assert ingest_root_path(legacy_settings) == settings.processed_path / "ingest"
    assert transform_root_path(legacy_settings) == settings.processed_path / "transform"
    assert planning_root_path(legacy_settings) == settings.processed_path / "planning"

    legacy_outputs_dir = settings.processed_path / "outputs"
    legacy_outputs_dir.mkdir(parents=True, exist_ok=True)
    legacy_transform_path = legacy_outputs_dir / settings.master_parquet_path.name
    legacy_transform_path.write_text("legacy placeholder", encoding="utf-8")
    assert (
        resolve_transform_artifact_path(settings, settings.master_parquet_path)
        == legacy_transform_path
    )


def test_planning_cli_dispatch_registers_defaults_and_passes_explicit_args(
    monkeypatch, tmp_path: Path
) -> None:
    planning_command = _import_or_xfail("finance_tooling.commands.planning")
    handle = _attr_or_xfail(planning_command, "handle")
    configure_parser = _attr_or_xfail(planning_command, "configure_parser")
    _attr_or_xfail(planning_command, "run_planning")

    parser = _build_parser()
    subparsers_action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    if "planning" not in subparsers_action.choices:
        pytest.xfail("Top-level CLI has not registered the planning command yet")

    planning_parser = argparse.ArgumentParser(prog="planning")
    configure_parser(planning_parser)
    parsed = planning_parser.parse_args([])
    assert parsed.command == "planning"
    assert parsed.handler is handle

    captured: dict[str, Path | None] = {}
    explicit_input = tmp_path / "custom" / "transactions.parquet"
    explicit_output_dir = tmp_path / "custom" / "planning"
    explicit_budget_path = tmp_path / "custom" / "budget_targets.yaml"
    explicit_output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        planning_command,
        "load_settings_from_env",
        lambda: _settings_stub(tmp_path),
    )
    monkeypatch.setattr(planning_command, "print_planning_result", lambda _result, verbose=False: 0)

    def _run_planning(
        settings_arg: Any,
        *,
        input_transactions_path: Path | None,
        output_dir: Path | None,
        budget_targets_path: Path | None,
    ) -> Any:
        captured["input_transactions_path"] = input_transactions_path
        captured["output_dir"] = output_dir
        captured["budget_targets_path"] = budget_targets_path
        assert settings_arg is not None
        return SimpleNamespace(
            ledger_path=Path("planning_ledger.parquet"),
            kpi_summary_path=Path("planning_kpi_summary.json"),
            dashboard_path=Path("planning_dashboard.html"),
            warnings=(),
        )

    monkeypatch.setattr(planning_command, "run_planning", _run_planning)

    args = argparse.Namespace(
        input_transactions_path=explicit_input,
        output_dir=explicit_output_dir,
        budget_targets_path=explicit_budget_path,
        verbose=False,
    )
    exit_code = handle(args)

    assert exit_code == 0
    assert captured["input_transactions_path"] == explicit_input
    assert captured["output_dir"] == explicit_output_dir
    assert captured["budget_targets_path"] == explicit_budget_path


def test_run_planning_resolves_settings_defaults(monkeypatch, tmp_path: Path) -> None:
    planning_stage = _import_or_xfail("finance_tooling.workflow.planning_stage")
    run_planning = _attr_or_xfail(planning_stage, "run_planning")

    settings = _settings_stub(tmp_path)
    settings.category_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")
    frame = pd.DataFrame(
        [
            {
                "transaction_id": "tx-1",
                "booking_date": "2026-01-05",
                "amount_eur": 100.0,
                "cashflow_type": "inflow",
                "economic_role": "income",
                "decision_role": "income",
            }
        ]
    )

    legacy_outputs_dir = settings.processed_path / "outputs"
    legacy_outputs_dir.mkdir(parents=True, exist_ok=True)
    legacy_input = legacy_outputs_dir / settings.master_parquet_path.name
    frame.to_parquet(legacy_input, index=False)

    captured: dict[str, Path | tuple[str, ...]] = {}

    def _load_transactions(path: Path) -> pd.DataFrame:
        captured["input_transactions_path"] = path
        return frame

    def _render_dashboard(path: Path, **_kwargs: Any) -> Path:
        path.write_text("<html></html>", encoding="utf-8")
        return path

    monkeypatch.setattr(
        planning_stage,
        "_load_transactions",
        _load_transactions,
    )
    monkeypatch.setattr(
        planning_stage,
        "load_classification_rules",
        lambda _path: (None, []),
    )
    monkeypatch.setattr(
        planning_stage,
        "load_budget_config",
        lambda _path: (SimpleNamespace(targets=()), []),
    )
    monkeypatch.setattr(
        planning_stage,
        "render_planning_stage_dashboard_html",
        _render_dashboard,
    )

    result = run_planning(settings)

    assert captured["input_transactions_path"] == legacy_input
    assert result.input_transactions_path == legacy_input
    assert result.ledger_path.parent == settings.processed_path / "planning"
    assert result.dashboard_path.parent == settings.processed_path / "planning"


def test_run_planning_writes_expected_artifacts_and_reconciles_kpis(tmp_path: Path) -> None:
    planning_stage = _import_or_xfail("finance_tooling.workflow.planning_stage")
    run_planning = _attr_or_xfail(planning_stage, "run_planning")

    settings = _settings_stub(tmp_path)
    output_dir = settings.processed_path / "planning"
    settings.category_rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")

    frame = pd.DataFrame(
        [
            {
                "transaction_id": "tx-income",
                "booking_date": "2026-01-05",
                "description": "Salary",
                "source_document_id": "doc-income",
                "category_id": "income.salary",
                "reporting_category_id": "income.salary",
                "category": "Income",
                "subcategory": "Salary",
                "project": None,
                "cashflow_type": "inflow",
                "economic_role": "income",
                "decision_role": "income",
                "amount_eur": 1000.0,
                "bank": "DummyBank",
                "account_label": "Main",
            },
            {
                "transaction_id": "tx-fixed",
                "booking_date": "2026-01-06",
                "description": "Rent",
                "source_document_id": "doc-fixed",
                "category_id": "expense.housing.rent",
                "reporting_category_id": "expense.housing.rent",
                "category": "Housing",
                "subcategory": "Rent",
                "project": None,
                "cashflow_type": "outflow",
                "economic_role": "fixed_expense",
                "decision_role": "essential",
                "amount_eur": -300.0,
                "bank": "DummyBank",
                "account_label": "Main",
            },
            {
                "transaction_id": "tx-variable",
                "booking_date": "2026-01-07",
                "description": "Groceries",
                "source_document_id": "doc-variable",
                "category_id": "expense.food.groceries",
                "reporting_category_id": "expense.food.groceries",
                "category": "Food",
                "subcategory": "Groceries",
                "project": None,
                "cashflow_type": "outflow",
                "economic_role": "variable_expense",
                "decision_role": "discretionary",
                "amount_eur": -200.0,
                "bank": "DummyBank",
                "account_label": "Main",
            },
            {
                "transaction_id": "tx-savings",
                "booking_date": "2026-01-08",
                "description": "Savings transfer",
                "source_document_id": "doc-savings",
                "category_id": "transfer.savings",
                "reporting_category_id": "transfer.savings",
                "category": "Transfers",
                "subcategory": "Savings",
                "project": None,
                "cashflow_type": "transfer",
                "economic_role": "transfer",
                "decision_role": "savings",
                "amount_eur": -100.0,
                "bank": "DummyBank",
                "account_label": "Main",
            },
        ]
    )
    frame.to_parquet(settings.master_parquet_path, index=False)
    settings.budget_targets_path.write_text(
        "\n".join(
            [
                "currency: EUR",
                "targets:",
                "  - month: 2026-01",
                "    category_id: expense.food.groceries",
                "    amount: 250",
            ]
        ),
        encoding="utf-8",
    )

    run_planning(
        settings,
        input_transactions_path=settings.master_parquet_path,
        output_dir=output_dir,
        budget_targets_path=settings.budget_targets_path,
    )

    ledger_parquet_path = output_dir / "planning_ledger.parquet"
    ledger_csv_path = output_dir / "planning_ledger.csv"
    summary_path = output_dir / "planning_kpi_summary.json"
    budget_status_path = output_dir / "planning_budget_status.csv"
    dashboard_path = output_dir / "planning_dashboard.html"

    assert ledger_parquet_path.exists()
    assert ledger_csv_path.exists()
    assert summary_path.exists()
    assert budget_status_path.exists()
    assert dashboard_path.exists()

    ledger_parquet = pd.read_parquet(ledger_parquet_path)
    ledger_csv = pd.read_csv(ledger_csv_path)
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    budget_status = pd.read_csv(budget_status_path)
    dashboard_html = dashboard_path.read_text(encoding="utf-8")

    assert set(ledger_parquet["transaction_id"]) == set(ledger_csv["transaction_id"])
    assert len(ledger_parquet) == 4
    assert "description" in ledger_parquet.columns
    assert "account_holder" in ledger_parquet.columns
    assert (
        ledger_parquet.loc[ledger_parquet["transaction_id"].eq("tx-income"), "description"].iloc[0]
        == "Salary"
    )
    assert (
        ledger_parquet.loc[ledger_parquet["transaction_id"].eq("tx-income"), "account_holder"].iloc[
            0
        ]
        == "Main"
    )

    income_total = float(
        ledger_parquet.loc[
            ledger_parquet["planning_bucket"].eq("income"),
            "planning_amount_eur",
        ].sum()
    )
    expense_total = float(
        ledger_parquet.loc[
            ledger_parquet["planning_bucket"].eq("expense"),
            "planning_amount_eur",
        ].sum()
    )
    savings_total = float(
        ledger_parquet.loc[
            ledger_parquet["planning_bucket"].eq("savings"),
            "planning_amount_eur",
        ].sum()
    )
    fixed_expense_total = float(
        ledger_parquet.loc[
            ledger_parquet["economic_role"].eq("fixed_expense"), "planning_amount_eur"
        ].sum()
    )
    variable_expense_total = float(
        ledger_parquet.loc[
            ledger_parquet["economic_role"].eq("variable_expense"), "planning_amount_eur"
        ].sum()
    )

    totals = summary_payload["totals_by_planning_bucket"]
    ytd_totals = summary_payload["ytd_totals_by_planning_bucket"]

    assert totals["income"] == pytest.approx(income_total)
    assert totals["expense"] == pytest.approx(expense_total)
    assert totals["savings"] == pytest.approx(savings_total)
    assert ytd_totals["income"] == pytest.approx(income_total)
    assert ytd_totals["expense"] == pytest.approx(expense_total)
    assert ytd_totals["savings"] == pytest.approx(savings_total)
    assert summary_payload["economic_role_counts"]["fixed_expense"] == 1
    assert summary_payload["economic_role_counts"]["variable_expense"] == 1
    assert "surface_breakdowns" in summary_payload
    assert summary_payload["surface_breakdowns"]["economic_role"]["bucket_totals"][
        "fixed_expense"
    ] == pytest.approx(300.0)
    assert fixed_expense_total == pytest.approx(300.0)
    assert variable_expense_total == pytest.approx(200.0)

    assert len(budget_status) == 1
    assert budget_status.loc[0, "category_id"] == "expense.food.groceries"
    assert budget_status.loc[0, "actual_amount"] == pytest.approx(200.0)
    assert budget_status.loc[0, "variance"] == pytest.approx(50.0)
    assert "Planning Dashboard" in dashboard_html
    assert "Surface Explorer" in dashboard_html
    assert "economic_role" in dashboard_html
    assert "cashflow_type" in dashboard_html
    assert "decision_role" in dashboard_html
    assert "Budget Status" in dashboard_html
    assert "Planning Ledger" not in dashboard_html
    assert "Transaction" not in dashboard_html


def test_run_update_supports_skip_planning_and_stage_only_modes(
    monkeypatch, tmp_path: Path
) -> None:
    update_stage = _import_or_xfail("finance_tooling.workflow.update_stage")
    _attr_or_xfail(update_stage, "run_planning")

    settings = _settings_stub(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr(update_stage, "create_stage_backup_run", lambda **_: object())

    def _run_ingest(*_args: Any, **_kwargs: Any) -> Any:
        calls.append("ingest")
        return SimpleNamespace(staged_path=settings.processed_path / "state" / "ingest.parquet")

    def _run_transform(*_args: Any, **_kwargs: Any) -> Any:
        calls.append("transform")
        settings.master_parquet_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {
                    "transaction_id": "tx-1",
                    "booking_date": "2026-01-01",
                    "amount_eur": 100.0,
                    "cashflow_type": "inflow",
                    "economic_role": "income",
                    "decision_role": "income",
                }
            ]
        ).to_parquet(settings.master_parquet_path, index=False)
        return SimpleNamespace()

    def _run_planning(*_args: Any, **_kwargs: Any) -> Any:
        calls.append("planning")
        return SimpleNamespace()

    monkeypatch.setattr(update_stage, "run_ingest", _run_ingest)
    monkeypatch.setattr(update_stage, "run_transform", _run_transform)
    monkeypatch.setattr(update_stage, "run_planning", _run_planning)

    update_stage.run_update(settings, full_refresh=True)
    assert calls == ["ingest", "transform", "planning"]

    calls.clear()
    update_stage.run_update(settings, full_refresh=True, skip_planning=True)
    assert calls == ["ingest", "transform"]

    calls.clear()
    update_stage.run_update(settings, full_refresh=True, ingest_only=True)
    assert calls == ["ingest"]

    calls.clear()
    update_stage.run_update(settings, transform_only=True)
    assert calls == ["transform", "planning"]

    calls.clear()
    update_stage.run_update(settings, transform_only=True, skip_planning=True)
    assert calls == ["transform"]

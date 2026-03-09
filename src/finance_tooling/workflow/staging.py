"""Staging IO helpers for ingest->transform transaction handoff."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from finance_tooling.models import Transaction
from finance_tooling.workflow.types import StagingWriteResult

_REQUIRED_STAGED_COLUMNS = (
    "booking_date",
    "description",
    "source_record_index",
    "amount_native",
    "currency",
    "source_file",
    "bank",
    "parser",
    "category",
    "subcategory",
    "category_confidence",
    "category_source",
    "category_rule_id",
    "project",
    "project_tags",
    "project_source",
    "account_label",
    "fx_rate_to_eur",
    "fx_rate_date",
    "fx_source",
    "amount_eur",
    "source_file_mtime",
)


def _require_parquet_engine() -> None:
    try:
        __import__("pyarrow")
    except Exception as exc:
        raise RuntimeError(
            "Parquet support requires pyarrow. Install dependencies with `uv sync --all-groups`."
        ) from exc


def _is_missing(value: object) -> bool:
    return value is None or bool(pd.isna(value))


def _optional_str(value: object) -> str | None:
    if _is_missing(value):
        return None
    return str(value)


def _optional_project_tags(value: object) -> tuple[str, ...]:
    if _is_missing(value):
        return ()
    raw_values: list[str] = []
    if isinstance(value, list | tuple):
        raw_values.extend(str(item) for item in value)
    else:
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return ()
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                raw_values.extend(str(item) for item in payload)
            else:
                raw_values.append(text)
        except json.JSONDecodeError:
            raw_values.extend(part.strip() for part in text.split("|"))

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        tag = raw.strip()
        if not tag:
            continue
        marker = tag.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        normalized.append(tag)
    return tuple(normalized)


def _optional_decimal(value: object) -> Decimal | None:
    if _is_missing(value):
        return None
    return Decimal(str(value))


def _optional_date(value: object) -> date | None:
    if _is_missing(value):
        return None
    return date.fromisoformat(str(value))


def _optional_datetime(value: object) -> datetime | None:
    if _is_missing(value):
        return None
    return datetime.fromisoformat(str(value))


def write_staged_transactions(path: Path, transactions: list[Transaction]) -> StagingWriteResult:
    """Persist staged transactions to parquet with canonical stage schema."""
    _require_parquet_engine()
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "booking_date": tx.booking_date.isoformat(),
            "description": tx.description,
            "source_record_index": tx.source_record_index,
            "amount_native": str(tx.amount_native),
            "currency": tx.currency,
            "source_file": str(tx.source_file),
            "bank": tx.bank,
            "parser": tx.parser,
            "category": tx.category,
            "subcategory": tx.subcategory,
            "category_confidence": tx.category_confidence,
            "category_source": tx.category_source,
            "category_rule_id": tx.category_rule_id,
            "project": tx.project,
            "project_tags": (
                json.dumps(list(tx.project_tags), separators=(",", ":"), ensure_ascii=False)
                if tx.project_tags
                else None
            ),
            "project_source": tx.project_source,
            "account_label": tx.account_label,
            "fx_rate_to_eur": (str(tx.fx_rate_to_eur) if tx.fx_rate_to_eur is not None else None),
            "fx_rate_date": tx.fx_rate_date.isoformat() if tx.fx_rate_date is not None else None,
            "fx_source": tx.fx_source,
            "amount_eur": str(tx.amount_eur) if tx.amount_eur is not None else None,
            "source_file_mtime": (
                tx.source_file_mtime.isoformat() if tx.source_file_mtime is not None else None
            ),
        }
        for tx in transactions
    ]

    dataframe = pd.DataFrame(rows, columns=list(_REQUIRED_STAGED_COLUMNS))
    dataframe.to_parquet(path, index=False)
    return StagingWriteResult(
        path=path,
        rows_written=len(transactions),
        columns=tuple(dataframe.columns.tolist()),
    )


def read_staged_transactions(path: Path) -> list[Transaction]:
    """Load staged transactions from parquet and validate schema contract."""
    if not path.exists():
        raise FileNotFoundError(f"Staged transactions file not found: {path}")

    _require_parquet_engine()
    dataframe = pd.read_parquet(path)
    missing_columns = [column for column in _REQUIRED_STAGED_COLUMNS if column not in dataframe]
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Invalid staged transaction schema; missing columns: {missing}")

    transactions: list[Transaction] = []
    for row in dataframe.to_dict(orient="records"):
        transactions.append(
            Transaction(
                booking_date=date.fromisoformat(str(row["booking_date"])),
                description=str(row["description"]),
                source_record_index=(
                    int(row["source_record_index"])
                    if not _is_missing(row["source_record_index"])
                    else None
                ),
                amount_native=Decimal(str(row["amount_native"])),
                currency=str(row["currency"]),
                source_file=Path(str(row["source_file"])),
                bank=str(row["bank"]),
                parser=str(row["parser"]),
                category=(
                    str(row["category"]) if not _is_missing(row["category"]) else "Uncategorized"
                ),
                subcategory=_optional_str(row["subcategory"]),
                category_confidence=(
                    float(row["category_confidence"])
                    if not _is_missing(row["category_confidence"])
                    else None
                ),
                category_source=_optional_str(row["category_source"]),
                category_rule_id=_optional_str(row["category_rule_id"]),
                project=_optional_str(row["project"]),
                project_tags=_optional_project_tags(row["project_tags"]),
                project_source=_optional_str(row["project_source"]),
                account_label=_optional_str(row["account_label"]),
                fx_rate_to_eur=_optional_decimal(row["fx_rate_to_eur"]),
                fx_rate_date=_optional_date(row["fx_rate_date"]),
                fx_source=_optional_str(row["fx_source"]),
                amount_eur=_optional_decimal(row["amount_eur"]),
                source_file_mtime=_optional_datetime(row["source_file_mtime"]),
            )
        )

    return transactions

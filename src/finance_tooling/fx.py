"""Historical FX rates management and transaction-date resolution."""

from __future__ import annotations

from csv import DictReader
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from finance_tooling.models import Transaction

_ECB_SOURCE = "ECB_SDW"
_ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR"
_CACHE_COLUMNS = ["currency", "rate_date", "rate_to_eur", "source", "fetched_at"]


@dataclass(frozen=True)
class FxResolution:
    """Resolved FX data for a transaction date."""

    rate_to_eur: Decimal
    rate_date: date
    source: str


def _empty_cache() -> pd.DataFrame:
    return pd.DataFrame(columns=_CACHE_COLUMNS)


def read_fx_cache(path: Path) -> pd.DataFrame:
    """Load cached FX rates from parquet if available."""
    if not path.exists():
        return _empty_cache()

    frame = pd.read_parquet(path)
    if frame.empty:
        return _empty_cache()

    for column in _CACHE_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame = frame[_CACHE_COLUMNS].copy()
    frame["currency"] = frame["currency"].astype(str).str.upper()
    frame["rate_date"] = pd.to_datetime(frame["rate_date"]).dt.date
    return frame.drop_duplicates(subset=["currency", "rate_date"], keep="last")


def _write_fx_cache(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp.parquet")
    frame.to_parquet(tmp_path, index=False)
    tmp_path.replace(path)


def parse_ecb_csv(csv_text: str, currency: str) -> pd.DataFrame:
    """Parse ECB CSV payload into normalized cache rows."""
    rows: list[dict[str, object]] = []

    for row in DictReader(StringIO(csv_text)):
        time_period = row.get("TIME_PERIOD")
        obs_value = row.get("OBS_VALUE")
        if not time_period or not obs_value:
            continue

        try:
            rate_date = datetime.strptime(time_period, "%Y-%m-%d").date()
            rate_to_eur = float(obs_value)
        except ValueError:
            continue

        rows.append(
            {
                "currency": currency.upper(),
                "rate_date": rate_date,
                "rate_to_eur": rate_to_eur,
                "source": _ECB_SOURCE,
                "fetched_at": datetime.now(UTC).isoformat(),
            }
        )

    if not rows:
        return _empty_cache()

    return pd.DataFrame(rows, columns=_CACHE_COLUMNS)


def fetch_ecb_rates(currency: str, start_date: date, end_date: date) -> pd.DataFrame:
    """Fetch historical daily rates from ECB for one currency and date range."""
    if currency.upper() == "EUR":
        rows = [
            {
                "currency": "EUR",
                "rate_date": start_date,
                "rate_to_eur": 1.0,
                "source": "BASE",
                "fetched_at": datetime.now(UTC).isoformat(),
            }
        ]
        return pd.DataFrame(rows, columns=_CACHE_COLUMNS)

    url = (
        f"{_ECB_URL}/D.{currency.upper()}.EUR.SP00.A"
        f"?startPeriod={start_date.isoformat()}"
        f"&endPeriod={end_date.isoformat()}"
        "&format=csvdata"
    )
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    return parse_ecb_csv(response.text, currency)


def _required_ranges(
    transactions: list[Transaction],
    *,
    base_currency: str,
) -> dict[str, tuple[date, date]]:
    grouped: dict[str, list[date]] = {}
    for tx in transactions:
        currency = tx.currency.upper()
        if currency == base_currency:
            continue
        grouped.setdefault(currency, []).append(tx.booking_date)

    required: dict[str, tuple[date, date]] = {}
    for currency, dates in grouped.items():
        required[currency] = (min(dates), max(dates))
    return required


def ensure_fx_cache(
    cache_path: Path,
    transactions: list[Transaction],
    *,
    base_currency: str,
    auto_fetch: bool,
) -> tuple[pd.DataFrame, list[str]]:
    """Ensure cache contains rates for the transaction date ranges."""
    cache = read_fx_cache(cache_path)
    warnings: list[str] = []
    requirements = _required_ranges(transactions, base_currency=base_currency)

    fetched_frames: list[pd.DataFrame] = []

    for currency, (start_date, end_date) in requirements.items():
        existing = cache[cache["currency"] == currency]
        if not existing.empty:
            covered_min = min(existing["rate_date"])
            covered_max = max(existing["rate_date"])
            if covered_min <= start_date and covered_max >= end_date:
                continue

        if not auto_fetch:
            warnings.append(
                f"FX cache missing range for {currency} "
                f"({start_date}..{end_date}) and auto fetch disabled"
            )
            continue

        try:
            fetched = fetch_ecb_rates(currency, start_date, end_date)
            if fetched.empty:
                warnings.append(
                    f"No ECB rates fetched for {currency} in range {start_date}..{end_date}"
                )
            else:
                fetched_frames.append(fetched)
        except Exception as exc:
            warnings.append(f"Failed to fetch ECB rates for {currency}: {exc}")

    if fetched_frames:
        fetched_all = pd.concat(fetched_frames, ignore_index=True)
        cache = pd.concat([cache, fetched_all], ignore_index=True)
        cache = cache.drop_duplicates(subset=["currency", "rate_date"], keep="last")
        cache = cache.sort_values(by=["currency", "rate_date"]).reset_index(drop=True)
        _write_fx_cache(cache_path, cache)

    return cache, warnings


def resolve_rate(
    cache: pd.DataFrame,
    *,
    currency: str,
    booking_date: date,
    base_currency: str,
) -> FxResolution | None:
    """Resolve fx rate at booking date, falling back to previous available day."""
    code = currency.upper()
    if code == base_currency:
        return FxResolution(rate_to_eur=Decimal("1"), rate_date=booking_date, source="BASE")

    subset = cache[cache["currency"] == code]
    if subset.empty:
        return None

    candidates = subset[subset["rate_date"] <= booking_date].sort_values(by="rate_date")
    if candidates.empty:
        return None

    row = candidates.iloc[-1]
    return FxResolution(
        rate_to_eur=Decimal(str(row["rate_to_eur"])),
        rate_date=row["rate_date"],
        source=str(row["source"]),
    )

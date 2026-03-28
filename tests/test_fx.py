from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.fx import (
    build_fx_lookup_index,
    ensure_fx_cache,
    parse_ecb_csv,
    resolve_rate,
    resolve_rate_from_index,
)
from finance_tooling.models import Transaction

_USD_CSV = (
    "KEY,TIME_PERIOD,OBS_VALUE\n"
    "EXR.D.USD.EUR.SP00.A,2026-02-20,1.1767\n"
    "EXR.D.USD.EUR.SP00.A,2026-02-23,1.1784\n"
)


def _tx(booking_date: date, currency: str) -> Transaction:
    return Transaction(
        booking_date=booking_date,
        description="Sample",
        amount_native=Decimal("10"),
        currency=currency,
        source_file=Path("sample.pdf"),
        bank="TestBank",
        parser="test",
    )


def test_parse_ecb_csv() -> None:
    frame = parse_ecb_csv(_USD_CSV, "USD")

    assert len(frame) == 2
    assert list(frame["currency"]) == ["USD", "USD"]


def test_resolve_rate_uses_previous_day_fallback() -> None:
    cache = parse_ecb_csv(_USD_CSV, "USD")

    resolution = resolve_rate(
        cache,
        currency="USD",
        booking_date=date(2026, 2, 21),
        base_currency="EUR",
    )

    assert resolution is not None
    assert resolution.rate_date == date(2026, 2, 20)
    assert resolution.rate_to_eur == Decimal("1.1767")


def test_ensure_fx_cache_fetches_missing_ranges(tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "fx_rates_history.parquet"
    transactions = [_tx(date(2026, 2, 20), "USD")]

    called: list[tuple[str, date, date]] = []

    def fake_fetch(currency: str, start_date: date, end_date: date):
        called.append((currency, start_date, end_date))
        return parse_ecb_csv(
            "KEY,TIME_PERIOD,OBS_VALUE\nEXR.D.USD.EUR.SP00.A,2026-02-20,1.1767\n", currency
        )

    monkeypatch.setattr("finance_tooling.fx.fetch_ecb_rates", fake_fetch)

    cache, warnings = ensure_fx_cache(
        cache_path,
        transactions,
        base_currency="EUR",
        auto_fetch=True,
    )

    assert warnings == []
    assert len(called) == 1
    assert len(cache) == 1
    assert cache_path.exists()


def test_resolve_rate_from_index_matches_dataframe_resolution() -> None:
    cache = parse_ecb_csv(_USD_CSV, "USD")
    index = build_fx_lookup_index(cache)

    direct = resolve_rate(
        cache,
        currency="USD",
        booking_date=date(2026, 2, 21),
        base_currency="EUR",
    )
    indexed = resolve_rate_from_index(
        index,
        currency="USD",
        booking_date=date(2026, 2, 21),
        base_currency="EUR",
    )

    assert indexed == direct

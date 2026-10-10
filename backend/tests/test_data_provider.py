"""Demo dataset and provider tests."""

from datetime import date

import pytest

from app.data.demo_provider import DATASET_PATH, DemoDataProvider
from app.data.validation import find_bar_issues
from tests.factories import make_snapshot

REQUIRED_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]


@pytest.fixture(scope="module")
def provider() -> DemoDataProvider:
    return DemoDataProvider()


def test_dataset_file_exists():
    assert DATASET_PATH.exists()


@pytest.mark.parametrize("symbol", REQUIRED_SYMBOLS)
def test_required_symbols_have_enough_history(provider, symbol):
    snapshot = provider.get_snapshot(symbol)
    assert snapshot is not None
    assert len(snapshot.bars) >= 120


@pytest.mark.parametrize("symbol", REQUIRED_SYMBOLS)
def test_snapshot_is_marked_as_simulated(provider, symbol):
    snapshot = provider.get_snapshot(symbol)
    assert snapshot.is_simulated is True
    assert snapshot.data_source == "demo_dataset"


@pytest.mark.parametrize("symbol", REQUIRED_SYMBOLS)
def test_bars_have_all_ohlcv_fields_and_are_clean(provider, symbol):
    snapshot = provider.get_snapshot(symbol)
    for bar in snapshot.bars:
        assert isinstance(bar.date, date)
        assert bar.open > 0 and bar.high > 0 and bar.low > 0 and bar.close > 0
        assert bar.volume > 0
    assert snapshot.data_issues == []


def test_dates_are_sorted_and_end_on_last_date(provider):
    snapshot = provider.get_snapshot("NVDA")
    dates = [bar.date for bar in snapshot.bars]
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)
    assert snapshot.as_of == date(2026, 9, 30)


def test_provider_is_deterministic_across_instances():
    first = DemoDataProvider().get_snapshot("TSLA")
    second = DemoDataProvider().get_snapshot("TSLA")
    assert first.bars == second.bars
    assert first.fundamentals == second.fundamentals


def test_unknown_symbol_returns_none(provider):
    assert provider.get_snapshot("ZZZZ") is None


def test_fundamentals_are_loaded_for_demo_symbol(provider):
    fundamentals = provider.get_snapshot("MSFT").fundamentals
    assert fundamentals.revenue_growth == 0.14
    assert fundamentals.pe_ratio == 34.2


def test_validation_detects_bad_ohlc_and_non_positive_price():
    snapshot = make_snapshot([100.0, 101.0, 102.0])
    broken = snapshot.bars[1].__class__(
        date=snapshot.bars[1].date,
        open=101.0,
        high=90.0,  # high below open/close: inconsistent
        low=99.0,
        close=101.0,
        volume=10,
    )
    issues = find_bar_issues([snapshot.bars[0], broken])
    assert any("Inconsistent OHLC" in issue for issue in issues)

    zero = snapshot.bars[0].__class__(
        date=snapshot.bars[0].date, open=0.0, high=1.0, low=0.0, close=0.0, volume=1
    )
    assert any("Non-positive" in issue for issue in find_bar_issues([zero]))

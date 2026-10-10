"""Helpers that build controlled, hand-made market snapshots for tests."""

from datetime import date, timedelta

from app.data.provider import Fundamentals, MarketDataProvider, MarketSnapshot, PriceBar

START = date(2026, 1, 2)


def bars_from_closes(closes: list[float]) -> list[PriceBar]:
    bars = []
    for index, close in enumerate(closes):
        bars.append(
            PriceBar(
                date=START + timedelta(days=index),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=1_000_000,
            )
        )
    return bars


def make_snapshot(
    closes: list[float],
    fundamentals: Fundamentals | None = None,
    symbol: str = "TEST",
    company_name: str = "Test Company",
) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        company_name=company_name,
        bars=bars_from_closes(closes),
        fundamentals=fundamentals,
        data_source="test_fixture",
        is_simulated=True,
    )


class FixedProvider(MarketDataProvider):
    """Provider that returns one snapshot for one symbol and None otherwise."""

    def __init__(self, snapshot: MarketSnapshot | None):
        self._snapshot = snapshot

    def get_snapshot(self, symbol: str) -> MarketSnapshot | None:
        if self._snapshot is None or symbol != self._snapshot.symbol:
            return None
        return self._snapshot


def rising_closes(count: int, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + step * index for index in range(count)]


def alternating_closes(count: int, start: float = 100.0, swing: float = 0.10) -> list[float]:
    """Closes that move up and down by `swing` each day: very high volatility."""
    closes = [start]
    for index in range(1, count):
        factor = (1 + swing) if index % 2 else (1 - swing)
        closes.append(closes[-1] * factor)
    return closes

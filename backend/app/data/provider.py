"""Abstract market data provider interface.

Analysis code depends only on this interface. Replacing the demo dataset with
a real provider later means implementing `MarketDataProvider` and wiring it in
`app/main.py`; no analysis code changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class PriceBar:
    """One daily OHLCV bar."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class Fundamentals:
    """Basic fundamentals. A `None` value means the metric is unavailable."""

    revenue_growth: float | None
    profit_margin: float | None
    pe_ratio: float | None
    earnings_growth: float | None


@dataclass(frozen=True)
class MarketSnapshot:
    """Everything the analysis engine needs for one symbol."""

    symbol: str
    company_name: str
    bars: list[PriceBar]
    fundamentals: Fundamentals | None
    data_source: str
    is_simulated: bool
    data_issues: list[str] = field(default_factory=list)

    @property
    def as_of(self) -> date | None:
        """Date of the most recent bar, or None if there are no bars."""
        return self.bars[-1].date if self.bars else None


class MarketDataProvider(ABC):
    """Source of market data. Returns None for unknown symbols."""

    @abstractmethod
    def get_snapshot(self, symbol: str) -> MarketSnapshot | None:
        """Return the snapshot for `symbol`, or None if the symbol is unknown."""

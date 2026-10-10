"""Demo market data provider backed by the static, synthetic JSON dataset.

Every snapshot it returns is marked `is_simulated=True` with
`data_source="demo_dataset"`. Nothing here is real-time market data.
"""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.data.provider import Fundamentals, MarketDataProvider, MarketSnapshot, PriceBar
from app.data.validation import find_bar_issues

DATASET_PATH = Path(__file__).resolve().parent / "demo_dataset.json"
DATA_SOURCE = "demo_dataset"


@lru_cache(maxsize=1)
def _load_dataset() -> dict:
    with DATASET_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _to_bar(raw: dict) -> PriceBar:
    return PriceBar(
        date=date.fromisoformat(raw["date"]),
        open=float(raw["open"]),
        high=float(raw["high"]),
        low=float(raw["low"]),
        close=float(raw["close"]),
        volume=int(raw["volume"]),
    )


class DemoDataProvider(MarketDataProvider):
    """Serves the bundled demo dataset. Works fully offline."""

    def get_snapshot(self, symbol: str) -> MarketSnapshot | None:
        entry = _load_dataset()["symbols"].get(symbol)
        if entry is None:
            return None

        bars = [_to_bar(raw) for raw in entry["bars"]]
        raw_fundamentals = entry.get("fundamentals")
        fundamentals = (
            Fundamentals(
                revenue_growth=raw_fundamentals.get("revenueGrowth"),
                profit_margin=raw_fundamentals.get("profitMargin"),
                pe_ratio=raw_fundamentals.get("peRatio"),
                earnings_growth=raw_fundamentals.get("earningsGrowth"),
            )
            if raw_fundamentals
            else None
        )

        return MarketSnapshot(
            symbol=symbol,
            company_name=entry["companyName"],
            bars=bars,
            fundamentals=fundamentals,
            data_source=DATA_SOURCE,
            is_simulated=True,
            data_issues=find_bar_issues(bars),
        )

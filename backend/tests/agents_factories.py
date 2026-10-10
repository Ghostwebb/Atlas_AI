"""Controlled inputs for the Phase 7 strategy tests (synthetic, test-only)."""

from datetime import date, timedelta

from app.agents.snapshot import AgentSnapshot, Metric, build_agent_snapshot
from app.data.provider import Fundamentals, MarketSnapshot, PriceBar

UNITS = {
    "price_last": "usd", "sma20": "usd", "sma50": "usd", "pe_ratio": "multiple", "volume_ratio_20_60": "ratio",
}
FUNDAMENTAL_KEYS = {"revenue_growth", "earnings_growth", "profit_margin", "pe_ratio"}

# A neutral, complete baseline: every criterion of every strategy is evaluable.
BASE = {
    "price_last": 100.0, "return_20d": 0.0, "return_60d": 0.0, "sma20": 100.0, "sma50": 100.0,
    "price_vs_sma20": 0.0, "sma20_vs_sma50": 0.0, "volatility_annualized": 0.35, "volatility_20d": 0.35,
    "max_drawdown": 0.20, "current_drawdown": 0.10, "volume_ratio_20_60": 1.0,
    "revenue_growth": 0.10, "earnings_growth": 0.05, "profit_margin": 0.10, "pe_ratio": 20.0,
}


def agent_snapshot(**overrides) -> AgentSnapshot:
    values = {**BASE, **overrides}
    statuses = values.pop("_status", {})
    metrics = {
        key: Metric(value, UNITS.get(key, "decimal"), "fundamentals" if key in FUNDAMENTAL_KEYS else "price_bars",
                    None if key in FUNDAMENTAL_KEYS else "test", f"test metric {key}",
                    statuses.get(key, "missing" if value is None else "ok"),
                    None if value is not None else f"test {statuses.get(key, 'missing')}")
        for key, value in values.items()
    }
    return AgentSnapshot(symbol="TEST", company_name="Test Co", data_source="demo_dataset", provenance="synthetic",
                         is_simulated=True, observations=120, first_date="2026-04-16", last_date="2026-09-30",
                         data_issues=(), warnings=("test",), metrics=metrics)


def market_snapshot(closes: list[float], volumes: list[int] | None = None,
                    fundamentals: Fundamentals | None = None) -> MarketSnapshot:
    start = date(2026, 1, 1)
    volumes = volumes or [1_000_000] * len(closes)
    bars = [PriceBar(date=start + timedelta(days=i), open=c, high=c, low=c, close=c, volume=v)
            for i, (c, v) in enumerate(zip(closes, volumes))]
    return MarketSnapshot(symbol="TEST", company_name="Test Co", bars=bars, fundamentals=fundamentals,
                          data_source="demo_dataset", is_simulated=True, data_issues=[])


def built(closes, volumes=None, fundamentals=None) -> AgentSnapshot:
    return build_agent_snapshot(market_snapshot(closes, volumes, fundamentals))

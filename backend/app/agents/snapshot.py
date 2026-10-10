"""One shared, public snapshot per request: every strategy reads exactly these metrics.

Metrics are computed once from the provider's MarketSnapshot (no extra data queries per agent),
using only bars up to the last bar (no look-ahead). Insufficient history, missing inputs or
non-finite results produce value None, never 0. Values are rounded to METRIC_DECIMALS and the
strategies evaluate the rounded values, so every cited number is reproducible from the JSON.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from app.agents.config import (
    METRIC_DECIMALS,
    MIN_BARS_FULL_WINDOW,
    RETURN_LONG_WINDOW,
    RETURN_SHORT_WINDOW,
    SMA_LONG_WINDOW,
    SMA_SHORT_WINDOW,
    TRADING_DAYS_PER_YEAR,
    VOLATILITY_SHORT_WINDOW,
    VOLUME_LONG_WINDOW,
    VOLUME_SHORT_WINDOW,
)
from app.data.provider import MarketSnapshot
from app.supervision.config import PROVENANCE_BY_DATA_SOURCE


@dataclass(frozen=True)
class Metric:
    value: float | None
    unit: str            # "decimal" | "multiple" | "usd" | "ratio"
    source: str          # "price_bars" | "fundamentals"
    window: str | None   # e.g. "20 bars"; None for undated fundamentals
    description: str


@dataclass(frozen=True)
class AgentSnapshot:
    symbol: str
    company_name: str
    data_source: str
    provenance: str
    is_simulated: bool
    observations: int
    first_date: str | None
    last_date: str | None
    data_issues: tuple[str, ...]
    warnings: tuple[str, ...]
    metrics: dict[str, Metric] = field(default_factory=dict)


class SnapshotIntegrityError(Exception):
    """The provider data cannot be mapped to a known provenance."""


def _clean(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, METRIC_DECIMALS)


def _ret(closes: np.ndarray, window: int) -> float | None:
    if len(closes) < window + 1 or closes[-window - 1] <= 0:
        return None
    return closes[-1] / closes[-window - 1] - 1


def _sma(closes: np.ndarray, window: int) -> float | None:
    return float(closes[-window:].mean()) if len(closes) >= window else None


def _volatility(closes: np.ndarray, returns: int | None) -> float | None:
    """Sample std of daily log returns x sqrt(252). `returns`: last N returns, None = all."""
    if len(closes) < MIN_BARS_FULL_WINDOW or (closes <= 0).any():
        return None
    log_returns = np.diff(np.log(closes))
    if returns is not None:
        if len(log_returns) < returns:
            return None
        log_returns = log_returns[-returns:]
    return float(np.std(log_returns, ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _max_drawdown(closes: np.ndarray) -> float | None:
    if len(closes) < MIN_BARS_FULL_WINDOW or (closes <= 0).any():
        return None
    peaks = np.maximum.accumulate(closes)
    return float(-(closes / peaks - 1).min())


def _current_drawdown(closes: np.ndarray) -> float | None:
    if len(closes) < MIN_BARS_FULL_WINDOW or (closes <= 0).any():
        return None
    return float(1 - closes[-1] / closes.max())


def _volume_ratio(volumes: np.ndarray) -> float | None:
    if len(volumes) < VOLUME_LONG_WINDOW:
        return None
    long_avg = float(volumes[-VOLUME_LONG_WINDOW:].mean())
    if long_avg <= 0:
        return None
    return float(volumes[-VOLUME_SHORT_WINDOW:].mean()) / long_avg


def _ratio_minus_one(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b <= 0:
        return None
    return a / b - 1


def build_agent_snapshot(snapshot: MarketSnapshot) -> AgentSnapshot:
    provenance = PROVENANCE_BY_DATA_SOURCE.get(snapshot.data_source)
    if provenance is None:
        raise SnapshotIntegrityError(f"no provenance mapping for data source '{snapshot.data_source}'")

    closes = np.array([bar.close for bar in snapshot.bars], dtype=float)
    volumes = np.array([bar.volume for bar in snapshot.bars], dtype=float)
    price = float(closes[-1]) if len(closes) else None
    sma20 = _sma(closes, SMA_SHORT_WINDOW)
    sma50 = _sma(closes, SMA_LONG_WINDOW)
    f = snapshot.fundamentals

    def price_metric(value, unit, window, description):
        return Metric(_clean(value), unit, "price_bars", window, description)

    def fundamental_metric(value, unit, description):
        return Metric(_clean(value), unit, "fundamentals", None, description)

    metrics = {
        "price_last": price_metric(price, "usd", "last bar", "Last close"),
        "return_20d": price_metric(_ret(closes, RETURN_SHORT_WINDOW), "decimal", "20 bars",
                                   "close[t] / close[t-20] - 1"),
        "return_60d": price_metric(_ret(closes, RETURN_LONG_WINDOW), "decimal", "60 bars",
                                   "close[t] / close[t-60] - 1"),
        "sma20": price_metric(sma20, "usd", "20 bars", "Mean of the last 20 closes"),
        "sma50": price_metric(sma50, "usd", "50 bars", "Mean of the last 50 closes"),
        "price_vs_sma20": price_metric(_ratio_minus_one(price, sma20), "decimal", "20 bars", "price / SMA20 - 1"),
        "sma20_vs_sma50": price_metric(_ratio_minus_one(sma20, sma50), "decimal", "50 bars", "SMA20 / SMA50 - 1"),
        "volatility_annualized": price_metric(_volatility(closes, None), "decimal", "full window",
                                              "Sample std of daily log returns x sqrt(252)"),
        "volatility_20d": price_metric(_volatility(closes, VOLATILITY_SHORT_WINDOW), "decimal", "20 returns",
                                       "Sample std of the last 20 daily log returns x sqrt(252)"),
        "max_drawdown": price_metric(_max_drawdown(closes), "decimal", "full window",
                                     "Largest peak-to-trough fall, positive magnitude"),
        "current_drawdown": price_metric(_current_drawdown(closes), "decimal", "full window",
                                         "1 - last close / highest close in the window"),
        "volume_ratio_20_60": price_metric(_volume_ratio(volumes), "ratio", "20 vs 60 bars",
                                           "Mean volume of the last 20 bars / mean of the last 60"),
        "revenue_growth": fundamental_metric(f.revenue_growth if f else None, "decimal",
                                             "Revenue growth reported by the dataset (single period)"),
        "earnings_growth": fundamental_metric(f.earnings_growth if f else None, "decimal",
                                              "Earnings growth reported by the dataset (single period)"),
        "profit_margin": fundamental_metric(f.profit_margin if f else None, "decimal",
                                            "Net profit margin reported by the dataset"),
        "pe_ratio": fundamental_metric(f.pe_ratio if f else None, "multiple",
                                       "Price / earnings reported by the dataset"),
    }

    warnings = []
    if f is not None:
        warnings.append("Fundamentals in the dataset are undated; they are combined with prices up to "
                        f"{snapshot.as_of.isoformat() if snapshot.as_of else 'unknown'} without a matching date.")
    else:
        warnings.append("No fundamentals available for this symbol.")
    if snapshot.is_simulated:
        warnings.append("Synthetic demo dataset: not market data. Evaluations are illustrative only.")

    return AgentSnapshot(
        symbol=snapshot.symbol,
        company_name=snapshot.company_name,
        data_source=snapshot.data_source,
        provenance=provenance,
        is_simulated=snapshot.is_simulated,
        observations=len(snapshot.bars),
        first_date=snapshot.bars[0].date.isoformat() if snapshot.bars else None,
        last_date=snapshot.as_of.isoformat() if snapshot.as_of else None,
        data_issues=tuple(snapshot.data_issues),
        warnings=tuple(warnings),
        metrics=metrics,
    )

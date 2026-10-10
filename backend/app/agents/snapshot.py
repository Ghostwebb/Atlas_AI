"""One shared, public snapshot per request: every strategy reads exactly these metrics.

Metrics are computed once from the provider's MarketSnapshot (no extra data queries per agent),
using only bars up to the last bar (no look-ahead). Values are rounded to METRIC_DECIMALS and the
strategies evaluate the rounded values, so every cited number is reproducible from the JSON.

Input policy (agents.v1.1). INPUTS are validated before any computation:
  - a close is valid when it is finite and strictly positive;
  - a volume is valid when it is finite and >= 0 (a zero-volume day is a valid observation);
  - every observation a metric uses must be valid. Returns use EVERY close from t-N to t (not only
    the two end points), the same rule as moving averages, because they are read as sustained
    movement over that window;
  - bars are never dropped, compressed, forward-filled or replaced. An invalid observation only
    affects the metrics whose window contains it.
A metric that cannot be computed is published with value null and a status:
  missing (absent in the dataset), insufficient_history (fewer bars than the window),
  invalid_input (an input in the window is not finite / not positive / negative volume),
  not_computable (a valid but unusable denominator, e.g. zero average volume).
Never 0, never a neutral placeholder.
"""

import math
from collections.abc import Sequence
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

OK, MISSING, INSUFFICIENT, INVALID, NOT_COMPUTABLE = (
    "ok", "missing", "insufficient_history", "invalid_input", "not_computable")
# When a derived metric has several failing inputs, the most severe cause is published.
_SEVERITY = {INVALID: 4, NOT_COMPUTABLE: 3, INSUFFICIENT: 2, MISSING: 1, OK: 0}


@dataclass(frozen=True)
class Metric:
    value: float | None
    unit: str            # "decimal" | "multiple" | "usd" | "ratio"
    source: str          # "price_bars" | "fundamentals"
    window: str | None   # e.g. "20 bars"; None for undated fundamentals
    description: str
    status: str = OK     # ok | missing | insufficient_history | invalid_input | not_computable
    issue: str | None = None


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


@dataclass(frozen=True)
class _Result:
    value: float | None
    status: str = OK
    issue: str | None = None


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _valid_price(x: float) -> bool:
    return math.isfinite(x) and x > 0


def _valid_volume(x: float) -> bool:
    return math.isfinite(x) and x >= 0


class _Series:
    """Validated windows over the bars, oldest first. Never modifies the series."""

    def __init__(self, dates: Sequence[str], closes: Sequence[float], volumes: Sequence[float]):
        self.dates, self.closes, self.volumes = list(dates), list(closes), list(volumes)

    def _window(self, values, size, valid, what):
        if size < 1 or len(values) < size:
            return None, _Result(None, INSUFFICIENT, f"needs {size} bars, {len(values)} available")
        start = len(values) - size
        bad = [self.dates[start + i] for i, x in enumerate(values[start:]) if not valid(x)]
        if bad:
            return None, _Result(None, INVALID, f"{len(bad)} invalid {what} in the {size}-bar window "
                                                f"(first {bad[0]})")
        return np.array(values[start:], dtype=float), None

    def closes_window(self, size):
        return self._window(self.closes, size, _valid_price, "close(s)")

    def volumes_window(self, size):
        return self._window(self.volumes, size, _valid_volume, "volume(s)")


def _round(result: _Result) -> _Result:
    if result.value is None:
        return result
    value = _finite(result.value)
    if value is None:
        return _Result(None, NOT_COMPUTABLE, "computation produced a non-finite value")
    return _Result(round(value, METRIC_DECIMALS), OK, None)


def _ret(series: _Series, n: int) -> _Result:
    window, failure = series.closes_window(n + 1)
    return failure or _Result(window[-1] / window[0] - 1)


def _sma(series: _Series, n: int) -> _Result:
    window, failure = series.closes_window(n)
    return failure or _Result(float(window.mean()))


def _volatility(series: _Series, returns: int | None) -> _Result:
    """Sample std of daily log returns x sqrt(252). `returns`: last N returns, None = whole window."""
    size = len(series.closes) if returns is None else returns + 1
    if returns is None and size < MIN_BARS_FULL_WINDOW:
        return _Result(None, INSUFFICIENT, f"needs {MIN_BARS_FULL_WINDOW} bars, {size} available")
    window, failure = series.closes_window(size)
    if failure:
        return failure
    return _Result(float(np.std(np.diff(np.log(window)), ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR))


def _full_window(series: _Series) -> tuple[np.ndarray | None, _Result | None]:
    if len(series.closes) < MIN_BARS_FULL_WINDOW:
        return None, _Result(None, INSUFFICIENT, f"needs {MIN_BARS_FULL_WINDOW} bars, {len(series.closes)} available")
    return series.closes_window(len(series.closes))


def _max_drawdown(series: _Series) -> _Result:
    window, failure = _full_window(series)
    return failure or _Result(float(-(window / np.maximum.accumulate(window) - 1).min()))


def _current_drawdown(series: _Series) -> _Result:
    window, failure = _full_window(series)
    return failure or _Result(float(1 - window[-1] / window.max()))


def _volume_ratio(series: _Series) -> _Result:
    window, failure = series.volumes_window(VOLUME_LONG_WINDOW)
    if failure:
        return failure
    long_avg = float(window.mean())
    if long_avg <= 0:
        return _Result(None, NOT_COMPUTABLE, f"average volume over {VOLUME_LONG_WINDOW} bars is zero")
    return _Result(float(window[-VOLUME_SHORT_WINDOW:].mean()) / long_avg)


def _derived(name_a: str, a: _Result, name_b: str, b: _Result) -> _Result:
    """a / b - 1, inheriting the most severe cause of its inputs (published in `issue`)."""
    failing = [(n, r) for n, r in ((name_a, a), (name_b, b)) if r.value is None]
    if failing:
        worst = max(failing, key=lambda item: _SEVERITY[item[1].status])[1].status
        return _Result(None, worst, "depends on " + ", ".join(f"{n} ({r.status})" for n, r in failing))
    return _Result(a.value / b.value - 1)


def _fundamental(value: float | None) -> _Result:
    if value is None:
        return _Result(None, MISSING, "not provided by the dataset")
    if _finite(value) is None:
        return _Result(None, INVALID, "non-finite value in the dataset")
    return _Result(float(value))


def build_agent_snapshot(snapshot: MarketSnapshot) -> AgentSnapshot:
    provenance = PROVENANCE_BY_DATA_SOURCE.get(snapshot.data_source)
    if provenance is None:
        raise SnapshotIntegrityError(f"no provenance mapping for data source '{snapshot.data_source}'")

    series = _Series([b.date.isoformat() for b in snapshot.bars], [float(b.close) for b in snapshot.bars],
                     [float(b.volume) for b in snapshot.bars])
    price_window, price_failure = series.closes_window(1)
    price = price_failure or _Result(float(price_window[-1]))
    # Unrounded inputs for the derived ratios (rounding happens once, on publication).
    sma20 = _sma(series, SMA_SHORT_WINDOW)
    sma50 = _sma(series, SMA_LONG_WINDOW)
    f = snapshot.fundamentals

    def metric(result: _Result, unit, source, window, description):
        result = _round(result)
        return Metric(result.value, unit, source, window, description, result.status, result.issue)

    def fundamental(value, unit, description):
        return metric(_fundamental(value), unit, "fundamentals", None, description)

    metrics = {
        "price_last": metric(price, "usd", "price_bars", "last bar", "Last close"),
        "return_20d": metric(_ret(series, RETURN_SHORT_WINDOW), "decimal", "price_bars", "20 bars",
                             "close[t] / close[t-20] - 1; every close in the window must be valid"),
        "return_60d": metric(_ret(series, RETURN_LONG_WINDOW), "decimal", "price_bars", "60 bars",
                             "close[t] / close[t-60] - 1; every close in the window must be valid"),
        "sma20": metric(sma20, "usd", "price_bars", "20 bars", "Mean of the last 20 closes"),
        "sma50": metric(sma50, "usd", "price_bars", "50 bars", "Mean of the last 50 closes"),
        "price_vs_sma20": metric(_derived("price_last", price, "sma20", sma20), "decimal", "price_bars", "20 bars",
                                 "price / SMA20 - 1"),
        "sma20_vs_sma50": metric(_derived("sma20", sma20, "sma50", sma50), "decimal", "price_bars", "50 bars",
                                 "SMA20 / SMA50 - 1"),
        "volatility_annualized": metric(_volatility(series, None), "decimal", "price_bars", "full window",
                                        "Sample std of daily log returns x sqrt(252)"),
        "volatility_20d": metric(_volatility(series, VOLATILITY_SHORT_WINDOW), "decimal", "price_bars", "20 returns",
                                 "Sample std of the last 20 daily log returns x sqrt(252)"),
        "max_drawdown": metric(_max_drawdown(series), "decimal", "price_bars", "full window",
                               "Largest peak-to-trough fall, positive magnitude"),
        "current_drawdown": metric(_current_drawdown(series), "decimal", "price_bars", "full window",
                                   "1 - last close / highest close in the window"),
        "volume_ratio_20_60": metric(_volume_ratio(series), "ratio", "price_bars", "20 vs 60 bars",
                                     "Mean volume of the last 20 bars / mean of the last 60"),
        "revenue_growth": fundamental(f.revenue_growth if f else None, "decimal",
                                      "Revenue growth reported by the dataset (single period)"),
        "earnings_growth": fundamental(f.earnings_growth if f else None, "decimal",
                                       "Earnings growth reported by the dataset (single period)"),
        "profit_margin": fundamental(f.profit_margin if f else None, "decimal",
                                     "Net profit margin reported by the dataset"),
        "pe_ratio": fundamental(f.pe_ratio if f else None, "multiple", "Price / earnings reported by the dataset"),
    }

    warnings = []
    if f is not None:
        warnings.append("Fundamentals in the dataset are undated; they are combined with prices up to "
                        f"{snapshot.as_of.isoformat() if snapshot.as_of else 'unknown'} without a matching date.")
    else:
        warnings.append("No fundamentals available for this symbol.")
    invalid = [key for key, m in metrics.items() if m.status == INVALID]
    if invalid:
        warnings.append("Invalid input observations: " + ", ".join(invalid) + " could not be computed.")
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

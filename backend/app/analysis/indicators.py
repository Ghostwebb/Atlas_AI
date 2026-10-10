"""Pure indicator functions. Each returns None when there is not enough data.

Inputs are pandas Series of closing prices, oldest first. Nothing here invents
values: missing inputs produce None, never a default number.
"""

import math

import numpy as np
import pandas as pd

from app.analysis.config import TRADING_DAYS_PER_YEAR


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def period_change(closes: pd.Series) -> float | None:
    """Simple return from the first to the last close: last / first - 1."""
    if len(closes) < 2 or closes.iloc[0] == 0:
        return None
    return float(closes.iloc[-1] / closes.iloc[0] - 1)


def simple_moving_average(closes: pd.Series, window: int) -> float | None:
    """Mean of the last `window` closes."""
    if window < 1 or len(closes) < window:
        return None
    return float(closes.iloc[-window:].mean())


def annualized_volatility(closes: pd.Series) -> float | None:
    """Sample std dev of daily log returns, times sqrt(252)."""
    if len(closes) < 3:
        return None
    log_returns = np.log(closes).diff().dropna()
    daily_std = float(log_returns.std(ddof=1))
    if math.isnan(daily_std):
        return None
    return daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(closes: pd.Series) -> float | None:
    """Largest peak-to-trough fall, returned as a positive magnitude (0.12 = -12%)."""
    if len(closes) < 2:
        return None
    running_peak = closes.cummax()
    drawdowns = closes / running_peak - 1
    return float(-drawdowns.min())

"""Technical analyzer: momentum and trend from closing prices.

Formulas are documented in README.md ("Análisis técnico").
"""

from dataclasses import dataclass

import pandas as pd

from app.analysis.config import (
    LABEL_BAND,
    LONG_MA_WINDOW,
    MIN_BARS_REQUIRED,
    MOMENTUM_SCALE,
    SHORT_MA_WINDOW,
    TREND_SCALE,
)
from app.analysis.indicators import clamp, period_change, simple_moving_average


@dataclass(frozen=True)
class MomentumResult:
    label: str            # "positive" | "neutral" | "negative"
    score: float          # [-1, 1]
    change_percent: float # period change in percent units (8.4 = +8.4%)


@dataclass(frozen=True)
class TrendResult:
    label: str            # "bullish" | "neutral" | "bearish"
    score: float          # [-1, 1]
    short_moving_average: float
    long_moving_average: float
    price_vs_short_ma: float  # price / SMA20 - 1
    price_vs_long_ma: float   # price / SMA50 - 1


def _momentum_label(score: float) -> str:
    if score >= LABEL_BAND:
        return "positive"
    if score <= -LABEL_BAND:
        return "negative"
    return "neutral"


def _trend_label(score: float) -> str:
    if score >= LABEL_BAND:
        return "bullish"
    if score <= -LABEL_BAND:
        return "bearish"
    return "neutral"


def analyze_momentum(closes: pd.Series) -> MomentumResult | None:
    change = period_change(closes)
    if change is None:
        return None
    score = clamp(change / MOMENTUM_SCALE)
    return MomentumResult(
        label=_momentum_label(score),
        score=round(score, 4),
        change_percent=round(change * 100, 2),
    )


def analyze_trend(closes: pd.Series) -> TrendResult | None:
    if len(closes) < MIN_BARS_REQUIRED:
        return None

    short_ma = simple_moving_average(closes, SHORT_MA_WINDOW)
    long_ma = simple_moving_average(closes, LONG_MA_WINDOW)
    if short_ma is None or long_ma is None:
        return None

    price = float(closes.iloc[-1])
    gap_moving_averages = clamp((short_ma / long_ma - 1) / TREND_SCALE)
    gap_price_to_short = clamp((price / short_ma - 1) / TREND_SCALE)
    score = (gap_moving_averages + gap_price_to_short) / 2

    return TrendResult(
        label=_trend_label(score),
        score=round(score, 4),
        short_moving_average=round(short_ma, 2),
        long_moving_average=round(long_ma, 2),
        price_vs_short_ma=round(price / short_ma - 1, 4),
        price_vs_long_ma=round(price / long_ma - 1, 4),
    )

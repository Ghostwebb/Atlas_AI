"""Fundamental analyzer: a small set of demo metrics mapped to [-1, 1].

Missing metrics are EXCLUDED from the score. They are never treated as
positive or negative evidence.
"""

from dataclasses import dataclass

from app.analysis.config import (
    EARNINGS_GROWTH_BAD,
    EARNINGS_GROWTH_GOOD,
    LABEL_BAND,
    PE_RATIO_BAD,
    PE_RATIO_GOOD,
    PROFIT_MARGIN_BAD,
    PROFIT_MARGIN_GOOD,
    REVENUE_GROWTH_BAD,
    REVENUE_GROWTH_GOOD,
)
from app.analysis.indicators import clamp
from app.data.provider import Fundamentals


@dataclass(frozen=True)
class FundamentalResult:
    label: str                       # "positive" | "neutral" | "negative"
    score: float                     # [-1, 1], mean of available metric scores
    metrics_used: int                # how many of the 4 metrics contributed
    revenue_growth: float | None
    profit_margin: float | None
    pe_ratio: float | None
    earnings_growth: float | None


def _linear(value: float, bad: float, good: float) -> float:
    """Map `bad` to -1, `good` to +1, linearly and clamped. Works in reverse too."""
    return clamp(-1 + 2 * (value - bad) / (good - bad))


def _label(score: float) -> str:
    if score >= LABEL_BAND:
        return "positive"
    if score <= -LABEL_BAND:
        return "negative"
    return "neutral"


def analyze_fundamentals(fundamentals: Fundamentals | None) -> FundamentalResult | None:
    if fundamentals is None:
        return None

    metric_scores: list[float] = []
    if fundamentals.revenue_growth is not None:
        metric_scores.append(
            _linear(fundamentals.revenue_growth, REVENUE_GROWTH_BAD, REVENUE_GROWTH_GOOD)
        )
    if fundamentals.profit_margin is not None:
        metric_scores.append(
            _linear(fundamentals.profit_margin, PROFIT_MARGIN_BAD, PROFIT_MARGIN_GOOD)
        )
    if fundamentals.pe_ratio is not None:
        # Reversed: a lower P/E is more favorable.
        metric_scores.append(_linear(fundamentals.pe_ratio, PE_RATIO_BAD, PE_RATIO_GOOD))
    if fundamentals.earnings_growth is not None:
        metric_scores.append(
            _linear(fundamentals.earnings_growth, EARNINGS_GROWTH_BAD, EARNINGS_GROWTH_GOOD)
        )

    if not metric_scores:
        return None

    score = sum(metric_scores) / len(metric_scores)
    return FundamentalResult(
        label=_label(score),
        score=round(score, 4),
        metrics_used=len(metric_scores),
        revenue_growth=fundamentals.revenue_growth,
        profit_margin=fundamentals.profit_margin,
        pe_ratio=fundamentals.pe_ratio,
        earnings_growth=fundamentals.earnings_growth,
    )

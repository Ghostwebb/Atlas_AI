"""Risk analyzer: historical volatility, max drawdown and a rule-based label.

Educational metrics only. They describe past behaviour and do not predict
future volatility or losses.
"""

from dataclasses import dataclass

import pandas as pd

from app.analysis.config import (
    DRAWDOWN_REFERENCE,
    RISK_DRAWDOWN_WEIGHT,
    RISK_LOW_MAX,
    RISK_MODERATE_MAX,
    RISK_VOLATILITY_WEIGHT,
    VOLATILITY_REFERENCE,
)
from app.analysis.indicators import annualized_volatility, clamp, max_drawdown


@dataclass(frozen=True)
class RiskResult:
    label: str           # "low" | "moderate" | "high"
    risk_score: float    # [0, 1], higher = riskier
    volatility: float    # annualized, decimal (0.24 = 24%)
    max_drawdown: float  # positive magnitude (0.12 = 12% peak-to-trough fall)
    signal_score: float  # [-1, 1] passed to the aggregator; low risk = positive


def _risk_label(risk_score: float) -> str:
    if risk_score < RISK_LOW_MAX:
        return "low"
    if risk_score < RISK_MODERATE_MAX:
        return "moderate"
    return "high"


def analyze_risk(closes: pd.Series) -> RiskResult | None:
    volatility = annualized_volatility(closes)
    drawdown = max_drawdown(closes)
    if volatility is None or drawdown is None:
        return None

    risk_score = min(
        1.0,
        RISK_VOLATILITY_WEIGHT * volatility / VOLATILITY_REFERENCE
        + RISK_DRAWDOWN_WEIGHT * drawdown / DRAWDOWN_REFERENCE,
    )
    return RiskResult(
        label=_risk_label(risk_score),
        risk_score=round(risk_score, 4),
        volatility=round(volatility, 4),
        max_drawdown=round(drawdown, 4),
        signal_score=round(clamp(1 - 2 * risk_score), 4),
    )

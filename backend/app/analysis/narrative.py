"""Deterministic, template-based explanations.

No language model is used. Every number in the text comes directly from the
analysis results, so the explanation cannot invent figures.
"""

from app.analysis.aggregate import AggregateResult
from app.analysis.config import BUY_THRESHOLD, SELL_THRESHOLD
from app.analysis.fundamental import FundamentalResult
from app.analysis.risk import RiskResult
from app.analysis.technical import MomentumResult, TrendResult

DISCLAIMER = (
    "Educational analysis of synthetic demo data. It is not investment advice "
    "and does not guarantee returns."
)


def _pct(value: float, digits: int = 0) -> str:
    return f"{value * 100:.{digits}f}%"


def momentum_sentence(result: MomentumResult | None) -> str:
    if result is None:
        return "Momentum is unavailable: not enough price history."
    return (
        f"Momentum is {result.label}: the price changed {result.change_percent:+.1f}% "
        "over the demo period."
    )


def trend_sentence(result: TrendResult | None) -> str:
    if result is None:
        return "Trend is unavailable: at least 50 closing prices are required."
    relation = "above" if result.short_moving_average > result.long_moving_average else "below"
    return (
        f"Trend is {result.label}: the 20-day average ({result.short_moving_average:.2f}) "
        f"is {relation} the 50-day average ({result.long_moving_average:.2f})."
    )


def risk_sentence(result: RiskResult | None) -> str:
    if result is None:
        return "Risk is unavailable: not enough price history."
    return (
        f"Risk is {result.label}: annualized historical volatility is "
        f"{_pct(result.volatility)} and the largest peak-to-trough fall was "
        f"{_pct(result.max_drawdown)}."
    )


def fundamental_sentence(result: FundamentalResult | None) -> str:
    if result is None:
        return "Fundamental data is unavailable and is not counted in the score."
    return (
        f"Fundamentals are {result.label} based on {result.metrics_used} of 4 demo metrics."
    )


def build_summary(
    company_name: str,
    momentum: MomentumResult | None,
    trend: TrendResult | None,
    risk: RiskResult | None,
    recommendation: str,
) -> str:
    momentum_part = f"{momentum.label} momentum" if momentum else "unavailable momentum"
    trend_part = f"a {trend.label} trend" if trend else "an unavailable trend"
    risk_part = f"{risk.label} risk" if risk else "unavailable risk"
    return (
        f"{company_name} shows {momentum_part} and {trend_part} with {risk_part} "
        f"on the demo dataset. The composite signal points to {recommendation}."
    )


def build_explanation(
    momentum: MomentumResult | None,
    trend: TrendResult | None,
    risk: RiskResult | None,
    fundamental: FundamentalResult | None,
    aggregate: AggregateResult,
    data_issues: list[str],
) -> list[str]:
    lines = [
        momentum_sentence(momentum),
        trend_sentence(trend),
        risk_sentence(risk),
        fundamental_sentence(fundamental),
        (
            f"Composite score {aggregate.composite:+.2f} on a -1 to +1 scale. "
            f"BUY at or above {BUY_THRESHOLD:+.2f}, SELL at or below {SELL_THRESHOLD:+.2f}, "
            f"HOLD in between. Result: {aggregate.recommendation}."
        ),
        (
            f"Confidence {aggregate.confidence:.2f} = data coverage {aggregate.coverage:.2f} "
            f"x signal agreement {aggregate.agreement:.2f}. It measures data completeness and "
            "consistency, not the probability of a correct outcome."
        ),
    ]
    if aggregate.missing_components:
        lines.append(
            "Components without enough data and excluded from the score: "
            + ", ".join(aggregate.missing_components)
            + "."
        )
    lines.extend(f"Data issue: {issue}" for issue in data_issues)
    lines.append(DISCLAIMER)
    return lines

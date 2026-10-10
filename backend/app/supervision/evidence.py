"""Evidence extraction: polarity of each signal and its relation to the recommendation.

Two separate ideas are kept apart:

- Polarity (market reading of the signal, independent of the recommendation):
  momentum/fundamental positive and trend bullish are favorable; negative and
  bearish are unfavorable; neutral is neutral. Risk: low is favorable, high is
  unfavorable, moderate is neutral.
- Direction (relation to the engine recommendation), decided by this policy:

  Directional components (momentum, trend, fundamental):
    BUY  : favorable -> supporting, unfavorable -> opposing, neutral -> neutral
    SELL : unfavorable -> supporting, favorable -> opposing, neutral -> neutral
    HOLD : neutral -> supporting (consistent with no directional view).
           If favorable AND unfavorable signals are both present, they offset
           each other, so all of them support HOLD.
           If only one polarity is present, those signals lean away from a
           neutral stance and are opposing.

  Risk (volatility and drawdown describe the asset; they are not a direction):
    BUY  : low -> supporting, high -> opposing, moderate -> neutral
    SELL : always neutral. High risk is not a reason to sell, and low risk is
           not evidence against selling. SELL never means opening a short position.
    HOLD : always neutral.
  High risk is listed in the report's riskFactors for every recommendation.

Unavailable components are not evidence; they are reported as data gaps.
Descriptions only cite metrics that are present, and every cited metric has a
reference that resolves in the public response.
"""

from app.analysis.config import LONG_MA_WINDOW, SHORT_MA_WINDOW
from app.supervision.config import COMPONENT_ORDER, EXPECTED_FUNDAMENTAL_METRICS
from app.supervision.models import Direction, EvidenceItem, Polarity, SupervisionInput

DIRECTIONAL_COMPONENTS = ("momentum", "trend", "fundamental")

_POLARITY_BY_LABEL: dict[str, dict[str, Polarity]] = {
    "momentum": {"positive": Polarity.FAVORABLE, "negative": Polarity.UNFAVORABLE,
                 "neutral": Polarity.NEUTRAL},
    "trend": {"bullish": Polarity.FAVORABLE, "bearish": Polarity.UNFAVORABLE,
              "neutral": Polarity.NEUTRAL},
    "risk": {"low": Polarity.FAVORABLE, "high": Polarity.UNFAVORABLE,
             "moderate": Polarity.NEUTRAL},
    "fundamental": {"positive": Polarity.FAVORABLE, "negative": Polarity.UNFAVORABLE,
                    "neutral": Polarity.NEUTRAL},
}


def _pct(value: float, digits: int = 0) -> str:
    # round() then + 0.0 normalizes -0.0, so a zero never prints as "-0%".
    return f"{round(value * 100, digits) + 0.0:.{digits}f}%"


def _relation(a: float, b: float) -> str:
    if a > b:
        return "above"
    if a < b:
        return "below"
    return "equal to"


def _label_of(inp: SupervisionInput, component: str) -> str:
    return {
        "momentum": inp.momentum_label,
        "trend": inp.trend_label,
        "risk": inp.risk_label,
        "fundamental": inp.fundamental_label,
    }[component]


def polarity_of(inp: SupervisionInput, component: str) -> Polarity | None:
    """None when the component is unavailable."""
    return _POLARITY_BY_LABEL[component].get(_label_of(inp, component))


def describe(inp: SupervisionInput, component: str) -> tuple[str, list[str]]:
    """Return (description, refs). Missing metrics are omitted, never shown as zero."""
    label = _label_of(inp, component)
    refs = [f"signals.{component}"]

    if component == "momentum":
        refs.append("analysis.momentum.score")
        if inp.momentum_change_percent is None:
            return f"Momentum is {label}.", refs
        refs.append("analysis.momentum.changePercent")
        return (
            f"Momentum is {label} ({inp.momentum_change_percent:+.1f}% over the analysis period).",
            refs,
        )

    if component == "trend":
        refs.append("analysis.trend.score")
        sentences = [f"Trend is {label}."]
        short_ma, long_ma = inp.short_moving_average, inp.long_moving_average
        if short_ma is not None and long_ma is not None:
            refs += ["analysis.trend.shortMovingAverage", "analysis.trend.longMovingAverage"]
            sentences.append(
                f"The {SHORT_MA_WINDOW}-day average ({short_ma:.2f}) is "
                f"{_relation(short_ma, long_ma)} the {LONG_MA_WINDOW}-day average ({long_ma:.2f})."
            )
        if inp.price_vs_short_ma is not None:
            refs.append("analysis.trend.priceVsShortMovingAverage")
            gap = inp.price_vs_short_ma
            if gap == 0:
                sentences.append(f"The price equals the {SHORT_MA_WINDOW}-day average.")
            else:
                side = "above" if gap > 0 else "below"
                sentences.append(
                    f"The price is {_pct(abs(gap), 1)} {side} the {SHORT_MA_WINDOW}-day average."
                )
        return " ".join(sentences), refs

    if component == "risk":
        refs.append("analysis.risk.score")
        parts = []
        if inp.volatility is not None:
            refs.append("analysis.risk.volatility")
            parts.append(f"annualized volatility {_pct(inp.volatility)}")
        if inp.max_drawdown is not None:
            refs.append("analysis.risk.maxDrawdown")
            parts.append(f"maximum drawdown {_pct(inp.max_drawdown)}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Historical risk is {label}{detail}.", refs

    if component == "fundamental":
        refs += [
            "analysis.fundamental.score",
            "analysis.fundamental.metricsUsed",
            "supervision.dataQuality.expectedFundamentalMetrics",
        ]
        return (
            f"Fundamentals are {label} based on {inp.fundamental_metrics_used} of "
            f"{EXPECTED_FUNDAMENTAL_METRICS} metrics.",
            refs,
        )

    raise ValueError(f"unknown component: {component}")


def hold_has_offsetting_signals(inp: SupervisionInput) -> bool:
    polarities = {polarity_of(inp, c) for c in DIRECTIONAL_COMPONENTS}
    return Polarity.FAVORABLE in polarities and Polarity.UNFAVORABLE in polarities


def direction_for(inp: SupervisionInput, component: str, polarity: Polarity) -> Direction:
    recommendation = inp.engine_recommendation

    if component == "risk":
        if recommendation == "BUY":
            return {
                Polarity.FAVORABLE: Direction.SUPPORTING,
                Polarity.UNFAVORABLE: Direction.OPPOSING,
            }.get(polarity, Direction.NEUTRAL)
        return Direction.NEUTRAL

    if recommendation == "BUY":
        return {
            Polarity.FAVORABLE: Direction.SUPPORTING,
            Polarity.UNFAVORABLE: Direction.OPPOSING,
        }.get(polarity, Direction.NEUTRAL)
    if recommendation == "SELL":
        return {
            Polarity.UNFAVORABLE: Direction.SUPPORTING,
            Polarity.FAVORABLE: Direction.OPPOSING,
        }.get(polarity, Direction.NEUTRAL)

    # HOLD
    if polarity is Polarity.NEUTRAL:
        return Direction.SUPPORTING
    return Direction.SUPPORTING if hold_has_offsetting_signals(inp) else Direction.OPPOSING


def build_evidence(
    inp: SupervisionInput,
) -> tuple[list[EvidenceItem], list[EvidenceItem], list[EvidenceItem]]:
    """Return (supporting, opposing, neutral) evidence in fixed component order.

    Each available component appears in exactly one list.
    """
    lists: dict[Direction, list[EvidenceItem]] = {d: [] for d in Direction}

    for component in COMPONENT_ORDER:
        polarity = polarity_of(inp, component)
        if polarity is None:
            continue
        description, refs = describe(inp, component)
        direction = direction_for(inp, component, polarity)
        lists[direction].append(
            EvidenceItem(
                component=component,
                polarity=polarity,
                direction=direction,
                description=description,
                refs=refs,
            )
        )

    return lists[Direction.SUPPORTING], lists[Direction.OPPOSING], lists[Direction.NEUTRAL]

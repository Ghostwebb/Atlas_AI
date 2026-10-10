"""Normalized evidence extraction. Labels decide direction; numbers only describe it.

Neutral and unavailable components are not evidence and are not listed.
"""

from app.supervision.models import Direction, EvidenceItem, SupervisionInput

# label -> direction, per component
_DIRECTION_BY_LABEL: dict[str, dict[str, Direction]] = {
    "momentum": {
        "positive": Direction.SUPPORTING,
        "negative": Direction.OPPOSING,
        "neutral": Direction.NEUTRAL,
    },
    "trend": {
        "bullish": Direction.SUPPORTING,
        "bearish": Direction.OPPOSING,
        "neutral": Direction.NEUTRAL,
    },
    "risk": {
        "low": Direction.SUPPORTING,
        "high": Direction.OPPOSING,
        "moderate": Direction.NEUTRAL,
    },
    "fundamental": {
        "positive": Direction.SUPPORTING,
        "negative": Direction.OPPOSING,
        "neutral": Direction.NEUTRAL,
    },
}


def _pct(value: float, digits: int = 0) -> str:
    return f"{value * 100:.{digits}f}%"


def _describe(inp: SupervisionInput, component: str, label: str) -> str:
    if component == "momentum":
        change = inp.momentum_change_percent or 0.0
        return f"Momentum is {label} ({change:+.1f}% over the demo period)."
    if component == "trend":
        return f"Trend is {label}: the 20-day average is {'above' if label == 'bullish' else 'below'} the 50-day average."
    if component == "risk":
        vol = inp.volatility or 0.0
        if label == "high":
            dd = inp.max_drawdown or 0.0
            return f"Risk is high (annualized volatility {_pct(vol)}, largest fall {_pct(dd)})."
        return f"Risk is {label} (annualized volatility {_pct(vol)})."
    if component == "fundamental":
        return f"Fundamentals are {label} based on {inp.fundamental_metrics_used} of 4 demo metrics."
    raise ValueError(f"unknown component: {component}")


def _refs(component: str) -> list[str]:
    refs = [f"signals.{component}"]
    if component == "momentum":
        refs.append("analysis.momentum.score")
        refs.append("analysis.momentum.changePercent")
    elif component == "trend":
        refs.append("analysis.trend.score")
    elif component == "risk":
        refs.append("analysis.risk.score")
        refs.append("analysis.risk.volatility")
    elif component == "fundamental":
        refs.append("analysis.fundamental.score")
        refs.append("analysis.fundamental.metricsUsed")
    return refs


def _label_of(inp: SupervisionInput, component: str) -> str:
    return {
        "momentum": inp.momentum_label,
        "trend": inp.trend_label,
        "risk": inp.risk_label,
        "fundamental": inp.fundamental_label,
    }[component]


def build_evidence(inp: SupervisionInput) -> tuple[list[EvidenceItem], list[EvidenceItem]]:
    """Return (supporting, opposing) evidence in fixed component order."""
    supporting: list[EvidenceItem] = []
    opposing: list[EvidenceItem] = []

    for component in ("momentum", "trend", "risk", "fundamental"):
        label = _label_of(inp, component)
        direction = _DIRECTION_BY_LABEL[component].get(label)
        if direction in (None, Direction.NEUTRAL):
            continue
        item = EvidenceItem(
            component=component,
            direction=direction,
            description=_describe(inp, component, label),
            refs=_refs(component),
        )
        (supporting if direction is Direction.SUPPORTING else opposing).append(item)

    return supporting, opposing

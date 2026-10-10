"""Pure supervision rules and input integrity checks.

Each rule is a pure function of `SupervisionInput`. It returns at most one
Finding, so a rule cannot emit duplicates. Thresholds come from config.py.
"""

import math

from app.analysis.config import MIN_BARS_REQUIRED, WEIGHTS
from app.supervision.config import (
    CONFIDENCE_LOW_THRESHOLD,
    DIRECTION_MIN_MAGNITUDE,
    EXPECTED_FUNDAMENTAL_METRICS,
    SEVERITY_RANK,
)
from app.supervision.models import Finding, FindingCategory, Severity, SupervisionInput


def _side(score: float | None, minimum: float = DIRECTION_MIN_MAGNITUDE) -> int:
    """+1 / -1 for a directional score, 0 for absent or near-zero."""
    if score is None:
        return 0
    if score >= minimum:
        return 1
    if score <= -minimum:
        return -1
    return 0


# --- Integrity ------------------------------------------------------------

def integrity_issues(inp: SupervisionInput) -> list[str]:
    """Return problems that make the report unreliable. Empty list = valid.

    NaN, infinity and out-of-range values are reported, never silently
    converted to zero.
    """
    issues: list[str] = []

    numeric = {
        "confidence": inp.confidence,
        "momentum.score": inp.momentum_score,
        "momentum.changePercent": inp.momentum_change_percent,
        "trend.score": inp.trend_score,
        "trend.shortMovingAverage": inp.short_moving_average,
        "trend.longMovingAverage": inp.long_moving_average,
        "risk.score": inp.risk_score,
        "risk.volatility": inp.volatility,
        "risk.maxDrawdown": inp.max_drawdown,
        "fundamental.score": inp.fundamental_score,
    }
    for name, value in numeric.items():
        if value is not None and not math.isfinite(value):
            issues.append(f"{name} is not finite ({value})")

    def check_range(name: str, value: float | None, low: float, high: float) -> None:
        if value is not None and math.isfinite(value) and not (low <= value <= high):
            issues.append(f"{name} out of range [{low}, {high}]: {value}")

    check_range("confidence", inp.confidence, 0.0, 1.0)
    check_range("momentum.score", inp.momentum_score, -1.0, 1.0)
    check_range("trend.score", inp.trend_score, -1.0, 1.0)
    check_range("fundamental.score", inp.fundamental_score, -1.0, 1.0)
    check_range("risk.score", inp.risk_score, 0.0, 1.0)
    check_range("risk.maxDrawdown", inp.max_drawdown, 0.0, 1.0)
    if inp.volatility is not None and math.isfinite(inp.volatility) and inp.volatility < 0:
        issues.append(f"risk.volatility is negative: {inp.volatility}")

    if inp.engine_recommendation not in {"BUY", "HOLD", "SELL"}:
        issues.append(f"unknown engine recommendation: {inp.engine_recommendation}")

    # Internal consistency: a component is available iff its score exists.
    core = {
        "momentum": (inp.momentum_label, inp.momentum_score),
        "trend": (inp.trend_label, inp.trend_score),
        "risk": (inp.risk_label, inp.risk_score),
    }
    enough_history = inp.dataset.observations >= MIN_BARS_REQUIRED
    for name, (label, score) in core.items():
        available = label != "unavailable"
        if available != (score is not None):
            issues.append(f"{name} label and score disagree")
        if not available and enough_history:
            issues.append(f"{name} unavailable although history is sufficient")

    fundamental_available = inp.fundamental_label != "unavailable"
    if fundamental_available != (inp.fundamental_score is not None):
        issues.append("fundamental label and score disagree")
    present_metrics = sum(1 for value in inp.fundamental_raw_values if value is not None)
    if present_metrics != inp.fundamental_metrics_used:
        issues.append(
            f"fundamental metricsUsed={inp.fundamental_metrics_used} "
            f"but {present_metrics} metric values are present"
        )

    return issues


# --- Conflict rules -------------------------------------------------------

def rule_momentum_trend_divergence(inp: SupervisionInput) -> Finding | None:
    momentum_side = _side(inp.momentum_score)
    trend_side = _side(inp.trend_score)
    if momentum_side == 0 or trend_side == 0 or momentum_side == trend_side:
        return None

    if momentum_side > 0:
        message = f"Positive momentum coexists with a {inp.trend_label} trend."
    else:
        message = f"Negative momentum coexists with a {inp.trend_label} trend."
    return Finding(
        ruleId="MOMENTUM_TREND_DIVERGENCE",
        category=FindingCategory.CONTRADICTION,
        severity=Severity.WARNING,
        title="Momentum and trend disagree",
        message=message,
        evidenceRefs=["analysis.momentum.score", "analysis.trend.score"],
    )


def rule_technical_fundamental_divergence(inp: SupervisionInput) -> Finding | None:
    if inp.momentum_score is None or inp.trend_score is None or inp.fundamental_score is None:
        return None

    # Same weights the engine uses for its technical block; no new weighting is invented.
    technical_weight = WEIGHTS["momentum"] + WEIGHTS["trend"]
    technical_composite = (
        WEIGHTS["momentum"] * inp.momentum_score + WEIGHTS["trend"] * inp.trend_score
    ) / technical_weight

    technical_side = _side(technical_composite)
    fundamental_side = _side(inp.fundamental_score)
    if technical_side == 0 or fundamental_side == 0 or technical_side == fundamental_side:
        return None

    technical_word = "favorable" if technical_side > 0 else "unfavorable"
    fundamental_word = "favorable" if fundamental_side > 0 else "unfavorable"
    return Finding(
        ruleId="TECHNICAL_FUNDAMENTAL_DIVERGENCE",
        category=FindingCategory.CONTRADICTION,
        severity=Severity.WARNING,
        title="Technical and fundamental signals disagree",
        message=(
            f"The technical block is {technical_word} while the demo fundamentals are "
            f"{fundamental_word}."
        ),
        evidenceRefs=[
            "analysis.trend.score",
            "analysis.momentum.score",
            "analysis.fundamental.score",
        ],
    )


def rule_opportunity_risk_conflict(inp: SupervisionInput) -> Finding | None:
    if inp.engine_recommendation != "BUY" or inp.risk_label != "high":
        return None
    return Finding(
        ruleId="OPPORTUNITY_RISK_CONFLICT",
        category=FindingCategory.CAUTION,
        severity=Severity.WARNING,
        title="Favorable signal with high historical risk",
        message=(
            "The engine recommendation is BUY while historical risk is high. "
            "This is a conflict between favorable signals and risk, not a "
            "statement that the recommendation is wrong."
        ),
        evidenceRefs=["recommendation", "signals.risk", "analysis.risk.score"],
    )


# --- Data-gap rules -------------------------------------------------------

def rule_history_insufficient(inp: SupervisionInput) -> Finding | None:
    if inp.dataset.observations >= inp.dataset.requiredObservations:
        return None
    return Finding(
        ruleId="HISTORY_INSUFFICIENT",
        category=FindingCategory.DATA_GAP,
        severity=Severity.WARNING,
        title="Not enough price history",
        message=(
            f"{inp.dataset.observations} observations are available; "
            f"{inp.dataset.requiredObservations} are required for the technical indicators."
        ),
        evidenceRefs=["dataset.observations", "dataset.requiredObservations"],
    )


def rule_fundamentals_gap(inp: SupervisionInput) -> Finding | None:
    refs = ["signals.fundamental", "analysis.fundamental.metricsUsed"]
    if inp.fundamental_label == "unavailable":
        return Finding(
            ruleId="FUNDAMENTALS_MISSING",
            category=FindingCategory.DATA_GAP,
            severity=Severity.INFO,
            title="No fundamental data",
            message="No fundamental metrics are available; they are not counted in the score.",
            evidenceRefs=refs,
        )
    if inp.fundamental_metrics_used < EXPECTED_FUNDAMENTAL_METRICS:
        return Finding(
            ruleId="FUNDAMENTALS_PARTIAL",
            category=FindingCategory.DATA_GAP,
            severity=Severity.INFO,
            title="Partial fundamental data",
            message=(
                f"{inp.fundamental_metrics_used} of {EXPECTED_FUNDAMENTAL_METRICS} "
                "fundamental metrics are available."
            ),
            evidenceRefs=refs,
        )
    return None


# --- Observation -----------------------------------------------------------

def rule_low_confidence(inp: SupervisionInput, has_conflicts: bool) -> Finding | None:
    """Explain low confidence, but only when no conflict already explains it."""
    if has_conflicts or inp.confidence >= CONFIDENCE_LOW_THRESHOLD:
        return None
    return Finding(
        ruleId="LOW_CONFIDENCE",
        category=FindingCategory.OBSERVATION,
        severity=Severity.INFO,
        title="Low confidence score",
        message=(
            f"Confidence is {inp.confidence:.2f}, below {CONFIDENCE_LOW_THRESHOLD:.2f}. "
            "It reflects data coverage and signal agreement, not the probability of a correct outcome."
        ),
        evidenceRefs=["confidence"],
    )


CONFLICT_RULES = (
    rule_momentum_trend_divergence,
    rule_technical_fundamental_divergence,
    rule_opportunity_risk_conflict,
)
GAP_RULES = (
    rule_history_insufficient,
    rule_fundamentals_gap,
)


def evaluate_rules(inp: SupervisionInput) -> list[Finding]:
    """Run every rule, drop duplicates and return findings in stable order."""
    findings: list[Finding] = []
    for rule in CONFLICT_RULES + GAP_RULES:
        finding = rule(inp)
        if finding is not None:
            findings.append(finding)

    has_conflicts = any(
        f.category in (FindingCategory.CONTRADICTION, FindingCategory.CAUTION) for f in findings
    )
    low_confidence = rule_low_confidence(inp, has_conflicts)
    if low_confidence is not None:
        findings.append(low_confidence)

    unique: dict[str, Finding] = {}
    for finding in findings:
        unique.setdefault(finding.ruleId, finding)

    return sorted(
        unique.values(),
        key=lambda f: (SEVERITY_RANK[f.severity.value], f.ruleId),
    )

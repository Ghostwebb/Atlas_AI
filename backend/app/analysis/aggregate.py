"""Signal aggregator: combines component scores into one recommendation.

FORMULAS (all documented in README.md):

  composite  = sum(w_i * s_i) / sum(w_i)        over AVAILABLE components only
  coverage   = sum(w_i) / sum(all weights)      share of the weighting backed by data
  agreement  = 1 - min(1, stdev(s_i))           how consistently components agree
  confidence = coverage * agreement             rounded to 2 decimals

Confidence describes data coverage and signal consistency. It is NOT the
probability that the recommendation will be right.

  composite >= BUY_THRESHOLD   -> BUY
  composite <= SELL_THRESHOLD  -> SELL
  otherwise                    -> HOLD
"""

import statistics
from dataclasses import dataclass, field

from app.analysis.config import BUY_THRESHOLD, SELL_THRESHOLD, WEIGHTS


@dataclass(frozen=True)
class AggregateResult:
    recommendation: str                     # "BUY" | "HOLD" | "SELL"
    composite: float                        # [-1, 1]
    coverage: float                         # [0, 1]
    agreement: float                        # [0, 1]
    confidence: float                       # [0, 1]
    used_components: list[str] = field(default_factory=list)
    missing_components: list[str] = field(default_factory=list)


def aggregate(component_scores: dict[str, float | None]) -> AggregateResult:
    """Combine component scores. A `None` score means the component is unavailable."""
    available = {name: score for name, score in component_scores.items() if score is not None}
    missing = [name for name in WEIGHTS if name not in available]

    if not available:
        return AggregateResult(
            recommendation="HOLD",
            composite=0.0,
            coverage=0.0,
            agreement=0.0,
            confidence=0.0,
            missing_components=missing,
        )

    total_weight = sum(WEIGHTS.values())
    available_weight = sum(WEIGHTS[name] for name in available)
    composite = sum(WEIGHTS[name] * score for name, score in available.items()) / available_weight

    coverage = available_weight / total_weight
    scores = list(available.values())
    spread = statistics.pstdev(scores) if len(scores) > 1 else 0.0
    agreement = 1 - min(1.0, spread)
    confidence = round(coverage * agreement, 2)

    if composite >= BUY_THRESHOLD:
        recommendation = "BUY"
    elif composite <= SELL_THRESHOLD:
        recommendation = "SELL"
    else:
        recommendation = "HOLD"

    return AggregateResult(
        recommendation=recommendation,
        composite=round(composite, 4),
        coverage=round(coverage, 4),
        agreement=round(agreement, 4),
        confidence=confidence,
        used_components=list(available),
        missing_components=missing,
    )

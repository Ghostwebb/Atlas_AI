"""Evidence quality: coverage, data-quality label and limitations.

Two different units are kept apart on purpose:
- componentCoverage = available score-bearing components / 4 (a count ratio).
- fundamentalCoverage = available fundamental metrics / 4 (a count ratio).
- The engine's `confidence` uses WEIGHTED coverage (see analysis/aggregate.py),
  so with fundamentals missing it is 0.80 weighted but 0.75 as a count. This is
  intentional; each number is labelled for what it measures.
"""

from app.analysis.config import MIN_BARS_REQUIRED
from app.supervision.config import (
    COMPONENT_ORDER,
    CORE_TECHNICAL_COMPONENTS,
    EXPECTED_FUNDAMENTAL_METRICS,
)
from app.supervision.models import (
    DataQuality,
    Limitation,
    Provenance,
    QualityLabel,
    SupervisionInput,
    SupervisorStatus,
)


def _component_available(inp: SupervisionInput, name: str) -> bool:
    label = {
        "momentum": inp.momentum_label,
        "trend": inp.trend_label,
        "risk": inp.risk_label,
        "fundamental": inp.fundamental_label,
    }[name]
    return label != "unavailable"


def build_data_quality(inp: SupervisionInput, status: SupervisorStatus) -> DataQuality:
    available = [name for name in COMPONENT_ORDER if _component_available(inp, name)]
    missing = [name for name in COMPONENT_ORDER if name not in available]

    component_coverage = len(available) / len(COMPONENT_ORDER)
    fundamental_coverage = inp.fundamental_metrics_used / EXPECTED_FUNDAMENTAL_METRICS

    if status is SupervisorStatus.INSUFFICIENT_DATA:
        label = QualityLabel.INSUFFICIENT
    elif component_coverage < 1.0 or fundamental_coverage < 1.0:
        label = QualityLabel.LIMITED
    else:
        label = QualityLabel.SUFFICIENT

    return DataQuality(
        label=label,
        componentCoverage=round(component_coverage, 4),
        availableComponents=available,
        missingComponents=missing,
        fundamentalCoverage=round(fundamental_coverage, 4),
        availableFundamentalMetrics=inp.fundamental_metrics_used,
        expectedFundamentalMetrics=EXPECTED_FUNDAMENTAL_METRICS,
        historicalObservations=inp.dataset.observations,
        requiredHistoricalObservations=MIN_BARS_REQUIRED,
        provenance=Provenance(inp.dataset.provenance),
        firstDate=inp.dataset.firstDate,
        lastDate=inp.dataset.lastDate,
    )


def build_limitations(inp: SupervisionInput, quality: DataQuality) -> list[Limitation]:
    limitations: list[Limitation] = []
    if quality.provenance is Provenance.SYNTHETIC:
        limitations.append(
            Limitation(
                code="SYNTHETIC_DATA",
                message="Prices and fundamentals come from a synthetic demo dataset.",
            )
        )
    if inp.fundamental_label == "unavailable":
        limitations.append(
            Limitation(
                code="FUNDAMENTALS_MISSING",
                message="Fundamental metrics are unavailable and are not counted in the score.",
            )
        )
    elif inp.fundamental_metrics_used < EXPECTED_FUNDAMENTAL_METRICS:
        limitations.append(
            Limitation(
                code="FUNDAMENTALS_PARTIAL",
                message=(
                    f"Only {inp.fundamental_metrics_used} of {EXPECTED_FUNDAMENTAL_METRICS} "
                    "fundamental metrics are available."
                ),
            )
        )
    limitations.append(
        Limitation(
            code="NON_PREDICTIVE",
            message=(
                "Rules and thresholds are educational. They describe past demo data "
                "and do not predict returns."
            ),
        )
    )
    return limitations


def core_components_missing(inp: SupervisionInput) -> bool:
    return any(not _component_available(inp, name) for name in CORE_TECHNICAL_COMPONENTS)

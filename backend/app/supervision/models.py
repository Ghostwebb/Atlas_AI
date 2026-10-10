"""Supervisor public models and internal input types.

Public models (Pydantic) form the `supervision` block of the API response.
`SupervisionInput` is an internal, immutable view of already-computed results;
rules read only from it. The supervisor never fetches data or recomputes
indicators.
"""

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SupervisorStatus(str, Enum):
    CONSISTENT = "consistent"
    CAUTION = "caution"
    INSUFFICIENT_DATA = "insufficient_data"


class Direction(str, Enum):
    SUPPORTING = "supporting"
    OPPOSING = "opposing"
    NEUTRAL = "neutral"


class QualityLabel(str, Enum):
    SUFFICIENT = "sufficient"
    LIMITED = "limited"
    INSUFFICIENT = "insufficient"


class Provenance(str, Enum):
    SYNTHETIC = "synthetic"
    HISTORICAL = "historical"
    LIVE = "live"


class FindingCategory(str, Enum):
    CONTRADICTION = "contradiction"  # two signals point in opposite directions
    CAUTION = "caution"              # favorable signal alongside a material risk
    DATA_GAP = "data_gap"            # something is missing from the evidence base
    OBSERVATION = "observation"      # informational; never changes the status


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetInfo(_Model):
    """Structured facts about the dataset the analysis was computed from."""

    observations: int
    requiredObservations: int
    firstDate: str | None
    lastDate: str | None
    provenance: Provenance
    dataSource: str


class EvidenceItem(_Model):
    component: str
    direction: Direction
    description: str
    refs: list[str]


class Finding(_Model):
    ruleId: str
    category: FindingCategory
    severity: Severity
    title: str
    message: str
    evidenceRefs: list[str]


class Limitation(_Model):
    code: str
    message: str


class DataQuality(_Model):
    label: QualityLabel
    componentCoverage: float
    availableComponents: list[str]
    missingComponents: list[str]
    fundamentalCoverage: float
    availableFundamentalMetrics: int
    expectedFundamentalMetrics: int
    historicalObservations: int
    requiredHistoricalObservations: int
    provenance: Provenance
    firstDate: str | None
    lastDate: str | None


class Report(_Model):
    headline: str
    summary: str
    keyReasons: list[str]
    riskFactors: list[str]
    dataGaps: list[str]


class SupervisionReport(_Model):
    schemaVersion: str
    policyVersion: str
    status: SupervisorStatus
    engineRecommendation: str
    dataQuality: DataQuality
    findings: list[Finding]
    supportingEvidence: list[EvidenceItem]
    opposingEvidence: list[EvidenceItem]
    limitations: list[Limitation]
    report: Report


class SupervisionIntegrityError(Exception):
    """Raised when inputs are invalid enough that a reliable report cannot be issued."""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


@dataclass(frozen=True)
class SupervisionInput:
    """Immutable view of the computed analysis. Built once; rules only read it."""

    engine_recommendation: str
    confidence: float

    momentum_label: str
    momentum_score: float | None
    momentum_change_percent: float | None

    trend_label: str
    trend_score: float | None
    short_moving_average: float | None
    long_moving_average: float | None

    risk_label: str
    risk_score: float | None
    volatility: float | None
    max_drawdown: float | None

    fundamental_label: str
    fundamental_score: float | None
    fundamental_metrics_used: int
    # revenueGrowth, profitMargin, peRatio, earningsGrowth (None = unavailable)
    fundamental_raw_values: tuple[float | None, ...]

    dataset: DatasetInfo

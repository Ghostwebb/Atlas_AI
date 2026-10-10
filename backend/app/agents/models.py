"""Public contract of POST /api/agents/analyze (schema agents.v1)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.symbols import normalize_symbol


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentsAnalyzeRequest(_Strict):
    symbol: str = Field(..., min_length=1, max_length=12, examples=["NVDA"])

    @field_validator("symbol")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_symbol(value)


class MetricOut(_Strict):
    value: float | None = Field(..., description="null = unavailable (never 0); see status")
    status: Literal["ok", "missing", "insufficient_history", "invalid_input", "not_computable"]
    issue: str | None = Field(..., description="Cause when status is not ok (affected window, first date)")
    unit: Literal["decimal", "multiple", "usd", "ratio"]
    source: Literal["price_bars", "fundamentals"]
    window: str | None
    description: str


class SnapshotOut(_Strict):
    symbol: str
    companyName: str
    dataSource: str
    provenance: Literal["synthetic", "historical", "live"]
    isSimulated: bool
    observations: int
    firstDate: str | None
    lastDate: str | None
    dataIssues: list[str]
    warnings: list[str]
    metrics: dict[str, MetricOut]


class Reference(_Strict):
    path: str = Field(..., description="JSON path inside this response, e.g. snapshot.metrics.pe_ratio")
    value: float | None
    unit: str


class EvidenceItem(_Strict):
    id: str
    criterion: str
    label: str
    direction: Literal["favorable", "neutral", "unfavorable"]
    weight: float
    core: bool
    rule: str
    statement: str
    references: list[Reference]


Unavailable = Literal["missing", "insufficient_history", "invalid_input", "not_computable"]


class NotEvaluatedItem(_Strict):
    id: str
    criterion: str
    label: str
    reason: Literal["missing", "insufficient_history", "invalid_input", "not_computable", "not_interpretable"]
    weight: float
    core: bool
    statement: str
    references: list[Reference]


class RiskItem(_Strict):
    id: str
    statement: str
    references: list[Reference]


class RiskNotEvaluatedItem(_Strict):
    id: str
    reason: Unavailable
    statement: str
    references: list[Reference]


class Evidence(_Strict):
    favorable: list[EvidenceItem]
    unfavorable: list[EvidenceItem]
    neutral: list[EvidenceItem]


class StrategyEvaluation(_Strict):
    strategyId: Literal["argo", "nova", "vector", "aegis"]
    name: str
    style: str
    version: str
    lens: str
    stanceMeaning: str
    status: Literal["complete", "partial", "insufficient"]
    stance: Literal["favorable", "neutral", "unfavorable", "insufficient_data"]
    score: float | None = Field(..., ge=-1, le=1, description="Weighted mean of criterion points in [-1, 1]")
    coverage: float = Field(..., ge=0, le=1,
                            description="Share of the weight of the SCORED criteria that could be evaluated; "
                                        "it does not cover risk checks (see risksNotEvaluated)")
    evidence: Evidence
    notEvaluated: list[NotEvaluatedItem]
    risks: list[RiskItem]
    risksNotEvaluated: list[RiskNotEvaluatedItem]
    missingData: list[str]
    limitations: list[str]


class AgentsAnalyzeResponse(_Strict):
    schemaVersion: Literal["agents.v1.1"]
    notice: str
    snapshot: SnapshotOut
    evaluations: list[StrategyEvaluation]
    limitations: list[str]

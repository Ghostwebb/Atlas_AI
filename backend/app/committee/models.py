"""Public contract of POST /api/committee/analyze (schema committee.v1)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.models import AgentsAnalyzeRequest, AgentsAnalyzeResponse


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommitteeAnalyzeRequest(AgentsAnalyzeRequest):
    """Only a symbol (normalized like /api/analyze). Extra fields are rejected."""


StrategyId = Literal["argo", "nova", "vector", "aegis"]
Direction = Literal["favorable", "unfavorable", "neutral"]


class CommitteeReference(_Strict):
    source: Literal["evidence", "risk", "risk_not_evaluated", "not_evaluated"]
    id: str = Field(..., description="Id of the cited agents item (evidence, risk or not-evaluated criterion)")
    strategyId: StrategyId
    criterion: str | None
    direction: Direction | None
    path: str = Field(..., description="agents.snapshot.metrics.<id> inside this response")
    value: float | None
    unit: str


class Finding(_Strict):
    id: str
    kind: str
    statement: str
    references: list[CommitteeReference]
    level: Literal["stance", "criterion", "risk"] | None = None


class Abstention(_Strict):
    id: str
    strategyId: StrategyId
    reason: Literal["insufficient"]
    causes: list[str]
    statement: str
    references: list[CommitteeReference]


class Participant(_Strict):
    strategyId: StrategyId
    role: Literal["opportunity", "risk"]
    status: Literal["complete", "partial", "insufficient"]
    stance: Literal["favorable", "neutral", "unfavorable", "insufficient_data"]
    coverage: float
    participates: bool


class Agreement(_Strict):
    id: str
    direction: Literal["favorable", "unfavorable"]
    strategies: list[StrategyId]
    independentBases: int
    bases: list[list[StrategyId]]
    statement: str


class Citation(_Strict):
    evidenceId: str
    strategyId: StrategyId
    direction: Direction


class SharedEvidence(_Strict):
    path: str
    citedBy: list[Citation]
    statement: str


class Requirement(_Strict):
    id: str
    met: bool
    statement: str


class Condition(_Strict):
    id: str
    statement: str


class MissingData(_Strict):
    metric: str
    path: str
    strategyId: StrategyId
    status: str


class Conclusion(_Strict):
    state: Literal["insufficient_data", "conflicted", "aligned_unfavorable", "aligned_favorable", "caution", "neutral"]
    policyVersion: str
    rulesApplied: list[str]
    summary: str
    requirements: list[Requirement]
    notice: str


class Committee(_Strict):
    conclusion: Conclusion
    participants: list[Participant]
    abstentions: list[Abstention]
    agreements: list[Agreement]
    conflicts: list[Finding]
    observations: list[Finding]
    arguments: list[Finding]
    counterpoints: list[Finding]
    observedRisks: list[Finding]
    riskProfile: list[Finding]
    unevaluatedRisks: list[Finding]
    missingData: list[MissingData]
    sharedEvidence: list[SharedEvidence]
    conditions: list[Condition]
    limitations: list[str]


class CommitteeAnalyzeResponse(_Strict):
    schemaVersion: Literal["committee.v1"]
    policyVersion: str
    notice: str
    agents: AgentsAnalyzeResponse
    committee: Committee

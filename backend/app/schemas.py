"""Pydantic models defining the API contract shared with the frontend.

Phase 2 keeps every Phase 1 field. It adds `analysis`, `explanation`,
`dataSource`, `dataAsOf`, `dataIssues` and `signals.fundamental`.
Unavailable components use label "unavailable" and null metrics; they are
never converted into a positive or negative signal.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.supervision.models import SupervisionReport
from app.symbols import normalize_symbol


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., min_length=1, max_length=12, examples=["NVDA"])

    @field_validator("symbol")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_symbol(value)


class MomentumAnalysis(BaseModel):
    label: Literal["positive", "neutral", "negative", "unavailable"]
    score: float | None
    changePercent: float | None = Field(None, description="Period change in percent units")


class TrendAnalysis(BaseModel):
    label: Literal["bullish", "neutral", "bearish", "unavailable"]
    score: float | None
    shortMovingAverage: float | None
    longMovingAverage: float | None
    priceVsShortMovingAverage: float | None = Field(None, description="price / SMA20 - 1")
    priceVsLongMovingAverage: float | None = Field(None, description="price / SMA50 - 1")


class RiskAnalysis(BaseModel):
    label: Literal["low", "moderate", "high", "unavailable"]
    score: float | None = Field(None, description="Risk score in [0, 1], higher = riskier")
    volatility: float | None = Field(None, description="Annualized, decimal (0.24 = 24%)")
    maxDrawdown: float | None = Field(None, description="Positive magnitude (0.12 = -12%)")


class FundamentalAnalysis(BaseModel):
    label: Literal["positive", "neutral", "negative", "unavailable"]
    score: float | None
    metricsUsed: int
    revenueGrowth: float | None
    profitMargin: float | None
    peRatio: float | None
    earningsGrowth: float | None


class AnalysisDetails(BaseModel):
    momentum: MomentumAnalysis
    trend: TrendAnalysis
    risk: RiskAnalysis
    fundamental: FundamentalAnalysis


class Signals(BaseModel):
    momentum: Literal["positive", "neutral", "negative", "unavailable"]
    risk: Literal["low", "moderate", "high", "unavailable"]
    trend: Literal["bullish", "neutral", "bearish", "unavailable"]
    fundamental: Literal["positive", "neutral", "negative", "unavailable"]


class AnalyzeResponse(BaseModel):
    symbol: str
    companyName: str
    recommendation: Literal["BUY", "HOLD", "SELL"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    summary: str
    explanation: list[str]
    signals: Signals
    analysis: AnalysisDetails
    isSimulated: Literal[True]
    dataSource: str
    dataAsOf: str | None
    dataIssues: list[str]
    # Additive in Phase 3. Always present in analyze responses; optional only so
    # the analysis can be built before the supervisor runs.
    supervision: SupervisionReport | None = None


class ErrorResponse(BaseModel):
    error: str
    message: str

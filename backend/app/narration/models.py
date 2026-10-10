"""Narration models: evidence packet, model output schema and public contract."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.narration.config import (
    MAX_EVIDENCE_IDS_PER_POINT,
    MAX_OVERVIEW_CHARS,
    MAX_POINT_CHARS,
    MAX_POINTS_PER_SECTION,
    MAX_TITLE_CHARS,
)
from app.schemas import AnalyzeResponse
from app.symbols import normalize_symbol

Language = Literal["es", "en"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Request ---------------------------------------------------------------

class ReportRequest(_Strict):
    symbol: str = Field(..., min_length=1, max_length=12, examples=["NVDA"])
    language: Language = "es"

    @field_validator("symbol")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_symbol(value)


# --- Evidence packet (what the model sees) -----------------------------------

class PacketMetric(_Strict):
    id: str
    evidenceId: str
    name: str
    value: float | int | None
    unit: str


class PacketItem(_Strict):
    id: str
    section: Literal["supporting", "counterpoint", "risk", "dataGap", "limitation", "context"]
    polarity: Literal["favorable", "unfavorable", "neutral"] | None
    text: str


class EvidencePacket(_Strict):
    symbol: str
    companyName: str
    recommendation: Literal["BUY", "HOLD", "SELL"]
    confidence: float
    confidenceMeaning: str
    supervisorStatus: str
    supervisorStatusMeaning: str
    provenance: str
    isSimulated: bool
    firstDate: str | None
    lastDate: str | None
    componentCoverage: float
    fundamentalCoverage: float
    metrics: list[PacketMetric]
    items: list[PacketItem]


# --- Model output (validated strictly) ------------------------------------

class NarrativePoint(_Strict):
    text: str = Field(..., min_length=1, max_length=MAX_POINT_CHARS)
    evidenceIds: list[str] = Field(..., min_length=1, max_length=MAX_EVIDENCE_IDS_PER_POINT)


class OverviewPoint(NarrativePoint):
    text: str = Field(..., min_length=1, max_length=MAX_OVERVIEW_CHARS)


class NarrativeReport(_Strict):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_CHARS)
    overview: OverviewPoint
    supportingReasons: list[NarrativePoint] = Field(..., max_length=MAX_POINTS_PER_SECTION)
    counterpoints: list[NarrativePoint] = Field(..., max_length=MAX_POINTS_PER_SECTION)
    riskFactors: list[NarrativePoint] = Field(..., max_length=MAX_POINTS_PER_SECTION)
    dataGaps: list[NarrativePoint] = Field(..., max_length=MAX_POINTS_PER_SECTION)
    limitations: list[NarrativePoint] = Field(..., max_length=MAX_POINTS_PER_SECTION)


# --- Public contract --------------------------------------------------------

class NarrativeStatus(str, Enum):
    GENERATED = "generated"
    FALLBACK = "fallback"
    DISABLED = "disabled"


class ReasonCode(str, Enum):
    MODEL_DISABLED = "MODEL_DISABLED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_BUSY = "MODEL_BUSY"
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"


class NarrativeReason(_Strict):
    code: ReasonCode
    message: str


class NarrativeFacts(_Strict):
    """Copied from the deterministic backend; never taken from model text."""

    recommendation: Literal["BUY", "HOLD", "SELL"]
    confidence: float
    supervisorStatus: str
    provenance: str
    isSimulated: bool
    dataAsOf: str | None


class Narrative(_Strict):
    schemaVersion: str
    promptVersion: str
    supervisorPolicyVersion: str
    status: NarrativeStatus
    generationMode: Literal["llm", "deterministic"]
    model: str | None
    language: Language
    reason: NarrativeReason | None
    facts: NarrativeFacts
    report: NarrativeReport


class ReportResponse(_Strict):
    analysis: AnalyzeResponse
    narrative: Narrative

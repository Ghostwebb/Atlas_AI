"""Pydantic models defining the API contract shared with the frontend."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.symbols import normalize_symbol


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., min_length=1, max_length=12, examples=["NVDA"])

    @field_validator("symbol")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_symbol(value)


class Signals(BaseModel):
    momentum: Literal["positive", "neutral", "negative"]
    risk: Literal["low", "moderate", "high"]
    trend: Literal["positive", "neutral", "negative"]


class AnalyzeResponse(BaseModel):
    symbol: str
    companyName: str
    recommendation: Literal["BUY", "HOLD", "SELL"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    summary: str
    signals: Signals
    isSimulated: Literal[True]


class ErrorResponse(BaseModel):
    error: str
    message: str

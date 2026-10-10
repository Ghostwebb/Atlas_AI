"""Paper trading domain and contract models.

Money and quantities are Decimal in the domain and decimal strings in JSON.
Amount fields only accept JSON strings: numbers (floats) are rejected.

Three lifecycles are kept apart:
  ProposalStatus    open -> confirmed | expired       (the user's decision)
  SubmissionStatus  local view of the send to Alpaca
  BrokerOrderStatus Alpaca's order status, as reported by Alpaca
"""

import re
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.paper.config import MIN_NOTIONAL_USD, NOTIONAL_PATTERN, QTY_PATTERN
from app.symbols import is_valid_format, normalize_symbol


class Environment(str, Enum):
    PAPER = "paper"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class ProposalStatus(str, Enum):
    OPEN = "open"            # prepared, awaiting explicit confirmation
    CONFIRMED = "confirmed"  # the user confirmed; see submissionStatus
    EXPIRED = "expired"      # TTL elapsed before confirmation


class SubmissionStatus(str, Enum):
    NOT_SUBMITTED = "not_submitted"
    SUBMITTING = "submitting"                  # intent persisted, request in flight
    SUBMITTED = "submitted"                    # Alpaca returned an order
    SUBMISSION_UNKNOWN = "submission_unknown"  # Alpaca may or may not have the order
    REJECTED_BY_BROKER = "rejected_by_broker"  # explicit 4xx from Alpaca
    FAILED_BEFORE_SUBMIT = "failed_before_submit"  # connection never established


class BrokerOrderStatus(str, Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    DONE_FOR_DAY = "done_for_day"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"
    PENDING_REPLACE = "pending_replace"
    ACCEPTED = "accepted"
    PENDING_NEW = "pending_new"
    ACCEPTED_FOR_BIDDING = "accepted_for_bidding"
    STOPPED = "stopped"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    CALCULATED = "calculated"
    UNRECOGNIZED = "unrecognized"  # a status this version does not know

    @classmethod
    def parse(cls, value: str | None) -> "BrokerOrderStatus":
        try:
            return cls(value)
        except ValueError:
            return cls.UNRECOGNIZED


TERMINAL_BROKER_STATUSES = {
    BrokerOrderStatus.FILLED, BrokerOrderStatus.CANCELED, BrokerOrderStatus.EXPIRED,
    BrokerOrderStatus.REJECTED, BrokerOrderStatus.REPLACED,
}


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_CONFIRMATION = "INVALID_CONFIRMATION"
    PAPER_DISABLED = "PAPER_DISABLED"
    PAPER_NOT_CONFIGURED = "PAPER_NOT_CONFIGURED"
    BROKER_UNAVAILABLE = "BROKER_UNAVAILABLE"
    ACCOUNT_NOT_TRADABLE = "ACCOUNT_NOT_TRADABLE"
    MARKET_CLOSED = "MARKET_CLOSED"
    ASSET_NOT_SUPPORTED = "ASSET_NOT_SUPPORTED"
    FRACTIONAL_NOT_SUPPORTED = "FRACTIONAL_NOT_SUPPORTED"
    ORDER_LIMIT_EXCEEDED = "ORDER_LIMIT_EXCEEDED"
    INSUFFICIENT_BUYING_POWER = "INSUFFICIENT_BUYING_POWER"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
    PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
    SUBMISSION_IN_PROGRESS = "SUBMISSION_IN_PROGRESS"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    BROKER_REJECTED = "BROKER_REJECTED"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_NOT_CANCELABLE = "ORDER_NOT_CANCELABLE"
    ORIGIN_NOT_ALLOWED = "ORIGIN_NOT_ALLOWED"


ERROR_STATUS = {
    ErrorCode.INVALID_REQUEST: 400, ErrorCode.INVALID_CONFIRMATION: 400,
    ErrorCode.ORIGIN_NOT_ALLOWED: 403,
    ErrorCode.PROPOSAL_NOT_FOUND: 404, ErrorCode.ORDER_NOT_FOUND: 404,
    ErrorCode.MARKET_CLOSED: 409, ErrorCode.PROPOSAL_EXPIRED: 409,
    ErrorCode.SUBMISSION_IN_PROGRESS: 409, ErrorCode.SUBMISSION_UNCERTAIN: 409,
    ErrorCode.ORDER_NOT_CANCELABLE: 409,
    ErrorCode.ACCOUNT_NOT_TRADABLE: 422, ErrorCode.ASSET_NOT_SUPPORTED: 422,
    ErrorCode.FRACTIONAL_NOT_SUPPORTED: 422, ErrorCode.ORDER_LIMIT_EXCEEDED: 422,
    ErrorCode.INSUFFICIENT_BUYING_POWER: 422, ErrorCode.INSUFFICIENT_POSITION: 422,
    ErrorCode.BROKER_REJECTED: 422,
    ErrorCode.PAPER_DISABLED: 503, ErrorCode.PAPER_NOT_CONFIGURED: 503,
    ErrorCode.BROKER_UNAVAILABLE: 503,
}


class PaperError(Exception):
    """Domain error with a stable code and a public, sanitized message."""

    def __init__(self, code: ErrorCode, message: str, proposal_id: str | None = None):
        self.code = code
        self.message = message
        self.proposal_id = proposal_id
        super().__init__(f"{code.value}: {message}")

    @property
    def http_status(self) -> int:
        return ERROR_STATUS[self.code]


class PaperErrorResponse(BaseModel):
    error: str
    message: str
    code: ErrorCode
    correlationId: str
    proposalId: str | None = None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Requests ---------------------------------------------------------------

_ANALYSIS_REF = re.compile(r"^[A-Za-z0-9._:@-]{1,64}$")


class ProposalRequest(_Strict):
    symbol: str = Field(..., min_length=1, max_length=12)
    side: Side
    notional: str | None = Field(None, max_length=12, description="USD, buy only, e.g. '100.00'")
    qty: str | None = Field(None, max_length=20, description="Shares, sell only, e.g. '0.5'")
    analysisReference: str | None = Field(None, max_length=64)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        value = normalize_symbol(value)
        if not is_valid_format(value):
            raise ValueError("invalid symbol")
        return value

    @field_validator("notional")
    @classmethod
    def _notional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(NOTIONAL_PATTERN, value):
            raise ValueError("notional must be a decimal string with at most 2 decimals")
        if Decimal(value) < MIN_NOTIONAL_USD:
            raise ValueError(f"notional must be at least {MIN_NOTIONAL_USD}")
        return value

    @field_validator("qty")
    @classmethod
    def _qty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(QTY_PATTERN, value):
            raise ValueError("qty must be a decimal string with at most 9 decimals")
        if Decimal(value) <= 0:
            raise ValueError("qty must be positive")
        return value

    @field_validator("analysisReference")
    @classmethod
    def _reference(cls, value: str | None) -> str | None:
        if value is not None and not _ANALYSIS_REF.fullmatch(value):
            raise ValueError("invalid analysisReference")
        return value

    @model_validator(mode="after")
    def _one_amount(self) -> "ProposalRequest":
        if self.side is Side.BUY and (self.notional is None or self.qty is not None):
            raise ValueError("a buy requires notional and no qty")
        if self.side is Side.SELL and (self.qty is None or self.notional is not None):
            raise ValueError("a sell requires qty and no notional")
        return self


class ConfirmRequest(_Strict):
    confirmation: Literal["CONFIRM_PAPER_ORDER"]


class CancelRequest(_Strict):
    confirmation: Literal["CANCEL_PAPER_ORDER"]


# --- Responses --------------------------------------------------------------

class Check(_Strict):
    name: str
    passed: bool
    detail: str


class Proposal(_Strict):
    id: str
    environment: Environment
    symbol: str
    side: Side
    notional: Decimal | None
    qty: Decimal | None
    orderType: Literal["market"]
    timeInForce: Literal["day"]
    clientOrderId: str
    analysisReference: str | None
    createdAt: str
    expiresAt: str
    status: ProposalStatus
    submissionStatus: SubmissionStatus
    brokerOrderId: str | None
    brokerStatus: BrokerOrderStatus | None
    filledQty: Decimal | None
    filledAvgPrice: Decimal | None
    lastErrorCode: ErrorCode | None
    checks: list[Check]
    warnings: list[str]
    updatedAt: str


class BrokerOrder(_Strict):
    id: str
    clientOrderId: str
    symbol: str
    side: str
    type: str
    timeInForce: str
    qty: Decimal | None
    notional: Decimal | None
    filledQty: Decimal | None
    filledAvgPrice: Decimal | None
    status: BrokerOrderStatus
    brokerStatusRaw: str
    submittedAt: str | None
    filledAt: str | None
    canceledAt: str | None
    proposalId: str | None = None  # set when the order was created by ATLAS
    environment: Environment = Environment.PAPER


class Account(_Strict):
    environment: Environment = Environment.PAPER
    status: str
    currency: str
    cash: Decimal | None
    buyingPower: Decimal | None
    nonMarginableBuyingPower: Decimal | None
    equity: Decimal | None
    tradingBlocked: bool
    accountBlocked: bool


class Position(_Strict):
    environment: Environment = Environment.PAPER
    symbol: str
    side: str
    qty: Decimal
    qtyAvailable: Decimal | None
    avgEntryPrice: Decimal | None
    marketValue: Decimal | None
    assetClass: str | None


class Clock(_Strict):
    isOpen: bool
    timestamp: str | None
    nextOpen: str | None
    nextClose: str | None


class Asset(_Strict):
    symbol: str
    assetClass: str
    status: str
    tradable: bool
    fractionable: bool


class PaperStatus(_Strict):
    environment: Environment = Environment.PAPER
    enabled: bool
    configured: bool
    brokerReachable: bool | None
    marketOpen: bool | None
    maxOrderNotionalUsd: Decimal
    proposalTtlSeconds: int
    analysisDataNotice: str
    message: str

"""HTTP routes for paper trading under /api/paper.

Mutating routes (create, confirm, reconcile, cancel) require an Origin header
from the configured CORS origins. CORS and this Origin check reduce cross-site
misuse from browsers; they are NOT authentication. This backend is a local
application and must not be exposed publicly without real auth.
"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.paper.config import DEFAULT_ORDERS_PAGE, MAX_ORDERS_PAGE
from app.paper.models import (
    Account,
    BrokerOrder,
    CancelRequest,
    Clock,
    ConfirmRequest,
    ErrorCode,
    PaperError,
    PaperErrorResponse,
    PaperStatus,
    Position,
    Proposal,
    ProposalRequest,
)
from app.paper.service import PaperTradingService

router = APIRouter(prefix="/api/paper", tags=["paper"])

_state: dict = {"service": None, "origins": ()}

ERROR_TITLES = {400: "Invalid paper trading request", 403: "Paper trading request not allowed",
                404: "Paper trading resource not found", 409: "Paper trading state conflict",
                422: "Paper trading validation error", 503: "Paper trading unavailable"}


def configure(service: PaperTradingService, allowed_origins: list[str]) -> None:
    _state["service"] = service
    _state["origins"] = tuple(allowed_origins)


def get_service() -> PaperTradingService:
    return _state["service"]


def correlation_id() -> str:
    return uuid.uuid4().hex


def error_response(error: PaperError, cid: str) -> JSONResponse:
    status = error.http_status
    body = PaperErrorResponse(error=ERROR_TITLES[status], message=error.message, code=error.code,
                              correlationId=cid, proposalId=error.proposal_id)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"),
                        headers={"X-Correlation-Id": cid})


def check_origin(request: Request, service: PaperTradingService) -> None:
    origin = request.headers.get("origin")
    if origin is None and service.settings.allow_requests_without_origin:
        return
    if origin is None or origin not in _state["origins"]:
        raise PaperError(ErrorCode.ORIGIN_NOT_ALLOWED,
                         "Mutating paper trading requests must come from an allowed origin.")


def _run(fn, cid: str):
    try:
        return fn()
    except PaperError as error:
        return error_response(error, cid)


_ERRORS = {code: {"model": PaperErrorResponse} for code in (400, 403, 404, 409, 422, 503)}


@router.get("/status", response_model=PaperStatus)
def status(service: PaperTradingService = Depends(get_service)):
    return service.status()


@router.get("/account", response_model=Account, responses=_ERRORS)
def account(service: PaperTradingService = Depends(get_service), cid: str = Depends(correlation_id)):
    return _run(service.account, cid)


@router.get("/clock", response_model=Clock, responses=_ERRORS)
def clock(service: PaperTradingService = Depends(get_service), cid: str = Depends(correlation_id)):
    return _run(service.clock, cid)


@router.get("/positions", response_model=list[Position], responses=_ERRORS)
def positions(service: PaperTradingService = Depends(get_service), cid: str = Depends(correlation_id)):
    return _run(service.positions, cid)


def _guarded(request: Request, service: PaperTradingService, cid: str, fn):
    try:
        check_origin(request, service)
        return fn()
    except PaperError as error:
        return error_response(error, cid)


@router.post("/proposals", response_model=Proposal, status_code=201, responses=_ERRORS)
def create_proposal(payload: ProposalRequest, request: Request,
                    service: PaperTradingService = Depends(get_service),
                    cid: str = Depends(correlation_id)):
    return _guarded(request, service, cid, lambda: service.create_proposal(payload, cid))


@router.get("/proposals/{proposal_id}", response_model=Proposal, responses=_ERRORS)
def get_proposal(proposal_id: str, service: PaperTradingService = Depends(get_service),
                 cid: str = Depends(correlation_id)):
    return _run(lambda: service.get_proposal(proposal_id), cid)


@router.post("/proposals/{proposal_id}/confirm", response_model=Proposal, responses=_ERRORS)
def confirm(proposal_id: str, payload: ConfirmRequest, request: Request,
            service: PaperTradingService = Depends(get_service), cid: str = Depends(correlation_id)):
    return _guarded(request, service, cid, lambda: service.confirm(proposal_id, cid))


@router.post("/proposals/{proposal_id}/reconcile", response_model=Proposal, responses=_ERRORS)
def reconcile(proposal_id: str, request: Request, service: PaperTradingService = Depends(get_service),
              cid: str = Depends(correlation_id)):
    return _guarded(request, service, cid, lambda: service.reconcile(proposal_id, cid))


@router.get("/orders", response_model=list[BrokerOrder], responses=_ERRORS)
def list_orders(status: str = Query("all"),
                limit: int = Query(DEFAULT_ORDERS_PAGE, ge=1, le=MAX_ORDERS_PAGE),
                service: PaperTradingService = Depends(get_service), cid: str = Depends(correlation_id)):
    return _run(lambda: service.list_orders(status, limit), cid)


@router.get("/orders/{order_id}", response_model=BrokerOrder, responses=_ERRORS)
def get_order(order_id: str, service: PaperTradingService = Depends(get_service),
              cid: str = Depends(correlation_id)):
    return _run(lambda: service.get_order(order_id, cid), cid)


@router.post("/orders/{order_id}/cancel", responses=_ERRORS)
def cancel(order_id: str, payload: CancelRequest, request: Request,
           service: PaperTradingService = Depends(get_service), cid: str = Depends(correlation_id)):
    def run():
        result = service.cancel_order(order_id, cid)
        return {"cancelRequested": result["cancelRequested"],
                "order": result["order"].model_dump(mode="json")}

    return _guarded(request, service, cid, run)

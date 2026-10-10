"""Paper trading service: proposals, confirmation, submission, reconciliation, cancel.

Flow:  prepare (validate, persist, never submit)
       -> confirm (re-validate, atomic claim + persisted intent, single submit)
       -> reconcile by client_order_id when the outcome is uncertain.
No mutating call to Alpaca is ever retried automatically. A proposal whose
outcome is uncertain is never resubmitted; it can only be reconciled.
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from app.paper.client import (
    BrokerClient,
    BrokerConflict,
    BrokerNotFound,
    BrokerUnavailable,
    SubmitOutcome,
    SubmitResult,
)
from app.paper.config import (
    DEFAULT_ORDERS_PAGE,
    ENVIRONMENT,
    MAX_ORDERS_PAGE,
    ORDER_TYPE,
    TIME_IN_FORCE,
    PaperSettings,
)
from app.paper.models import (
    Account,
    BrokerOrder,
    Check,
    Clock,
    ErrorCode,
    PaperError,
    PaperStatus,
    Position,
    Proposal,
    ProposalRequest,
    Side,
)
from app.paper.reconciliation import order_changes, order_matches, to_broker_order
from app.paper.repository import Repository
from app.paper.validation import dec, run_checks

logger = logging.getLogger("atlas.paper")

ANALYSIS_NOTICE = (
    "ATLAS analysis uses a synthetic demo dataset. It is not market data and is not "
    "linked to paper orders, balances or prices."
)
WARNINGS = [
    "Paper trading: simulated money in an Alpaca Paper account.",
    "Market order: the execution price is not known in advance and is not guaranteed.",
    "These checks do not reserve funds or shares; Alpaca may still reject the order.",
    ANALYSIS_NOTICE,
]
_ORDER_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_UNCERTAIN = ("submitting", "submission_unknown")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


class PaperTradingService:
    def __init__(self, settings: PaperSettings, client: BrokerClient | None,
                 repository: Repository | None, now: Callable[[], datetime] | None = None):
        self.settings = settings
        self.client = client
        self.repository = repository
        self._now = now or (lambda: datetime.now(timezone.utc))

    # --- guards -----------------------------------------------------------

    def _ready(self) -> tuple[BrokerClient, Repository]:
        if not self.settings.enabled:
            raise PaperError(ErrorCode.PAPER_DISABLED, "Paper trading is disabled on this server.")
        if not self.settings.configured or self.client is None or self.repository is None:
            raise PaperError(ErrorCode.PAPER_NOT_CONFIGURED,
                             "Alpaca Paper credentials are not configured on this server.")
        return self.client, self.repository

    def _read(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except BrokerUnavailable as error:
            raise PaperError(ErrorCode.BROKER_UNAVAILABLE, "Alpaca Paper is not reachable right now.") from error

    def _event(self, proposal_id: str | None, kind: str, correlation_id: str | None, **data) -> dict:
        logger.info("paper_event type=%s proposal=%s correlation=%s", kind, proposal_id, correlation_id)
        return {"proposal_id": proposal_id, "at": _iso(self._now()), "type": kind,
                "correlation_id": correlation_id, "data": data}

    # --- read-only endpoints ---------------------------------------------

    def status(self) -> PaperStatus:
        base = dict(enabled=self.settings.enabled, configured=self.settings.configured,
                    maxOrderNotionalUsd=self.settings.max_order_notional,
                    proposalTtlSeconds=self.settings.proposal_ttl_seconds,
                    analysisDataNotice=ANALYSIS_NOTICE)
        if not self.settings.enabled:
            return PaperStatus(**base, brokerReachable=None, marketOpen=None,
                               message="Paper trading is disabled.")
        if not self.settings.configured or self.client is None:
            return PaperStatus(**base, brokerReachable=None, marketOpen=None,
                               message="Alpaca Paper credentials are missing.")
        try:
            clock = self.client.get_clock()
        except BrokerUnavailable:
            return PaperStatus(**base, brokerReachable=False, marketOpen=None,
                               message="Alpaca Paper is not reachable.")
        return PaperStatus(**base, brokerReachable=True, marketOpen=clock.get("is_open") is True,
                           message="Connected to Alpaca Paper.")

    def account(self) -> Account:
        client, _ = self._ready()
        raw = self._read(client.get_account)
        return Account(
            status=str(raw.get("status")), currency=str(raw.get("currency") or "USD"),
            cash=dec(raw.get("cash")), buyingPower=dec(raw.get("buying_power")),
            nonMarginableBuyingPower=dec(raw.get("non_marginable_buying_power")),
            equity=dec(raw.get("equity")), tradingBlocked=bool(raw.get("trading_blocked")),
            accountBlocked=bool(raw.get("account_blocked")),
        )

    def positions(self) -> list[Position]:
        client, _ = self._ready()
        rows = self._read(client.list_positions)
        return [
            Position(symbol=str(p.get("symbol")), side=str(p.get("side")), qty=dec(p.get("qty")) or Decimal(0),
                     qtyAvailable=dec(p.get("qty_available")), avgEntryPrice=dec(p.get("avg_entry_price")),
                     marketValue=dec(p.get("market_value")), assetClass=p.get("asset_class"))
            for p in rows
        ]

    def clock(self) -> Clock:
        client, _ = self._ready()
        raw = self._read(client.get_clock)
        return Clock(isOpen=raw.get("is_open") is True, timestamp=raw.get("timestamp"),
                     nextOpen=raw.get("next_open"), nextClose=raw.get("next_close"))

    # --- validation -------------------------------------------------------------

    def _validate(self, side: Side, symbol: str, notional: Decimal | None, qty: Decimal | None,
                  exclude_id: str | None = None) -> list[Check]:
        client, repo = self._ready()
        account = self._read(client.get_account)
        clock = self._read(client.get_clock)
        asset = self._read(lambda: client.get_asset(symbol))
        position = self._read(lambda: client.get_position(symbol)) if side is Side.SELL else None
        committed = repo.committed_sell_qty(symbol, exclude_id) if side is Side.SELL else []
        return run_checks(self.settings, side, symbol, notional, qty, account, clock, asset,
                          position, committed)

    # --- proposals -----------------------------------------------------------

    def create_proposal(self, request: ProposalRequest, correlation_id: str) -> Proposal:
        _, repo = self._ready()
        notional = Decimal(request.notional) if request.notional else None
        qty = Decimal(request.qty) if request.qty else None
        try:
            checks = self._validate(request.side, request.symbol, notional, qty)
        except PaperError as error:
            repo.add_event(self._event(None, "validation_failed", correlation_id, stage="prepare",
                                       symbol=request.symbol, side=request.side.value, code=error.code.value))
            raise

        now = self._now()
        proposal_id = uuid.uuid4().hex
        row = {
            "id": proposal_id,
            "client_order_id": f"atlas-{proposal_id}",
            "environment": ENVIRONMENT,
            "symbol": request.symbol,
            "side": request.side.value,
            "notional": str(notional) if notional is not None else None,
            "qty": str(qty) if qty is not None else None,
            "order_type": ORDER_TYPE,
            "time_in_force": TIME_IN_FORCE,
            "analysis_reference": request.analysisReference,
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=self.settings.proposal_ttl_seconds)),
            "status": "open",
            "submission_status": "not_submitted",
            "broker_order_id": None, "broker_status": None, "filled_qty": None,
            "filled_avg_price": None, "last_error_code": None,
            "checks": [c.model_dump() for c in checks],
            "warnings": WARNINGS,
            "updated_at": _iso(now),
            "version": 0,
        }
        repo.insert_proposal(row, self._event(
            proposal_id, "proposal_created", correlation_id, symbol=row["symbol"], side=row["side"],
            notional=row["notional"], qty=row["qty"], client_order_id=row["client_order_id"]))
        return self._to_proposal(row)

    def get_proposal(self, proposal_id: str) -> Proposal:
        _, repo = self._ready()
        row = self._load(repo, proposal_id)
        row = self._expire_if_due(repo, row, None)
        return self._to_proposal(row)

    def _load(self, repo: Repository, proposal_id: str) -> dict:
        row = repo.get_proposal(proposal_id) if re.fullmatch(r"[0-9a-f]{32}", proposal_id) else None
        if row is None:
            raise PaperError(ErrorCode.PROPOSAL_NOT_FOUND, "The proposal does not exist.")
        return row

    def _expire_if_due(self, repo: Repository, row: dict, correlation_id: str | None) -> dict:
        now = _iso(self._now())
        if row["status"] == "open" and row["submission_status"] in ("not_submitted", "failed_before_submit") \
                and now >= row["expires_at"]:
            repo.transition(row["id"], {"status": ("open",)},
                            {"status": "expired", "updated_at": now},
                            self._event(row["id"], "proposal_expired", correlation_id))
            row = repo.get_proposal(row["id"])
        return row

    def _known_result(self, row: dict) -> Proposal:
        """Outcome of a proposal that was already confirmed (idempotent confirm)."""
        submission = row["submission_status"]
        if submission == "submitted":
            return self._to_proposal(row)
        if submission == "submitting":
            raise PaperError(ErrorCode.SUBMISSION_IN_PROGRESS,
                             "This proposal is being submitted. Check its status.", row["id"])
        if submission == "submission_unknown":
            raise PaperError(ErrorCode.SUBMISSION_UNCERTAIN,
                             "The submission result is uncertain. Reconcile the proposal; it will not be resent.",
                             row["id"])
        if submission == "rejected_by_broker":
            raise PaperError(ErrorCode.BROKER_REJECTED, "Alpaca Paper rejected this order.", row["id"])
        raise AssertionError(f"unexpected confirmed state {submission}")

    def confirm(self, proposal_id: str, correlation_id: str) -> Proposal:
        client, repo = self._ready()
        row = self._load(repo, proposal_id)
        row = self._expire_if_due(repo, row, correlation_id)
        if row["status"] == "expired":
            raise PaperError(ErrorCode.PROPOSAL_EXPIRED, "The proposal has expired.", proposal_id)
        if row["status"] == "confirmed":
            return self._known_result(row)

        side = Side(row["side"])
        notional, qty = dec(row["notional"]), dec(row["qty"])
        try:
            checks = self._validate(side, row["symbol"], notional, qty, exclude_id=proposal_id)
        except PaperError as error:
            repo.add_event(self._event(proposal_id, "validation_failed", correlation_id,
                                       stage="confirm", code=error.code.value))
            error.proposal_id = proposal_id
            raise

        now = _iso(self._now())
        claimed = repo.transition(
            proposal_id,
            {"status": ("open",), "submission_status": ("not_submitted", "failed_before_submit")},
            {"status": "confirmed", "submission_status": "submitting", "last_error_code": None,
             "updated_at": now},
            self._event(proposal_id, "submission_intent", correlation_id,
                        client_order_id=row["client_order_id"], symbol=row["symbol"], side=row["side"],
                        notional=row["notional"], qty=row["qty"],
                        checks=[c.name for c in checks if c.passed]),
            extra_where="expires_at > ?", extra_params=(now,),
        )
        if not claimed:
            # Another confirmation won the race, or the proposal just expired.
            row = self._expire_if_due(repo, repo.get_proposal(proposal_id), correlation_id)
            if row["status"] == "expired":
                raise PaperError(ErrorCode.PROPOSAL_EXPIRED, "The proposal has expired.", proposal_id)
            return self._known_result(row)

        payload = {"symbol": row["symbol"], "side": row["side"], "type": ORDER_TYPE,
                   "time_in_force": TIME_IN_FORCE, "client_order_id": row["client_order_id"]}
        if side is Side.BUY:
            payload["notional"] = row["notional"]
        else:
            payload["qty"] = row["qty"]

        try:
            result = client.submit_order(payload)
        except Exception:  # noqa: BLE001 - anything after the claim leaves the outcome uncertain
            logger.exception("paper submit raised proposal=%s correlation=%s", proposal_id, correlation_id)
            result = SubmitResult(SubmitOutcome.UNKNOWN, detail="client exception")
        return self._apply_submit_result(repo, client, row, result, correlation_id)

    def _apply_submit_result(self, repo, client, row, result, correlation_id) -> Proposal:
        pid, now = row["id"], _iso(self._now())
        submitting = {"submission_status": ("submitting",)}
        if result.outcome is SubmitOutcome.ACCEPTED and order_matches(row, result.order):
            repo.transition(pid, submitting, order_changes(result.order, now),
                            self._event(pid, "broker_accepted", correlation_id,
                                        broker_order_id=result.order["id"],
                                        broker_status=result.order.get("status")))
            return self._to_proposal(repo.get_proposal(pid))
        if result.outcome is SubmitOutcome.REJECTED:
            repo.transition(pid, submitting,
                            {"submission_status": "rejected_by_broker",
                             "last_error_code": ErrorCode.BROKER_REJECTED.value, "updated_at": now},
                            self._event(pid, "broker_rejected", correlation_id, http_status=result.http_status))
            raise PaperError(ErrorCode.BROKER_REJECTED, "Alpaca Paper rejected this order.", pid)
        if result.outcome is SubmitOutcome.NOT_SENT:
            # The connection was never established: nothing reached Alpaca.
            repo.transition(pid, submitting,
                            {"status": "open", "submission_status": "failed_before_submit",
                             "last_error_code": ErrorCode.BROKER_UNAVAILABLE.value, "updated_at": now},
                            self._event(pid, "submission_not_sent", correlation_id, detail=result.detail))
            raise PaperError(ErrorCode.BROKER_UNAVAILABLE,
                             "Alpaca Paper was not reachable; the order was not sent.", pid)

        # UNKNOWN (or an accepted body that does not match the proposal).
        repo.transition(pid, submitting,
                        {"submission_status": "submission_unknown",
                         "last_error_code": ErrorCode.SUBMISSION_UNCERTAIN.value, "updated_at": now},
                        self._event(pid, "submission_unknown", correlation_id,
                                    detail=result.detail, http_status=result.http_status))
        # One read-only lookup by client_order_id. Never a resubmission.
        try:
            return self.reconcile(pid, correlation_id)
        except PaperError:
            raise PaperError(ErrorCode.SUBMISSION_UNCERTAIN,
                             "The submission result is uncertain. Reconcile the proposal; it will not be resent.",
                             pid) from None

    # --- reconciliation ----------------------------------------------------

    def reconcile(self, proposal_id: str, correlation_id: str | None) -> Proposal:
        client, repo = self._ready()
        row = self._load(repo, proposal_id)
        if row["submission_status"] not in ("submitting", "submission_unknown", "submitted"):
            return self._to_proposal(self._expire_if_due(repo, row, correlation_id))
        if row["submission_status"] == "submitting":
            raise PaperError(ErrorCode.SUBMISSION_IN_PROGRESS,
                             "This proposal is being submitted. Check its status.", proposal_id)

        if row["broker_order_id"]:
            order = self._read(lambda: client.get_order(row["broker_order_id"]))
        else:
            order = self._read(lambda: client.get_order_by_client_id(row["client_order_id"]))
        now = _iso(self._now())
        if order is None or not order_matches(row, order):
            repo.add_event(self._event(proposal_id, "reconcile_not_found", correlation_id,
                                       client_order_id=row["client_order_id"]))
            if row["submission_status"] == "submission_unknown":
                raise PaperError(ErrorCode.SUBMISSION_UNCERTAIN,
                                 "No matching order was found yet. The proposal stays uncertain and will not be resent.",
                                 proposal_id)
            raise PaperError(ErrorCode.ORDER_NOT_FOUND, "The broker order was not found.", proposal_id)

        repo.transition(proposal_id, {"submission_status": ("submission_unknown", "submitted")},
                        order_changes(order, now),
                        self._event(proposal_id, "reconciled", correlation_id, broker_order_id=order["id"],
                                    broker_status=order.get("status"), filled_qty=order.get("filled_qty")))
        return self._to_proposal(repo.get_proposal(proposal_id))

    def recover_pending(self) -> list[str]:
        """Startup recovery: in-flight submissions become uncertain, then are reconciled (read-only)."""
        if not self.settings.enabled or self.repository is None:
            return []
        repo = self.repository
        recovered = []
        for row in repo.list_by_submission(_UNCERTAIN):
            if row["submission_status"] == "submitting":
                repo.transition(row["id"], {"submission_status": ("submitting",)},
                                {"submission_status": "submission_unknown",
                                 "last_error_code": ErrorCode.SUBMISSION_UNCERTAIN.value,
                                 "updated_at": _iso(self._now())},
                                self._event(row["id"], "recovered_after_restart", None))
            recovered.append(row["id"])
            if self.client is not None and self.settings.configured:
                try:
                    self.reconcile(row["id"], None)
                except PaperError:
                    pass  # stays submission_unknown; visible to the user
        return recovered

    # --- orders -------------------------------------------------------------------

    def _proposal_for(self, repo: Repository, order: dict) -> dict | None:
        row = repo.get_by_client_order_id(str(order.get("client_order_id") or ""))
        return row if row is not None and order_matches(row, order) else None

    def list_orders(self, status: str = "all", limit: int = DEFAULT_ORDERS_PAGE) -> list[BrokerOrder]:
        client, repo = self._ready()
        if status not in ("open", "closed", "all") or not 1 <= limit <= MAX_ORDERS_PAGE:
            raise PaperError(ErrorCode.INVALID_REQUEST,
                             f"status must be open, closed or all; limit must be 1-{MAX_ORDERS_PAGE}.")
        orders = self._read(lambda: client.list_orders(status, limit))
        result = []
        for order in orders[:limit]:
            row = self._proposal_for(repo, order)
            result.append(to_broker_order(order, row["id"] if row else None))
        return result

    def get_order(self, order_id: str, correlation_id: str | None = None) -> BrokerOrder:
        client, repo = self._ready()
        if not _ORDER_ID.fullmatch(order_id):
            raise PaperError(ErrorCode.ORDER_NOT_FOUND, "The order does not exist.")
        order = self._read(lambda: client.get_order(order_id))
        if order is None:
            raise PaperError(ErrorCode.ORDER_NOT_FOUND, "The order does not exist.")
        row = self._proposal_for(repo, order)
        if row is not None:
            repo.transition(row["id"], {"submission_status": ("submitted", "submission_unknown")},
                            order_changes(order, _iso(self._now())),
                            self._event(row["id"], "order_status", correlation_id,
                                        broker_status=order.get("status"), filled_qty=order.get("filled_qty")))
        return to_broker_order(order, row["id"] if row else None)

    def cancel_order(self, order_id: str, correlation_id: str) -> dict:
        client, repo = self._ready()
        if not _ORDER_ID.fullmatch(order_id):
            raise PaperError(ErrorCode.ORDER_NOT_FOUND, "The order does not exist.")
        linked = repo.get_by_broker_order_id(order_id)
        linked_id = linked["id"] if linked else None
        repo.add_event(self._event(linked_id, "cancel_requested", correlation_id, broker_order_id=order_id))
        try:
            client.cancel_order(order_id)
        except BrokerNotFound:
            raise PaperError(ErrorCode.ORDER_NOT_FOUND, "The order does not exist.") from None
        except BrokerConflict:
            repo.add_event(self._event(linked_id, "cancel_rejected", correlation_id, broker_order_id=order_id))
            raise PaperError(ErrorCode.ORDER_NOT_CANCELABLE,
                             "The order can no longer be canceled (it may already be filled or closed).",
                             linked_id) from None
        except BrokerUnavailable:
            raise PaperError(ErrorCode.BROKER_UNAVAILABLE, "Alpaca Paper is not reachable right now.") from None
        # A 204 means "cancel requested", not "canceled": report Alpaca's current status.
        order = self.get_order(order_id, correlation_id)
        repo.add_event(self._event(linked_id, "cancel_result", correlation_id, broker_order_id=order_id,
                                   broker_status=order.status.value))
        return {"cancelRequested": True, "order": order}

    # --- serialization -------------------------------------------------------------

    @staticmethod
    def _to_proposal(row: dict) -> Proposal:
        return Proposal(
            id=row["id"], environment=row["environment"], symbol=row["symbol"], side=row["side"],
            notional=dec(row["notional"]), qty=dec(row["qty"]), orderType=row["order_type"],
            timeInForce=row["time_in_force"], clientOrderId=row["client_order_id"],
            analysisReference=row["analysis_reference"], createdAt=row["created_at"],
            expiresAt=row["expires_at"], status=row["status"], submissionStatus=row["submission_status"],
            brokerOrderId=row["broker_order_id"], brokerStatus=row["broker_status"],
            filledQty=dec(row["filled_qty"]), filledAvgPrice=dec(row["filled_avg_price"]),
            lastErrorCode=row["last_error_code"], checks=row["checks"], warnings=row["warnings"],
            updatedAt=row["updated_at"],
        )

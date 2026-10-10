"""Paper trading service: validation, proposals, confirmation, uncertainty, cancel."""

import threading
from decimal import Decimal

import pytest

from app.paper.models import ErrorCode, PaperError, ProposalRequest
from app.paper.repository import Repository
from app.paper.service import PaperTradingService
from tests.paper_fakes import Clock, FakeBroker, make_service, settings


def buy(symbol="NVDA", notional="100.00", **kw):
    return ProposalRequest(symbol=symbol, side="buy", notional=notional, **kw)


def sell(symbol="NVDA", qty="1"):
    return ProposalRequest(symbol=symbol, side="sell", qty=qty)


def expect(code, fn):
    with pytest.raises(PaperError) as excinfo:
        fn()
    assert excinfo.value.code is code, excinfo.value
    return excinfo.value


@pytest.fixture
def broker():
    return FakeBroker()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def svc(tmp_path, broker, clock):
    return make_service(tmp_path, broker, clock)


# --- 1. disabled / 3. not configured ------------------------------------------

def test_disabled_makes_no_external_calls(tmp_path, broker):
    service = make_service(tmp_path, broker, enabled=False)
    for fn in (service.account, service.positions, service.clock,
               lambda: service.create_proposal(buy(), "c"), lambda: service.list_orders()):
        expect(ErrorCode.PAPER_DISABLED, fn)
    assert service.status().enabled is False
    assert broker.calls == []
    assert service.recover_pending() == []


def test_missing_secrets_make_no_external_calls(tmp_path, broker):
    service = make_service(tmp_path, broker, api_key="", secret_key="")
    expect(ErrorCode.PAPER_NOT_CONFIGURED, service.account)
    assert service.status().configured is False
    assert broker.calls == []


def test_status_reports_broker_reachability(svc, broker):
    assert svc.status().brokerReachable is True and svc.status().marketOpen is True
    broker.unavailable = True
    assert svc.status().brokerReachable is False


# --- 5-10. business validation ------------------------------------------------

@pytest.mark.parametrize("symbol", ["OLD", "ZZZZ"])
def test_unknown_or_non_tradable_asset(svc, symbol):
    expect(ErrorCode.ASSET_NOT_SUPPORTED, lambda: svc.create_proposal(buy(symbol), "c"))


def test_non_us_equity_asset_rejected(svc, broker):
    broker.assets["XYZ"] = {"symbol": "XYZ", "class": "crypto", "status": "active",
                            "tradable": True, "fractionable": True}
    expect(ErrorCode.ASSET_NOT_SUPPORTED, lambda: svc.create_proposal(buy("XYZ"), "c"))


def test_notional_buy_requires_fractionable(svc):
    error = expect(ErrorCode.FRACTIONAL_NOT_SUPPORTED, lambda: svc.create_proposal(buy("BRK.A"), "c"))
    assert "No other order type is substituted" in error.message


def test_fractional_sell_requires_fractionable_but_whole_sell_does_not(svc, broker):
    broker.add_position("BRK.A", "3")
    expect(ErrorCode.FRACTIONAL_NOT_SUPPORTED, lambda: svc.create_proposal(sell("BRK.A", "0.5"), "c"))
    assert svc.create_proposal(sell("BRK.A", "1"), "c").qty == Decimal("1")


def test_market_closed(svc, broker):
    broker.clock["is_open"] = False
    expect(ErrorCode.MARKET_CLOSED, lambda: svc.create_proposal(buy(), "c"))


@pytest.mark.parametrize("change", [{"trading_blocked": True}, {"account_blocked": True}, {"status": "INACTIVE"}])
def test_account_not_tradable(svc, broker, change):
    broker.account.update(change)
    expect(ErrorCode.ACCOUNT_NOT_TRADABLE, lambda: svc.create_proposal(buy(), "c"))


def test_insufficient_buying_power_uses_non_marginable(svc, broker):
    broker.account["non_marginable_buying_power"] = "50"  # margin buying power is higher
    expect(ErrorCode.INSUFFICIENT_BUYING_POWER, lambda: svc.create_proposal(buy(notional="60.00"), "c"))


def test_missing_buying_power_is_not_assumed_safe(svc, broker):
    del broker.account["non_marginable_buying_power"]
    expect(ErrorCode.BROKER_UNAVAILABLE, lambda: svc.create_proposal(buy(), "c"))


def test_order_limit(svc):
    expect(ErrorCode.ORDER_LIMIT_EXCEEDED, lambda: svc.create_proposal(buy(notional="1000.01"), "c"))
    assert svc.create_proposal(buy(notional="1000.00"), "c").notional == Decimal("1000.00")


def test_sell_more_than_position(svc, broker):
    broker.add_position("NVDA", "2")
    expect(ErrorCode.INSUFFICIENT_POSITION, lambda: svc.create_proposal(sell(qty="2.5"), "c"))


@pytest.mark.parametrize("setup", [lambda b: None, lambda b: b.add_position("NVDA", "-3", side="short")])
def test_sell_without_long_position_never_shorts(svc, broker, setup):
    setup(broker)
    error = expect(ErrorCode.INSUFFICIENT_POSITION, lambda: svc.create_proposal(sell(), "c"))
    assert "Short sales are not allowed" in error.message


def test_open_orders_reduce_available_quantity(svc, broker):
    broker.add_position("NVDA", "5", qty_available="2")  # 3 shares locked by open orders
    expect(ErrorCode.INSUFFICIENT_POSITION, lambda: svc.create_proposal(sell(qty="3"), "c"))
    assert svc.create_proposal(sell(qty="2"), "c").status.value == "open"


def test_uncertain_local_sells_are_committed(svc, broker):
    broker.add_position("NVDA", "5")
    broker.submit_mode = "unknown_missing"
    first = svc.create_proposal(sell(qty="4"), "c")
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(first.id, "c"))
    # Phase 5.5: blocked by an uncertain local sell -> check status first (not a definitive shortage).
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: svc.create_proposal(sell(qty="2"), "c"))
    assert svc.create_proposal(sell(qty="1"), "c").qty == Decimal("1")


def test_broker_down_during_validation(svc, broker):
    broker.unavailable = True
    expect(ErrorCode.BROKER_UNAVAILABLE, lambda: svc.create_proposal(buy(), "c"))


# --- 11-15. proposal lifecycle -------------------------------------------------

def test_prepare_never_submits(svc, broker, tmp_path):
    proposal = svc.create_proposal(buy(analysisReference="NVDA@2026-09-30"), "c")
    assert broker.submits == [] and "submit_order" not in broker.calls
    assert proposal.status.value == "open" and proposal.submissionStatus.value == "not_submitted"
    assert proposal.clientOrderId == f"atlas-{proposal.id}"
    assert proposal.environment.value == "paper"
    assert proposal.orderType == "market" and proposal.timeInForce == "day"
    assert proposal.analysisReference == "NVDA@2026-09-30"
    assert any("not guaranteed" in w for w in proposal.warnings)
    assert any("synthetic" in w for w in proposal.warnings)
    assert {c.name for c in proposal.checks} >= {"account_tradable", "market_open", "asset_tradable", "buying_power"}


def test_valid_confirmation_submits_once_with_stable_client_order_id(svc, broker, tmp_path):
    proposal = svc.create_proposal(buy(), "c1")
    confirmed = svc.confirm(proposal.id, "c2")
    assert confirmed.status.value == "confirmed" and confirmed.submissionStatus.value == "submitted"
    assert confirmed.brokerOrderId and confirmed.brokerStatus.value == "accepted"
    assert broker.submits == [{"symbol": "NVDA", "side": "buy", "type": "market", "time_in_force": "day",
                               "client_order_id": proposal.clientOrderId, "notional": "100.00"}]
    events = [e["type"] for e in Repository(tmp_path / "paper.sqlite3").events(proposal.id)]
    assert events == ["proposal_created", "submission_intent", "broker_accepted"]


def test_sell_payload_uses_qty(svc, broker):
    broker.add_position("NVDA", "2")
    proposal = svc.create_proposal(sell(qty="0.500000"), "c")
    svc.confirm(proposal.id, "c")
    assert broker.submits[0]["qty"] == "0.500000" and "notional" not in broker.submits[0]


def test_confirmation_revalidates(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    broker.clock["is_open"] = False
    expect(ErrorCode.MARKET_CLOSED, lambda: svc.confirm(proposal.id, "c"))
    assert broker.submits == []
    assert svc.get_proposal(proposal.id).status.value == "open"


def test_expired_proposal_is_not_submitted(svc, broker, clock):
    proposal = svc.create_proposal(buy(), "c")
    clock.advance(301)
    expect(ErrorCode.PROPOSAL_EXPIRED, lambda: svc.confirm(proposal.id, "c"))
    assert svc.get_proposal(proposal.id).status.value == "expired"
    assert broker.submits == []


def test_proposal_fields_are_immutable(svc, tmp_path):
    proposal = svc.create_proposal(buy(), "c")
    repo = Repository(tmp_path / "paper.sqlite3")
    with pytest.raises(ValueError, match="immutable"):
        repo.transition(proposal.id, {"status": ("open",)}, {"notional": "999.00"}, {"at": "x", "type": "t"})
    with pytest.raises(Exception):
        with repo.transaction() as conn:  # the schema forbids a buy without notional
            conn.execute("UPDATE proposals SET notional = NULL WHERE id = ?", (proposal.id,))
    assert svc.get_proposal(proposal.id).notional == Decimal("100.00")


def test_duplicate_confirmation_returns_known_result(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    first = svc.confirm(proposal.id, "c")
    second = svc.confirm(proposal.id, "c")
    assert len(broker.submits) == 1
    assert second.brokerOrderId == first.brokerOrderId


def test_concurrent_confirmations_submit_once(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    broker.submit_delay = 0.3
    results, barrier = [], threading.Barrier(4)

    def run():
        barrier.wait()
        try:
            results.append(svc.confirm(proposal.id, "c").submissionStatus.value)
        except PaperError as error:
            results.append(error.code.value)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(broker.submits) == 1
    assert results.count("submitted") >= 1
    assert set(results) <= {"submitted", "SUBMISSION_IN_PROGRESS"}


def test_not_sent_can_be_confirmed_again_with_same_client_order_id(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    broker.submit_mode = "not_sent"
    expect(ErrorCode.BROKER_UNAVAILABLE, lambda: svc.confirm(proposal.id, "c"))
    assert svc.get_proposal(proposal.id).submissionStatus.value == "failed_before_submit"
    broker.submit_mode = "accept"
    assert svc.confirm(proposal.id, "c").submissionStatus.value == "submitted"
    assert [s["client_order_id"] for s in broker.submits] == [proposal.clientOrderId] * 2


# --- 17-21. uncertainty, reconciliation, rejection, fills -----------------------

def test_timeout_after_broker_accepted_is_reconciled_without_resubmit(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    broker.submit_mode = "unknown_created"
    result = svc.confirm(proposal.id, "c")
    assert result.submissionStatus.value == "submitted" and result.brokerOrderId
    assert len(broker.submits) == 1
    assert "get_order_by_client_id" in broker.calls


def test_uncertain_submission_is_never_resent(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(proposal.id, "c"))
    assert svc.get_proposal(proposal.id).submissionStatus.value == "submission_unknown"
    broker.submit_mode = "accept"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(proposal.id, "c"))
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.reconcile(proposal.id, "c"))
    assert len(broker.submits) == 1


def test_reconcile_by_client_order_id_once_order_appears(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(proposal.id, "c"))
    broker._store({**broker.submits[0]})  # the order shows up at Alpaca later
    result = svc.reconcile(proposal.id, "c")
    assert result.submissionStatus.value == "submitted" and result.brokerOrderId
    assert len(broker.submits) == 1


def test_reconcile_ignores_order_with_different_symbol(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(proposal.id, "c"))
    broker._store({**broker.submits[0], "symbol": "AAPL"})
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.reconcile(proposal.id, "c"))


def test_client_exception_after_claim_is_treated_as_uncertain(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    broker.submit_mode = "raise"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(proposal.id, "c"))


def test_restart_with_pending_submission_reconciles_before_anything_else(tmp_path, broker, clock):
    first = make_service(tmp_path, broker, clock)
    proposal = first.create_proposal(buy(), "c")
    repo = Repository(tmp_path / "paper.sqlite3")
    # Simulate a crash after the intent was persisted and the order reached Alpaca.
    repo.transition(proposal.id, {"status": ("open",)},
                    {"status": "confirmed", "submission_status": "submitting"}, {"at": "t", "type": "submission_intent"})
    broker._store({"client_order_id": proposal.clientOrderId, "symbol": "NVDA", "side": "buy",
                   "type": "market", "time_in_force": "day", "notional": "100.00"})
    restarted = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    assert restarted.recover_pending() == [proposal.id]
    assert restarted.get_proposal(proposal.id).submissionStatus.value == "submitted"
    assert broker.submits == []
    types = [e["type"] for e in repo.events(proposal.id)]
    assert "recovered_after_restart" in types and "reconciled" in types


def test_restart_without_matching_order_stays_uncertain(tmp_path, broker, clock):
    first = make_service(tmp_path, broker, clock)
    proposal = first.create_proposal(buy(), "c")
    Repository(tmp_path / "paper.sqlite3").transition(
        proposal.id, {"status": ("open",)}, {"status": "confirmed", "submission_status": "submitting"},
        {"at": "t", "type": "submission_intent"})
    restarted = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    restarted.recover_pending()
    assert restarted.get_proposal(proposal.id).submissionStatus.value == "submission_unknown"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: restarted.confirm(proposal.id, "c"))
    assert broker.submits == []


def test_explicit_rejection_is_final(svc, broker):
    proposal = svc.create_proposal(buy(), "c")
    broker.submit_mode = "reject"
    expect(ErrorCode.BROKER_REJECTED, lambda: svc.confirm(proposal.id, "c"))
    assert svc.get_proposal(proposal.id).submissionStatus.value == "rejected_by_broker"
    broker.submit_mode = "accept"
    expect(ErrorCode.BROKER_REJECTED, lambda: svc.confirm(proposal.id, "c"))
    assert len(broker.submits) == 1


def test_partial_fill_is_tracked_from_broker_status(svc, broker):
    broker.fill_status, broker.fill_qty = "partially_filled", "0.4"
    proposal = svc.confirm(svc.create_proposal(buy(), "c").id, "c")
    assert proposal.brokerStatus.value == "partially_filled" and proposal.filledQty == Decimal("0.4")
    broker.orders[proposal.brokerOrderId].update(status="filled", filled_qty="0.98")
    order = svc.get_order(proposal.brokerOrderId)
    assert order.status.value == "filled" and order.proposalId == proposal.id
    assert svc.get_proposal(proposal.id).filledQty == Decimal("0.98")


# --- 22. cancellation ---------------------------------------------------------

def _submitted(svc):
    return svc.confirm(svc.create_proposal(buy(), "c").id, "c")


def test_cancel_request_reports_pending_not_canceled(svc, broker):
    proposal = _submitted(svc)
    result = svc.cancel_order(proposal.brokerOrderId, "c")
    assert result["cancelRequested"] is True
    assert result["order"].status.value == "pending_cancel"
    assert svc.get_proposal(proposal.id).brokerStatus.value == "pending_cancel"


def test_cancel_racing_with_fill_reports_fill(svc, broker):
    proposal = _submitted(svc)
    broker.cancel_mode = "filled_race"
    result = svc.cancel_order(proposal.brokerOrderId, "c")
    assert result["order"].status.value == "filled"
    assert svc.get_proposal(proposal.id).brokerStatus.value == "filled"


def test_cancel_not_cancelable_and_not_found(svc, broker):
    proposal = _submitted(svc)
    broker.cancel_mode = "not_cancelable"
    expect(ErrorCode.ORDER_NOT_CANCELABLE, lambda: svc.cancel_order(proposal.brokerOrderId, "c"))
    expect(ErrorCode.ORDER_NOT_FOUND, lambda: svc.cancel_order("missing-id", "c"))
    expect(ErrorCode.ORDER_NOT_FOUND, lambda: svc.cancel_order("../v2/account", "c"))


def test_reads_never_cancel(svc, broker):
    proposal = _submitted(svc)
    svc.list_orders()
    svc.get_order(proposal.brokerOrderId)
    svc.get_proposal(proposal.id)
    assert "cancel_order" not in broker.calls


# --- 23. persistence -------------------------------------------------------------

def test_proposals_survive_a_new_service_instance(tmp_path, broker, clock):
    proposal = make_service(tmp_path, broker, clock).create_proposal(buy(), "c")
    again = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    assert again.get_proposal(proposal.id) == proposal


def test_orders_listing_is_bounded_and_linked(svc, broker):
    proposal = _submitted(svc)
    orders = svc.list_orders("all", 10)
    assert orders[0].proposalId == proposal.id
    expect(ErrorCode.INVALID_REQUEST, lambda: svc.list_orders("weird", 10))
    expect(ErrorCode.INVALID_REQUEST, lambda: svc.list_orders("all", 1000))


def test_amounts_serialize_as_decimal_strings(svc):
    data = svc.create_proposal(buy(notional="100.10"), "c").model_dump(mode="json")
    assert data["notional"] == "100.10" and data["qty"] is None

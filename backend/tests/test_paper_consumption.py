"""Phase 5.6: executed consumption must stay protected until a snapshot can be trusted.

Snapshots are frozen on purpose; the fake never refreshes them to hide the lag.
"""

import pytest

from app.paper.models import ErrorCode, PaperError
from tests.paper_fakes import FakeBroker, make_service
from tests.test_paper_reservations import budget, buy, sell


def expect(code, fn):
    with pytest.raises(PaperError) as excinfo:
        fn()
    assert excinfo.value.code is code, excinfo.value
    return excinfo.value


def test_repro_a_partial_buy_with_stale_account(tmp_path):
    broker = FakeBroker()
    budget(broker, "100")
    broker.freeze_account()
    service = make_service(tmp_path, broker)
    first = service.confirm(service.create_proposal(buy("100.00"), "t").id, "t")
    broker.fill(first.brokerOrderId, qty="0.5", price="100", final=False)
    # Truth: cash 50, open hold 50 -> nothing available. Snapshot still says 100.
    expect(ErrorCode.RECONCILIATION_REQUIRED,
           lambda: service.confirm(service.create_proposal(buy("50.00"), "t").id, "t"))
    assert [o["notional"] for o in broker.submits] == ["100.00"]


def test_repro_b_filled_sell_with_stale_position(tmp_path):
    broker = FakeBroker()
    broker.add_position("NVDA", "1")
    broker.freeze_position("NVDA")
    service = make_service(tmp_path, broker)
    first = service.confirm(service.create_proposal(sell("1"), "t").id, "t")
    broker.fill(first.brokerOrderId, qty="1", price="100", final=True)
    # Truth: position 0. Snapshot still says 1.
    expect(ErrorCode.RECONCILIATION_REQUIRED,
           lambda: service.confirm(service.create_proposal(sell("1"), "t").id, "t"))
    assert [o["qty"] for o in broker.submits] == ["1"]


# --- helpers -------------------------------------------------------------------

import sqlite3  # noqa: E402
import threading  # noqa: E402
from decimal import Decimal  # noqa: E402

from app.paper.repository import MIGRATION_V2, SCHEMA_V1, Repository  # noqa: E402
from app.paper.service import PaperTradingService  # noqa: E402
from tests.paper_fakes import Clock, settings  # noqa: E402


def submitted(broker, field):
    return [o.get(field) for o in broker.submits if field in o]


def ok(service, request):
    return service.confirm(service.create_proposal(request, "t").id, "t")


# --- 2-5: stale snapshots after fills -------------------------------------------

def test_partial_buy_with_stale_account_protects_consumed_and_pending(tmp_path):
    broker = FakeBroker()
    budget(broker, "200")
    broker.freeze_account()
    service = make_service(tmp_path, broker)
    first = ok(service, buy("100.00"))
    broker.fill(first.brokerOrderId, "0.5", "100", final=False)      # consumed 50, pending 50
    # Ledger: 200 - 50 consumed - 50 hold = 100 proven, snapshot claims 150.
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(buy("100.01"), "t"))
    assert ok(service, buy("100.00")).submissionStatus.value == "submitted"
    assert submitted(broker, "notional") == ["100.00", "100.00"]


def test_full_buy_with_stale_account(tmp_path):
    broker = FakeBroker()
    budget(broker, "100")
    broker.freeze_account()
    service = make_service(tmp_path, broker)
    first = ok(service, buy("100.00"))
    broker.fill(first.brokerOrderId, "1", "100", final=True)
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(buy("1.00"), "t"))
    reservation = service.get_proposal(first.id).reservation
    assert (reservation.state.value, reservation.filledNotional) == ("released", Decimal("100"))
    assert submitted(broker, "notional") == ["100.00"]


def test_partial_sell_with_stale_position(tmp_path):
    broker = FakeBroker()
    broker.add_position("NVDA", "5")
    broker.freeze_position("NVDA")
    service = make_service(tmp_path, broker)
    first = ok(service, sell("4"))
    broker.fill(first.brokerOrderId, "3", "100", final=False)          # 3 sold, 1 pending
    # Ledger: 5 - 3 = 2 shares, 1 still held by the open order -> 1 proven.
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(sell("2"), "t"))
    assert ok(service, sell("1")).submissionStatus.value == "submitted"
    assert submitted(broker, "qty") == ["4", "1"]


def test_full_sell_then_fresh_position_needs_no_reconciliation(tmp_path):
    broker = FakeBroker()
    broker.add_position("NVDA", "2")
    broker.freeze_position("NVDA")
    service = make_service(tmp_path, broker)
    first = ok(service, sell("1"))
    broker.fill(first.brokerOrderId, "1", "100", final=True)
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(sell("2"), "t"))
    assert ok(service, sell("1")).submissionStatus.value == "submitted"   # 1 share is proven
    broker.frozen_positions.clear()                                    # broker catches up
    expect(ErrorCode.INSUFFICIENT_POSITION, lambda: service.create_proposal(sell("1"), "t"))


# --- 6, 18: cancellation -----------------------------------------------------------

def test_cancel_after_partial_fill_frees_only_the_remainder(tmp_path):
    broker = FakeBroker()
    broker.add_position("NVDA", "5")
    broker.freeze_position("NVDA")
    service = make_service(tmp_path, broker)
    first = ok(service, sell("4"))
    broker.fill(first.brokerOrderId, "3", "100", final=False)
    service.cancel_order(first.brokerOrderId, "t")
    broker.finish_cancel(first.brokerOrderId)
    service.get_order(first.brokerOrderId)
    reservation = service.get_proposal(first.id).reservation
    assert (reservation.state.value, reservation.filledQty) == ("released", Decimal("3"))
    # The unfilled share is free again, the 3 sold shares stay protected.
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(sell("3"), "t"))
    assert ok(service, sell("2")).submissionStatus.value == "submitted"


def test_cancel_requested_keeps_pending_and_consumed_protected(tmp_path):
    broker = FakeBroker()
    broker.add_position("NVDA", "5")
    broker.freeze_position("NVDA")
    service = make_service(tmp_path, broker)
    first = ok(service, sell("4"))
    broker.fill(first.brokerOrderId, "1", "100", final=False)
    result = service.cancel_order(first.brokerOrderId, "t")
    assert result["order"].status.value == "pending_cancel"
    assert service.get_proposal(first.id).reservation.state.value == "acknowledged"
    # 5 - 1 sold - 3 still held = 1.
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(sell("2"), "t"))
    assert ok(service, sell("1")).submissionStatus.value == "submitted"


@pytest.mark.parametrize("final_status", ["expired", "rejected"])
def test_final_status_with_fills_is_not_zero_execution(tmp_path, final_status):
    broker = FakeBroker()
    broker.add_position("NVDA", "5")
    broker.freeze_position("NVDA")
    service = make_service(tmp_path, broker)
    first = ok(service, sell("4"))
    broker.fill(first.brokerOrderId, "2", "100", final=False)
    broker.orders[first.brokerOrderId]["status"] = final_status
    service.get_order(first.brokerOrderId)
    assert service.get_proposal(first.id).reservation.filledQty == Decimal("2")
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(sell("4"), "t"))
    assert ok(service, sell("3")).submissionStatus.value == "submitted"


# --- 7, 15: fresh snapshots are not double counted -----------------------------

def test_fresh_snapshots_are_not_double_counted(tmp_path):
    broker = FakeBroker()
    budget(broker, "200")
    broker.add_position("NVDA", "5")
    service = make_service(tmp_path, broker)
    b = ok(service, buy("100.00"))
    broker.fill(b.brokerOrderId, "0.5", "100", final=False)
    broker.fill(b.brokerOrderId, "0.5", "100", final=True)              # cash 100 at the broker
    s = ok(service, sell("4"))
    broker.fill(s.brokerOrderId, "4", "50", final=True)                 # cash 300, qty 2 at the broker
    # Exactly the fresh values are usable: 300 USD and 2 shares (1.0 from the buy + 1).
    assert ok(service, sell("2")).submissionStatus.value == "submitted"
    assert ok(service, buy("300.00")).submissionStatus.value == "submitted"
    assert submitted(broker, "notional")[-1] == "300.00"


def test_weighted_average_and_cumulative_fills(tmp_path):
    broker = FakeBroker()
    budget(broker, "220")
    service = make_service(tmp_path, broker)
    first = ok(service, buy("110.00"))
    broker.fill(first.brokerOrderId, "0.5", "100", final=False)
    broker.fill(first.brokerOrderId, "0.5", "120", final=True)          # cost 110, avg 110
    service.get_order(first.brokerOrderId)
    assert service.get_proposal(first.id).reservation.filledNotional == Decimal("110")
    assert ok(service, buy("110.00")).submissionStatus.value == "submitted"   # 220 - 110 = 110 exactly
    expect(ErrorCode.INSUFFICIENT_BUYING_POWER, lambda: service.create_proposal(buy("1.00"), "t"))


# --- 8: open order with consumption pending reconciliation ----------------------

def test_open_acknowledged_order_with_unreflected_fill_then_broker_catches_up(tmp_path):
    broker = FakeBroker()
    budget(broker, "200")
    broker.freeze_account()
    service = make_service(tmp_path, broker)
    first = ok(service, buy("100.00"))
    broker.fill(first.brokerOrderId, "0.5", "100", final=False)
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(buy("150.00"), "t"))
    reservation = service.get_proposal(first.id).reservation
    assert (reservation.state.value, reservation.filledNotional) == ("acknowledged", Decimal("50"))
    broker.frozen_account = None                                         # evidence arrives: fresh snapshot
    assert ok(service, buy("100.00")).submissionStatus.value == "submitted"   # 200 - 50 - 50 hold
    expect(ErrorCode.INSUFFICIENT_BUYING_POWER, lambda: service.create_proposal(buy("1.00"), "t"))


# --- 9-11: idempotent and monotonic observation -----------------------------------

def test_repeated_observation_of_the_same_fill_is_idempotent(tmp_path):
    broker = FakeBroker()
    budget(broker, "200")
    service = make_service(tmp_path, broker)
    first = ok(service, buy("100.00"))
    broker.fill(first.brokerOrderId, "0.5", "100", final=False)
    for _ in range(3):
        service.get_order(first.brokerOrderId)
        service.reconcile(first.id, "t")
    assert service.get_proposal(first.id).reservation.filledNotional == Decimal("50")
    assert service._expected("cash").value == Decimal("150")


def test_older_order_response_does_not_reduce_fills(tmp_path, monkeypatch):
    broker = FakeBroker()
    budget(broker, "200")
    broker.freeze_account()
    service = make_service(tmp_path, broker)
    first = ok(service, buy("100.00"))
    old = dict(broker.orders[first.brokerOrderId], filled_qty="0.2", filled_avg_price="100",
               status="partially_filled")
    broker.fill(first.brokerOrderId, "0.8", "100", final=False)
    service.get_order(first.brokerOrderId)
    monkeypatch.setattr(broker, "get_order", lambda order_id: dict(old))
    service.get_order(first.brokerOrderId)
    proposal = service.get_proposal(first.id)
    assert proposal.filledQty == Decimal("0.8") and proposal.reservation.filledNotional == Decimal("80.0")
    types = [e["type"] for e in Repository(tmp_path / "paper.sqlite3").events(first.id)]
    assert "stale_order_ignored" in types


def test_older_status_after_final_status_is_ignored(tmp_path, monkeypatch):
    broker = FakeBroker()
    budget(broker, "200")
    service = make_service(tmp_path, broker)
    first = ok(service, buy("100.00"))
    old = dict(broker.orders[first.brokerOrderId])                       # accepted, no fills
    broker.fill(first.brokerOrderId, "1", "100", final=True)
    service.get_order(first.brokerOrderId)
    monkeypatch.setattr(broker, "get_order", lambda order_id: dict(old))
    service.get_order(first.brokerOrderId)
    proposal = service.get_proposal(first.id)
    assert proposal.brokerStatus.value == "filled"
    assert proposal.reservation.state.value == "released"
    assert proposal.reservation.filledNotional == Decimal("100")


# --- 12-13: restart and processes ---------------------------------------------------

def test_restart_keeps_unreconciled_consumption(tmp_path):
    broker = FakeBroker()
    budget(broker, "100")
    broker.freeze_account()
    clock = Clock()
    first_service = make_service(tmp_path, broker, clock)
    first = ok(first_service, buy("100.00"))
    broker.fill(first.brokerOrderId, "1", "100", final=True)
    first_service.get_order(first.brokerOrderId)
    restarted = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    restarted.recover_pending()
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: restarted.create_proposal(buy("50.00"), "t"))
    assert submitted(broker, "notional") == ["100.00"]


def test_two_processes_share_the_ledger(tmp_path):
    broker = FakeBroker()
    budget(broker, "200")
    broker.freeze_account()
    clock = Clock()
    a = make_service(tmp_path, broker, clock)
    b = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    first = ok(a, buy("100.00"))
    broker.fill(first.brokerOrderId, "0.5", "100", final=False)
    a.get_order(first.brokerOrderId)
    # 200 - 50 consumed - 50 hold = 100 proven; two concurrent 100 buys -> only one.
    ids = [a.create_proposal(buy("100.00"), "t").id, b.create_proposal(buy("100.00"), "t").id]
    broker.pause_after["list_orders"] = threading.Barrier(2)
    results = []

    def run(service, pid):
        try:
            results.append(service.confirm(pid, "t").submissionStatus.value)
        except PaperError as error:
            results.append(error.code.value)

    threads = [threading.Thread(target=run, args=pair) for pair in ((a, ids[0]), (b, ids[1]))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    broker.pause_after.clear()
    assert sorted(results) == ["RESOURCE_RESERVED", "submitted"]
    assert submitted(broker, "notional") == ["100.00", "100.00"]


# --- 14: migration of Phase 5.5 data ------------------------------------------------

def test_phase55_released_reservation_with_consumption_is_blocked(tmp_path):
    path = tmp_path / "paper.sqlite3"
    conn = sqlite3.connect(path)
    for statement in (SCHEMA_V1 + MIGRATION_V2).split(";"):
        if statement.strip():
            conn.execute(statement)
    conn.execute("PRAGMA user_version = 2")
    conn.execute(
        "INSERT INTO proposals (id, client_order_id, environment, symbol, side, notional, qty, order_type, "
        "time_in_force, analysis_reference, created_at, expires_at, status, submission_status, broker_order_id, "
        "broker_status, filled_qty, filled_avg_price, last_error_code, checks, warnings, updated_at, version) "
        "VALUES (?, ?, 'paper', 'NVDA', 'buy', '100.00', NULL, 'market', 'day', NULL, 't', 't', 'confirmed', "
        "'submitted', 'ord-1', 'filled', '1', '100', NULL, '[]', '[]', 't', 1)", ("f" * 32, "atlas-" + "f" * 32))
    conn.execute("INSERT INTO reservations (proposal_id, resource_type, symbol, amount, consumed, state, "
                 "release_reason, broker_order_id, created_at, updated_at) VALUES (?, 'cash', NULL, '100.00', "
                 "'100', 'released', 'order_terminal', 'ord-1', 't', 't')", ("f" * 32,))
    conn.commit()
    conn.close()

    broker = FakeBroker()
    broker.add_position("NVDA", "1")
    service = PaperTradingService(settings(), broker, Repository(path), now=Clock())
    row = Repository(path).latest_reservation("f" * 32)
    assert (row["filled_qty"], row["filled_notional"]) == ("1", "100")
    error = expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(buy("10.00"), "t"))
    assert "cannot be verified" in error.message
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(sell("1"), "t"))
    assert broker.submits == []


# --- 17: uncertain submissions are still never resent ------------------------------

def test_uncertain_submission_is_not_resent_with_ledger(tmp_path):
    broker = FakeBroker()
    budget(broker, "200")
    service = make_service(tmp_path, broker)
    first = service.create_proposal(buy("100.00"), "t")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: service.confirm(first.id, "t"))
    broker.submit_mode = "accept"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: service.confirm(first.id, "t"))
    assert ok(service, buy("100.00")).submissionStatus.value == "submitted"    # 200 - 100 held
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(buy("1.00"), "t"))
    assert submitted(broker, "notional") == ["100.00", "100.00"]


def test_checkpoint_never_moves_to_a_stale_snapshot(tmp_path):
    broker = FakeBroker()
    broker.add_position("NVDA", "5")
    broker.freeze_position("NVDA")
    service = make_service(tmp_path, broker)
    first = ok(service, sell("2"))
    broker.fill(first.brokerOrderId, "2", "100", final=True)            # truth 3, snapshot 5
    assert ok(service, sell("1")).submissionStatus.value == "submitted"  # fits the ledger (3)
    # A later sale must still see 3 - 1 pending = 2, not the stale 5.
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(sell("3"), "t"))
    assert ok(service, sell("2")).submissionStatus.value == "submitted"
    assert submitted(broker, "qty") == ["2", "1", "2"]

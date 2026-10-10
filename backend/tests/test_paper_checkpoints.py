"""Phase 5.7: a zero net effect is not proof that no fills happened.

Checkpoints must never move to a snapshot once ATLAS has observed a fill on that
measure, even if buys and sells cancel out. Snapshots are frozen on purpose and
the fake never blocks over-commitment by itself: assertions check what was sent.
"""

import sqlite3
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from app.paper.models import ErrorCode, PaperError
from app.paper.repository import Repository
from app.paper.service import PaperTradingService
from tests.paper_fakes import Clock, FakeBroker, make_service, settings
from tests.test_paper_reservations import budget, buy, sell

BLOCKED = {"RESOURCE_RESERVED", "RECONCILIATION_REQUIRED"}


def attempt(service, request) -> str:
    try:
        return service.confirm(service.create_proposal(request, "t").id, "t").submissionStatus.value
    except PaperError as error:
        return error.code.value


def confirm(service, request):
    return service.confirm(service.create_proposal(request, "t").id, "t")


def sells(broker) -> list[Decimal]:
    return [Decimal(o["qty"]) for o in broker.submits if o["side"] == "sell"]


def buys(broker) -> list[Decimal]:
    return [Decimal(o["notional"]) for o in broker.submits if o["side"] == "buy"]


def compensated_shares(tmp_path: Path, broker: FakeBroker, clock: Clock | None = None):
    """Exact review reproduction up to the point of the two remaining sales."""
    budget(broker, "200")
    broker.add_position("NVDA", "1")
    service = make_service(tmp_path, broker, clock)
    purchase = confirm(service, buy("100"))
    broker.fill(purchase.brokerOrderId, "1", "100", True)
    service.get_order(purchase.brokerOrderId)
    broker.freeze_position("NVDA")                                  # frozen at 2 shares
    sale = confirm(service, sell("1"))
    broker.fill(sale.brokerOrderId, "1", "100", True)
    service.get_order(sale.brokerOrderId)                           # truth 1, snapshot 2, net effect 0
    return service


def test_review_reproduction_compensated_buy_and_sell(tmp_path):
    broker = FakeBroker()
    service = compensated_shares(tmp_path, broker)
    assert attempt(service, sell("1")) == "submitted"
    assert attempt(service, sell("1")) in BLOCKED
    assert sells(broker) == [Decimal(1), Decimal(1)]               # the earlier sale + one remaining sale
    assert sum(sells(broker)) - 1 <= 1                              # never more than the real share after the buy
    checkpoint = Repository(tmp_path / "paper.sqlite3").checkpoint("qty:NVDA")
    assert Decimal(checkpoint["value"]) == Decimal(1)               # never moved to the stale 2


def test_cash_compensation_with_stale_higher_balance(tmp_path):
    broker = FakeBroker()
    budget(broker, "100")
    broker.add_position("NVDA", "1")
    service = make_service(tmp_path, broker)
    sale = confirm(service, sell("1"))
    broker.fill(sale.brokerOrderId, "1", "100", True)               # cash 200
    service.get_order(sale.brokerOrderId)
    broker.freeze_account()                                          # frozen at 200
    purchase = confirm(service, buy("100.00"))
    broker.fill(purchase.brokerOrderId, "1", "100", True)           # truth 100, snapshot 200, net 0
    service.get_order(purchase.brokerOrderId)
    assert attempt(service, buy("100.00")) == "submitted"
    assert attempt(service, buy("100.00")) in BLOCKED
    assert buys(broker) == [Decimal("100.00"), Decimal("100.00")]
    assert Decimal(Repository(tmp_path / "paper.sqlite3").checkpoint("cash")["value"]) == Decimal(100)


def test_partial_fills_that_end_up_compensating(tmp_path):
    broker = FakeBroker()
    budget(broker, "200")
    broker.add_position("NVDA", "1")
    service = make_service(tmp_path, broker)
    purchase = confirm(service, buy("100"))
    broker.fill(purchase.brokerOrderId, "0.4", "100", False)
    service.get_order(purchase.brokerOrderId)
    broker.fill(purchase.brokerOrderId, "0.6", "100", True)
    service.get_order(purchase.brokerOrderId)
    broker.freeze_position("NVDA")                                  # 2 shares
    sale = confirm(service, sell("1"))
    for part, final in (("0.3", False), ("0.3", False), ("0.4", True)):
        broker.fill(sale.brokerOrderId, part, "100", final)
        service.get_order(sale.brokerOrderId)
    assert attempt(service, sell("0.6")) == "submitted"
    assert attempt(service, sell("0.6")) in BLOCKED
    assert sum(sells(broker)) == Decimal("1.6")                     # 1 earlier + 0.6 <= 1 real share left


def test_fresh_snapshot_after_compensation_has_no_double_count(tmp_path):
    broker = FakeBroker()
    budget(broker, "200")
    broker.add_position("NVDA", "1")
    service = make_service(tmp_path, broker)
    purchase = confirm(service, buy("100"))
    broker.fill(purchase.brokerOrderId, "1", "100", True)
    sale = confirm(service, sell("1"))
    broker.fill(sale.brokerOrderId, "1", "100", True)               # fresh: 1 share, cash 200
    assert attempt(service, sell("1")) == "submitted"               # exactly the real share
    assert attempt(service, sell("1")) == "INSUFFICIENT_POSITION"
    assert attempt(service, buy("200.00")) == "submitted"           # exactly the real cash
    assert sells(broker) == [Decimal(1), Decimal(1)]


def test_stale_snapshot_never_increases_availability(tmp_path):
    broker = FakeBroker()
    service = compensated_shares(tmp_path, broker)
    repo = Repository(tmp_path / "paper.sqlite3")
    before = repo.checkpoint("qty:NVDA")
    for _ in range(3):                                              # repeated attempts, re-reads
        assert attempt(service, sell("2")) in BLOCKED
    after = repo.checkpoint("qty:NVDA")
    assert (after["value"], after["base_effect"]) == (before["value"], before["base_effect"])
    assert service._expected("qty:NVDA").value == Decimal(1)


def test_restart_between_fills_and_next_confirmation(tmp_path):
    broker, clock = FakeBroker(), Clock()
    compensated_shares(tmp_path, broker, clock)
    restarted = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    restarted.recover_pending()
    assert attempt(restarted, sell("1")) == "submitted"
    assert attempt(restarted, sell("1")) in BLOCKED
    assert sells(broker) == [Decimal(1), Decimal(1)]


def test_two_instances_on_the_same_database(tmp_path):
    broker, clock = FakeBroker(), Clock()
    a = compensated_shares(tmp_path, broker, clock)
    b = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    assert attempt(b, sell("1")) == "submitted"
    assert attempt(a, sell("1")) in BLOCKED
    assert attempt(b, sell("1")) in BLOCKED
    assert sells(broker) == [Decimal(1), Decimal(1)]


def test_concurrent_confirmations_after_compensation(tmp_path):
    broker, clock = FakeBroker(), Clock()
    a = compensated_shares(tmp_path, broker, clock)
    b = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    ids = [a.create_proposal(sell("1"), "t").id, b.create_proposal(sell("1"), "t").id]
    broker.pause_after["get_position"] = threading.Barrier(2)       # both snapshots before any claim
    results: list[str] = []

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
    assert results.count("submitted") == 1 and set(results) - {"submitted"} <= BLOCKED
    assert sells(broker) == [Decimal(1), Decimal(1)]


def test_rereading_orders_creates_no_credit_and_no_double_consumption(tmp_path):
    broker = FakeBroker()
    service = compensated_shares(tmp_path, broker)
    repo = Repository(tmp_path / "paper.sqlite3")
    for order_id in list(broker.orders):
        for _ in range(3):
            service.get_order(order_id)
    for row in repo.ledger_rows():
        service.reconcile(row["proposal_id"], "t")
    assert service._expected("qty:NVDA").value == Decimal(1)
    assert service._expected("cash").value == Decimal(200)
    assert attempt(service, sell("1")) == "submitted"
    assert attempt(service, sell("1")) in BLOCKED


def test_checkpoint_may_still_move_before_any_fill(tmp_path):
    """Without any ATLAS fill on a measure the snapshot cannot be missing one, so the
    checkpoint follows it (for example after a change made outside ATLAS)."""
    broker = FakeBroker()
    broker.add_position("NVDA", "1")
    service = make_service(tmp_path, broker)
    first = service.create_proposal(sell("1"), "t")
    broker.submit_mode = "reject"
    with pytest.raises(PaperError):
        service.confirm(first.id, "t")                              # creates checkpoint 1, no fill
    broker.submit_mode = "accept"
    broker.add_position("NVDA", "3")                                # changed outside ATLAS
    assert attempt(service, sell("3")) == "submitted"
    assert Decimal(Repository(tmp_path / "paper.sqlite3").checkpoint("qty:NVDA")["value"]) == Decimal(3)


def test_migration_from_phase56_distrusts_moved_checkpoints_with_fills(tmp_path):
    path = tmp_path / "paper.sqlite3"
    broker = FakeBroker()
    budget(broker, "200")
    broker.add_position("NVDA", "1")
    broker.add_position("AAPL", "1")
    service = make_service(tmp_path, broker)
    purchase = confirm(service, buy("100"))
    broker.fill(purchase.brokerOrderId, "1", "100", True)
    service.get_order(purchase.brokerOrderId)
    # Simulate what the 5.6 rule could leave behind: a checkpoint moved after fills,
    # plus an untouched checkpoint on a measure without fills.
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ledger_checkpoints SET value = '2', updated_at = 'later' WHERE measure = 'qty:NVDA'")
        conn.execute("INSERT INTO ledger_checkpoints VALUES ('qty:AAPL', '1', '0', 't0', 'later')")
        conn.execute("PRAGMA user_version = 3")
    repo = Repository(path)                                          # migrates 3 -> 5
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert repo.checkpoint("qty:NVDA")["value"] is None              # fills recorded: distrusted
    # Phase 5.8: dates prove nothing, so "never moved" is not trusted either; cash has fills.
    assert repo.checkpoint("cash")["value"] is None
    assert repo.checkpoint("qty:AAPL")["value"] == "1"               # no fills on this measure: kept
    restarted = PaperTradingService(settings(), broker, repo, now=Clock())
    assert attempt(restarted, sell("1")) == "RECONCILIATION_REQUIRED"
    assert sells(broker) == []

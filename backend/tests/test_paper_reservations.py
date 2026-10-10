"""Phase 5.5: atomic reservations across proposals (shares and cash).

Concurrency is driven by barriers on fake broker reads (no sleeps): every thread
finishes its broker snapshot before any of them reaches the claim transaction.
Assertions check the quantities actually sent to the fake broker.
"""

import sqlite3
import threading
from decimal import Decimal

import pytest

from app.paper.models import ErrorCode, PaperError, ProposalRequest
from app.paper.repository import SCHEMA_V1, Repository
from app.paper.service import PaperTradingService
from tests.paper_fakes import Clock, FakeBroker, make_service, settings


def buy(notional="100.00", symbol="NVDA"):
    return ProposalRequest(symbol=symbol, side="buy", notional=notional)


def sell(qty="1", symbol="NVDA"):
    return ProposalRequest(symbol=symbol, side="sell", qty=qty)


def expect(code, fn):
    with pytest.raises(PaperError) as excinfo:
        fn()
    assert excinfo.value.code is code, excinfo.value
    return excinfo.value


def budget(broker: FakeBroker, amount: str) -> None:
    broker.account.update(cash=amount, buying_power=amount, non_marginable_buying_power=amount)


def confirm_concurrently(pairs, broker: FakeBroker, pause_on: str) -> list[str]:
    """pairs: [(service, proposal_id)]. All snapshots finish before any claim."""
    broker.pause_after[pause_on] = threading.Barrier(len(pairs))
    results: list[str] = []
    lock = threading.Lock()

    def run(service, pid):
        try:
            value = service.confirm(pid, "c").submissionStatus.value
        except PaperError as error:
            value = error.code.value
        with lock:
            results.append(value)

    threads = [threading.Thread(target=run, args=pair) for pair in pairs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    broker.pause_after.clear()
    return sorted(results)


@pytest.fixture
def broker():
    return FakeBroker()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def svc(tmp_path, broker, clock):
    return make_service(tmp_path, broker, clock)


def active(tmp_path):
    return Repository(tmp_path / "paper.sqlite3").all_active_reservations()


# --- Sells ---------------------------------------------------------------------

def test_1_2_two_sells_of_the_only_share_submit_once(svc, broker):
    broker.add_position("NVDA", "1")
    ids = [svc.create_proposal(sell("1"), "c").id for _ in range(2)]
    results = confirm_concurrently([(svc, i) for i in ids], broker, "get_position")
    assert [s["qty"] for s in broker.submits] == ["1"]
    assert results == ["RESOURCE_RESERVED", "submitted"]


def test_3_sells_that_fit_together_both_submit(svc, broker):
    broker.add_position("NVDA", "2")
    ids = [svc.create_proposal(sell("1"), "c").id for _ in range(2)]
    assert confirm_concurrently([(svc, i) for i in ids], broker, "get_position") == ["submitted", "submitted"]
    assert sorted(s["qty"] for s in broker.submits) == ["1", "1"]


def test_4_sells_of_different_symbols_do_not_interfere(svc, broker):
    broker.add_position("NVDA", "1")
    broker.add_position("AAPL", "1")
    ids = [svc.create_proposal(sell("1", "NVDA"), "c").id, svc.create_proposal(sell("1", "AAPL"), "c").id]
    assert confirm_concurrently([(svc, i) for i in ids], broker, "get_position") == ["submitted", "submitted"]
    assert sorted(s["symbol"] for s in broker.submits) == ["AAPL", "NVDA"]


def test_5_uncertain_sell_keeps_its_shares(svc, broker, tmp_path):
    broker.add_position("NVDA", "1")
    first = svc.create_proposal(sell("1"), "c")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(first.id, "c"))
    broker.submit_mode = "accept"
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: svc.create_proposal(sell("1"), "c"))
    assert len(broker.submits) == 1
    assert [r["state"] for r in active(tmp_path)] == ["held"]


def test_6_broker_acknowledged_sell_is_not_subtracted_twice(svc, broker):
    broker.add_position("NVDA", "2")
    svc.confirm(svc.create_proposal(sell("1"), "c").id, "c")      # open at broker: qty_available 1
    second = svc.create_proposal(sell("1"), "c")                  # would fail if subtracted twice
    assert svc.confirm(second.id, "c").submissionStatus.value == "submitted"
    assert [s["qty"] for s in broker.submits] == ["1", "1"]
    expect(ErrorCode.INSUFFICIENT_POSITION, lambda: svc.create_proposal(sell("0.1"), "c"))


def test_7_partial_sell_fill_reduces_the_commitment(svc, broker):
    broker.add_position("NVDA", "5")
    first = svc.confirm(svc.create_proposal(sell("4"), "c").id, "c")
    broker.fill(first.brokerOrderId, "3", "100", final=False)     # position 2, 1 share still held
    svc.get_order(first.brokerOrderId)
    proposal = svc.get_proposal(first.id)
    assert proposal.reservation.state.value == "acknowledged"
    assert proposal.reservation.consumed == Decimal("3")
    # Available = min(qty_available 1, qty 2 - remaining 1) = 1; the full 4 is not subtracted again.
    assert svc.confirm(svc.create_proposal(sell("1"), "c").id, "c").submissionStatus.value == "submitted"
    expect(ErrorCode.INSUFFICIENT_POSITION, lambda: svc.create_proposal(sell("0.5"), "c"))


def test_8_pending_cancel_keeps_shares_until_cancel_is_final(svc, broker):
    broker.add_position("NVDA", "1")
    first = svc.confirm(svc.create_proposal(sell("1"), "c").id, "c")
    result = svc.cancel_order(first.brokerOrderId, "c")
    assert result["order"].status.value == "pending_cancel"
    assert svc.get_proposal(first.id).reservation.state.value == "acknowledged"
    broker.freeze_position("NVDA")                                # even a stale snapshot cannot free it
    broker.frozen_positions["NVDA"]["qty_available"] = "1"
    expect(ErrorCode.INSUFFICIENT_POSITION, lambda: svc.create_proposal(sell("1"), "c"))
    broker.frozen_positions.clear()
    broker.finish_cancel(first.brokerOrderId)
    svc.get_order(first.brokerOrderId)
    reservation = svc.get_proposal(first.id).reservation
    assert (reservation.state.value, reservation.releaseReason.value) == ("released", "order_terminal")
    assert svc.confirm(svc.create_proposal(sell("1"), "c").id, "c").submissionStatus.value == "submitted"


def test_9_restart_keeps_sell_protection(tmp_path, broker, clock):
    broker.add_position("NVDA", "1")
    first_service = make_service(tmp_path, broker, clock)
    proposal = first_service.create_proposal(sell("1"), "c")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: first_service.confirm(proposal.id, "c"))
    restarted = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    restarted.recover_pending()
    broker.submit_mode = "accept"
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: restarted.create_proposal(sell("1"), "c"))
    assert len(broker.submits) == 1


# --- Buys ----------------------------------------------------------------------

def test_10_uncertain_buy_protects_its_budget(svc, broker, tmp_path):
    budget(broker, "100")
    first = svc.create_proposal(buy("100.00"), "c")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(first.id, "c"))
    broker.submit_mode = "accept"
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: svc.create_proposal(buy("100.00"), "c"))
    assert [s["notional"] for s in broker.submits] == ["100.00"]
    assert svc.get_proposal(first.id).reservation.state.value == "held"


def test_10b_uncertain_buy_blocks_a_proposal_prepared_earlier(svc, broker):
    budget(broker, "100")
    first, second = svc.create_proposal(buy("100.00"), "c"), svc.create_proposal(buy("100.00"), "c")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(first.id, "c"))
    broker.submit_mode = "accept"
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: svc.confirm(second.id, "c"))
    assert len(broker.submits) == 1


def test_11_concurrent_buys_cannot_exceed_the_budget(svc, broker):
    budget(broker, "150")
    ids = [svc.create_proposal(buy("100.00"), "c").id for _ in range(2)]
    results = confirm_concurrently([(svc, i) for i in ids], broker, "list_orders")
    assert results == ["RESOURCE_RESERVED", "submitted"]
    assert [s["notional"] for s in broker.submits] == ["100.00"]


def test_12_buys_that_fit_together_both_submit(svc, broker):
    budget(broker, "200")
    ids = [svc.create_proposal(buy("100.00"), "c").id for _ in range(2)]
    assert confirm_concurrently([(svc, i) for i in ids], broker, "list_orders") == ["submitted", "submitted"]
    assert [s["notional"] for s in broker.submits] == ["100.00", "100.00"]


def test_13_acknowledged_buy_is_not_subtracted_twice(svc, broker):
    budget(broker, "200")
    svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c")  # broker now holds 100
    assert svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c").submissionStatus.value == "submitted"
    assert len(broker.submits) == 2


def test_14_stale_account_after_acceptance_cannot_overcommit(svc, broker):
    budget(broker, "100")
    broker.freeze_account()                                       # snapshot never shows the hold
    svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c")
    # min(stale nmbp 100, cash 100 - open hold 100) = 0
    expect(ErrorCode.INSUFFICIENT_BUYING_POWER, lambda: svc.create_proposal(buy("100.00"), "c"))
    assert len(broker.submits) == 1


def test_14b_stale_order_list_still_protects_acknowledged_buy(svc, broker, monkeypatch):
    budget(broker, "100")
    broker.freeze_account()
    svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c")
    monkeypatch.setattr(broker, "list_orders", lambda status, limit: [])  # order list lags too
    expect(ErrorCode.RESOURCE_RESERVED, lambda: svc.create_proposal(buy("100.00"), "c"))
    assert len(broker.submits) == 1


def test_15_partial_then_full_buy_fill(svc, broker):
    budget(broker, "200")
    first = svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c")
    broker.fill(first.brokerOrderId, "0.5", "100", final=False)
    svc.get_order(first.brokerOrderId)
    reservation = svc.get_proposal(first.id).reservation
    assert (reservation.state.value, reservation.consumed) == ("acknowledged", Decimal("50.0"))
    expect(ErrorCode.INSUFFICIENT_BUYING_POWER, lambda: svc.create_proposal(buy("100.01"), "c"))
    broker.fill(first.brokerOrderId, "0.5", "100", final=True)
    svc.get_order(first.brokerOrderId)
    reservation = svc.get_proposal(first.id).reservation
    assert (reservation.state.value, reservation.releaseReason.value) == ("released", "order_terminal")
    assert svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c").submissionStatus.value == "submitted"
    expect(ErrorCode.INSUFFICIENT_BUYING_POWER, lambda: svc.create_proposal(buy("1.00"), "c"))


def test_16_explicit_rejection_releases(svc, broker):
    budget(broker, "100")
    first = svc.create_proposal(buy("100.00"), "c")
    broker.submit_mode = "reject"
    expect(ErrorCode.BROKER_REJECTED, lambda: svc.confirm(first.id, "c"))
    reservation = svc.get_proposal(first.id).reservation
    assert (reservation.state.value, reservation.releaseReason.value) == ("released", "broker_rejected")
    broker.submit_mode = "accept"
    assert svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c").submissionStatus.value == "submitted"


def test_17_proven_failure_before_send_releases(svc, broker, tmp_path):
    budget(broker, "100")
    first = svc.create_proposal(buy("100.00"), "c")
    broker.submit_mode = "not_sent"
    expect(ErrorCode.BROKER_UNAVAILABLE, lambda: svc.confirm(first.id, "c"))
    assert active(tmp_path) == []
    broker.submit_mode = "accept"
    assert svc.confirm(first.id, "c").submissionStatus.value == "submitted"
    states = [r["state"] for r in Repository(tmp_path / "paper.sqlite3").reservations_of(first.id)]
    assert states == ["released", "acknowledged"]


def test_18_uncertain_buy_not_found_stays_protected(svc, broker, tmp_path):
    budget(broker, "100")
    first = svc.create_proposal(buy("100.00"), "c")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(first.id, "c"))
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.reconcile(first.id, "c"))
    assert [r["state"] for r in active(tmp_path)] == ["held"]
    broker.submit_mode = "accept"
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: svc.create_proposal(buy("50.00"), "c"))


def test_18b_uncertain_buy_found_later_becomes_acknowledged(svc, broker):
    budget(broker, "200")
    first = svc.create_proposal(buy("100.00"), "c")
    broker.submit_mode = "unknown_missing"
    expect(ErrorCode.SUBMISSION_UNCERTAIN, lambda: svc.confirm(first.id, "c"))
    broker._store(dict(broker.submits[0]))                        # the order shows up at Alpaca
    broker.submit_mode = "accept"
    # The fresh open-order list reveals it: no double count, budget 200 - 100 left.
    assert svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c").submissionStatus.value == "submitted"
    assert svc.get_proposal(first.id).reservation.state.value == "acknowledged"
    assert len(broker.submits) == 2


# --- Persistence -------------------------------------------------------------------

def test_19_repeated_confirmation_does_not_duplicate_reservations(svc, broker, tmp_path):
    proposal = svc.create_proposal(buy("100.00"), "c")
    svc.confirm(proposal.id, "c")
    svc.confirm(proposal.id, "c")
    assert len(Repository(tmp_path / "paper.sqlite3").reservations_of(proposal.id)) == 1
    assert len(broker.submits) == 1


def test_19b_database_rejects_a_second_active_reservation(svc, tmp_path):
    proposal = svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c")
    repo = Repository(tmp_path / "paper.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction() as conn:
            conn.execute("INSERT INTO reservations (proposal_id, resource_type, amount, state, created_at, "
                         "updated_at) VALUES (?, 'cash', '1', 'held', 't', 't')", (proposal.id,))


def test_20_two_repository_instances_on_one_database(tmp_path, broker, clock):
    broker.add_position("NVDA", "1")
    a = make_service(tmp_path, broker, clock)
    b = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    pa, pb = a.create_proposal(sell("1"), "c").id, b.create_proposal(sell("1"), "c").id
    results = confirm_concurrently([(a, pa), (b, pb)], broker, "get_position")
    assert results == ["RESOURCE_RESERVED", "submitted"]
    assert [s["qty"] for s in broker.submits] == ["1"]


def test_21_rollback_leaves_no_reservation_without_intent(svc, tmp_path):
    proposal = svc.create_proposal(buy("100.00"), "c")
    repo = Repository(tmp_path / "paper.sqlite3")
    reservation = {"resource_type": "cash", "symbol": None, "amount": "100.00", "created_at": "t"}
    expected = {"status": ("open",), "submission_status": ("not_submitted",)}
    changes = {"status": "confirmed", "submission_status": "submitting"}

    def refuse(rows):
        raise PaperError(ErrorCode.RESOURCE_RESERVED, "no")

    with pytest.raises(PaperError):
        repo.claim(proposal.id, expected, changes, reservation, {"at": "t", "type": "submission_intent"}, refuse)
    with pytest.raises(KeyError):  # the intent event fails after the reservation insert
        repo.claim(proposal.id, expected, changes, reservation, {"type": "missing_at"}, lambda rows: None)
    row = repo.get_proposal(proposal.id)
    assert (row["status"], row["submission_status"]) == ("open", "not_submitted")
    assert repo.reservations_of(proposal.id) == []
    assert "submission_intent" not in [e["type"] for e in repo.events(proposal.id)]


def _phase5_database(path):
    """A Phase 5 (schema v1) database with proposals in several states."""
    conn = sqlite3.connect(path)
    for statement in SCHEMA_V1.split(";"):
        if statement.strip():
            conn.execute(statement)
    base = dict(environment="paper", order_type="market", time_in_force="day", analysis_reference=None,
                created_at="2026-10-05T15:00:00.000000+00:00", expires_at="2026-10-05T15:05:00.000000+00:00",
                checks="[]", warnings="[]", updated_at="2026-10-05T15:00:00.000000+00:00", version=1,
                broker_order_id=None, broker_status=None, filled_qty=None, filled_avg_price=None,
                last_error_code=None)
    rows = [
        dict(base, id="a" * 32, client_order_id="atlas-" + "a" * 32, symbol="NVDA", side="sell", notional=None,
             qty="1", status="confirmed", submission_status="submission_unknown"),
        dict(base, id="b" * 32, client_order_id="atlas-" + "b" * 32, symbol="NVDA", side="buy",
             notional="100.00", qty=None, status="confirmed", submission_status="submitted",
             broker_order_id="ord-b", broker_status="partially_filled", filled_qty="0.4", filled_avg_price="100"),
        dict(base, id="c" * 32, client_order_id="atlas-" + "c" * 32, symbol="NVDA", side="buy",
             notional="50.00", qty=None, status="confirmed", submission_status="submitted",
             broker_order_id="ord-c", broker_status="filled", filled_qty="0.5", filled_avg_price="100"),
        dict(base, id="d" * 32, client_order_id="atlas-" + "d" * 32, symbol="NVDA", side="buy",
             notional="20.00", qty=None, status="open", submission_status="not_submitted"),
        dict(base, id="e" * 32, client_order_id="atlas-" + "e" * 32, symbol="AAPL", side="sell", notional=None,
             qty="2", status="confirmed", submission_status="submitting"),
    ]
    for row in rows:
        conn.execute(f"INSERT INTO proposals ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                     list(row.values()))
    conn.commit()
    conn.close()


def test_22_migrates_a_phase5_database_conservatively(tmp_path):
    path = tmp_path / "paper.sqlite3"
    _phase5_database(path)
    repo = Repository(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3   # 5.5 (v2) then 5.6 (v3)
        assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 5
        # Phase 5.6: measures touched by pre-5.6 rows have no trusted baseline.
        unverifiable = {r[0] for r in conn.execute("SELECT measure FROM ledger_checkpoints WHERE value IS NULL")}
        assert unverifiable == {"cash", "qty:NVDA", "qty:AAPL"}
    by_proposal = {r["proposal_id"][0]: r for r in repo.all_active_reservations()}
    assert set(by_proposal) == {"a", "b", "e"}                     # filled and never-sent rows get none
    assert (by_proposal["a"]["state"], by_proposal["a"]["amount"], by_proposal["a"]["resource_type"]) == ("held", "1", "shares")
    assert (by_proposal["b"]["state"], by_proposal["b"]["consumed"]) == ("acknowledged", "40.0")
    assert by_proposal["e"]["state"] == "held"
    Repository(path)                                                # idempotent: no second migration
    assert len(Repository(path).all_active_reservations()) == 3


def test_23_recovers_phase5_submissions_before_new_confirmations(tmp_path, broker, clock):
    path = tmp_path / "paper.sqlite3"
    _phase5_database(path)
    broker.add_position("AAPL", "2")
    service = PaperTradingService(settings(), broker, Repository(path), now=clock)
    service.recover_pending()
    repo = Repository(path)
    assert repo.get_proposal("e" * 32)["submission_status"] == "submission_unknown"
    assert [r["state"] for r in repo.reservations_of("e" * 32)] == ["held"]
    # The migrated uncertain AAPL sell still holds both shares.
    expect(ErrorCode.RECONCILIATION_REQUIRED, lambda: service.create_proposal(sell("1", "AAPL"), "c"))
    assert broker.submits == []


def test_23b_recovery_leaves_live_submissions_of_other_processes(tmp_path, broker, clock):
    owner = make_service(tmp_path, broker, clock)
    proposal = owner.create_proposal(buy("10.00"), "c")
    Repository(tmp_path / "paper.sqlite3").transition(
        proposal.id, {"status": ("open",)},
        {"status": "confirmed", "submission_status": "submitting", "submit_owner": "other-process",
         "submit_lease_until": "2026-10-05T15:02:00.000000+00:00"},
        {"at": "t", "type": "submission_intent"})
    other = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    assert other.recover_pending() == []
    assert other.get_proposal(proposal.id).submissionStatus.value == "submitting"
    expect(ErrorCode.SUBMISSION_IN_PROGRESS, lambda: other.reconcile(proposal.id, "c"))
    clock.advance(180)                                              # lease expired: now recoverable
    assert other.recover_pending() == [proposal.id]
    assert other.get_proposal(proposal.id).submissionStatus.value == "submission_unknown"


def test_24_reads_and_cancels_keep_proposal_and_reservation_in_sync(svc, broker, tmp_path):
    budget(broker, "1000")
    proposals = [svc.confirm(svc.create_proposal(buy("100.00"), "c").id, "c") for _ in range(3)]
    broker.fill(proposals[0].brokerOrderId, "1", "100", final=True)
    svc.get_order(proposals[0].brokerOrderId)                     # filled -> released
    svc.cancel_order(proposals[1].brokerOrderId, "c")             # pending_cancel -> kept
    broker.cancel_mode = "filled_race"
    svc.cancel_order(proposals[2].brokerOrderId, "c")             # fill won the race -> released
    repo = Repository(tmp_path / "paper.sqlite3")
    for proposal in proposals:
        row = repo.get_proposal(proposal.id)
        reservation = repo.latest_reservation(proposal.id)
        final = row["broker_status"] in {"filled", "canceled", "expired", "rejected"}
        assert (reservation["state"] == "released") is final, (row["broker_status"], reservation["state"])
    assert [repo.get_proposal(p.id)["broker_status"] for p in proposals] == ["filled", "pending_cancel", "filled"]

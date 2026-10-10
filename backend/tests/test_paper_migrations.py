"""Phase 5.8: repairing checkpoints from Phase 5.6 (v3) and Phase 5.7 (v4) databases.

Dates cannot prove that a checkpoint kept its initial value. Any checkpoint of a
measure with recorded ATLAS fills, in a database written before v5, is distrusted.
A fixed clock makes created_at == updated_at, as in the review reproduction.
"""

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from app.paper.models import ErrorCode, PaperError
from app.paper.repository import Repository
from app.paper.service import PaperTradingService
from tests.paper_fakes import Clock, FakeBroker, make_service, settings
from tests.test_paper_reservations import budget, buy, sell


def attempt(service, request) -> str:
    try:
        return service.confirm(service.create_proposal(request, "t").id, "t").submissionStatus.value
    except PaperError as error:
        return error.code.value


def confirm(service, request):
    return service.confirm(service.create_proposal(request, "t").id, "t")


def counts(path: Path) -> dict:
    with sqlite3.connect(path) as conn:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("proposals", "reservations", "events")}


def contaminate(path: Path, version: int, measure: str, value: str) -> None:
    """What the 5.6 net-zero rule could leave: an inflated checkpoint whose dates are
    equal (fixed clock), stored in a database at `version`."""
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ledger_checkpoints SET value = ?, updated_at = created_at WHERE measure = ?",
                     (value, measure))
        conn.execute(f"PRAGMA user_version = {version}")


def share_history(tmp_path: Path, broker: FakeBroker, clock: Clock) -> PaperTradingService:
    """Review scenario: 1 share, buy 1 filled, freeze at 2, sell 1 filled (real 1),
    then an order canceled without fills (no active reservation left)."""
    budget(broker, "1000")
    broker.add_position("NVDA", "1")
    service = make_service(tmp_path, broker, clock)
    purchase = confirm(service, buy("100"))
    broker.fill(purchase.brokerOrderId, "1", "100", True)
    service.get_order(purchase.brokerOrderId)
    broker.freeze_position("NVDA")
    sale = confirm(service, sell("1"))
    broker.fill(sale.brokerOrderId, "1", "100", True)
    service.get_order(sale.brokerOrderId)
    extra = confirm(service, buy("10.00"))
    service.cancel_order(extra.brokerOrderId, "t")
    broker.finish_cancel(extra.brokerOrderId)
    service.get_order(extra.brokerOrderId)
    return service


def restarted(tmp_path: Path, broker: FakeBroker, clock: Clock) -> PaperTradingService:
    service = PaperTradingService(settings(), broker, Repository(tmp_path / "paper.sqlite3"), now=clock)
    service.recover_pending()
    return service


@pytest.mark.parametrize("version", [3, 4])
def test_inflated_share_checkpoint_with_equal_dates_is_blocked(tmp_path, version):
    broker, clock = FakeBroker(), Clock()
    share_history(tmp_path, broker, clock)
    contaminate(tmp_path / "paper.sqlite3", version, "qty:NVDA", "2")
    sent = len(broker.submits)
    service = restarted(tmp_path, broker, clock)                  # migrates, then restarts
    assert Repository(tmp_path / "paper.sqlite3").checkpoint("qty:NVDA")["value"] is None
    assert attempt(service, sell("2")) == "RECONCILIATION_REQUIRED"
    assert attempt(service, sell("1")) == "RECONCILIATION_REQUIRED"
    assert len(broker.submits) == sent                            # zero new submissions


@pytest.mark.parametrize("version", [3, 4])
def test_inflated_cash_checkpoint_with_equal_dates_is_blocked(tmp_path, version):
    broker, clock = FakeBroker(), Clock()
    budget(broker, "100")
    broker.add_position("NVDA", "1")
    service = make_service(tmp_path, broker, clock)
    sale = confirm(service, sell("1"))
    broker.fill(sale.brokerOrderId, "1", "100", True)             # cash 200
    service.get_order(sale.brokerOrderId)
    broker.freeze_account()
    purchase = confirm(service, buy("100.00"))
    broker.fill(purchase.brokerOrderId, "1", "100", True)         # real 100, snapshot 200
    service.get_order(purchase.brokerOrderId)
    contaminate(tmp_path / "paper.sqlite3", version, "cash", "200")
    sent = len(broker.submits)
    again = restarted(tmp_path, broker, clock)
    assert Repository(tmp_path / "paper.sqlite3").checkpoint("cash")["value"] is None
    assert attempt(again, buy("150.00")) == "RECONCILIATION_REQUIRED"
    assert len(broker.submits) == sent


def test_partial_and_final_fills_make_both_measures_unverifiable(tmp_path):
    broker, clock = FakeBroker(), Clock()
    budget(broker, "1000")
    broker.add_position("AAPL", "5")
    service = make_service(tmp_path, broker, clock)
    open_sale = confirm(service, sell("4", "AAPL"))
    broker.fill(open_sale.brokerOrderId, "1", "100", False)       # partial, still open
    service.get_order(open_sale.brokerOrderId)
    with sqlite3.connect(tmp_path / "paper.sqlite3") as conn:
        conn.execute("PRAGMA user_version = 4")
    repo = Repository(tmp_path / "paper.sqlite3")
    assert repo.checkpoint("qty:AAPL")["value"] is None
    assert repo.checkpoint("cash")["value"] is None               # a sale changes cash too


def test_measures_without_fills_keep_their_checkpoints(tmp_path):
    broker, clock = FakeBroker(), Clock()
    budget(broker, "1000")
    broker.add_position("AAPL", "3")
    service = make_service(tmp_path, broker, clock)
    rejected = service.create_proposal(sell("1", "AAPL"), "t")
    broker.submit_mode = "reject"
    with pytest.raises(PaperError):
        service.confirm(rejected.id, "t")                          # checkpoints created, no fills
    with sqlite3.connect(tmp_path / "paper.sqlite3") as conn:
        conn.execute("PRAGMA user_version = 4")
    repo = Repository(tmp_path / "paper.sqlite3")
    assert repo.checkpoint("qty:AAPL")["value"] == "3"
    assert repo.checkpoint("cash")["value"] == "1000"


def test_already_unverifiable_checkpoints_stay_unverifiable(tmp_path):
    broker, clock = FakeBroker(), Clock()
    share_history(tmp_path, broker, clock)
    path = tmp_path / "paper.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ledger_checkpoints SET value = NULL WHERE measure = 'qty:NVDA'")
        conn.execute("PRAGMA user_version = 4")
    repo = Repository(path)
    assert repo.checkpoint("qty:NVDA")["value"] is None
    assert repo.checkpoint("qty:NVDA")["base_effect"] is not None


def test_repeated_reopening_is_idempotent_and_preserves_data(tmp_path):
    broker, clock = FakeBroker(), Clock()
    share_history(tmp_path, broker, clock)
    path = tmp_path / "paper.sqlite3"
    contaminate(path, 3, "qty:NVDA", "2")
    before = counts(path)
    with sqlite3.connect(path) as conn:
        reservations_before = conn.execute("SELECT * FROM reservations ORDER BY id").fetchall()
        events_before = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    Repository(path)
    after_first = counts(path)
    with sqlite3.connect(path) as conn:
        snapshot = (conn.execute("SELECT * FROM ledger_checkpoints ORDER BY measure").fetchall(),
                    conn.execute("SELECT * FROM events ORDER BY id").fetchall())
        assert conn.execute("SELECT * FROM reservations ORDER BY id").fetchall() == reservations_before
        assert conn.execute("SELECT * FROM events ORDER BY id").fetchall()[:len(events_before)] == events_before
    for _ in range(3):
        Repository(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        assert (conn.execute("SELECT * FROM ledger_checkpoints ORDER BY measure").fetchall(),
                conn.execute("SELECT * FROM events ORDER BY id").fetchall()) == snapshot
    assert after_first["proposals"] == before["proposals"]
    assert after_first["reservations"] == before["reservations"]
    assert after_first["events"] >= before["events"]               # audit events are only added
    assert counts(path) == after_first


def test_failed_migration_rolls_back_completely(tmp_path, monkeypatch):
    broker, clock = FakeBroker(), Clock()
    share_history(tmp_path, broker, clock)
    path = tmp_path / "paper.sqlite3"
    contaminate(path, 3, "qty:NVDA", "2")
    before = counts(path)

    original = Repository._distrust_filled_checkpoints

    def explode(conn):
        original(conn)                                             # changes happen ...
        raise RuntimeError("disk full")                            # ... then the migration fails

    monkeypatch.setattr(Repository, "_distrust_filled_checkpoints", staticmethod(explode))
    with pytest.raises(RuntimeError):
        Repository(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("SELECT value FROM ledger_checkpoints WHERE measure = 'qty:NVDA'").fetchone()[0] == "2"
    assert counts(path) == before

"""Polling contract for the frontend (Phase 6 handoff, section 7). Simulated broker only.

- GET /proposals/{id} reads SQLite only: it never calls the broker and never discovers a fill.
- GET /orders/{orderId} reads the broker and updates the linked proposal and reservation.
- POST /proposals/{id}/reconcile looks the order up by clientOrderId (read-only) and never submits.
- A live submit lease answers SUBMISSION_IN_PROGRESS; reading the proposal never recovers it.
- pending_cancel is not final.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.paper import routes
from app.paper.repository import Repository
from tests.paper_fakes import Clock, FakeBroker, make_service

client = TestClient(main.app)
ORIGIN = {"Origin": "http://localhost:3000"}
CONFIRM = {"confirmation": "CONFIRM_PAPER_ORDER"}
BUY = {"symbol": "NVDA", "side": "buy", "notional": "100.00"}


@pytest.fixture
def broker():
    return FakeBroker()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def installed(monkeypatch, tmp_path, broker, clock):
    service = make_service(tmp_path, broker, clock)
    monkeypatch.setitem(routes._state, "service", service)
    return service


def post(path, body=None):
    return client.post(path, json=body, headers=ORIGIN)


def get(path):
    return client.get(path)


def create():
    response = post("/api/paper/proposals", BUY)
    assert response.status_code == 201
    return response.json()["id"]


def test_get_proposal_does_not_reach_the_broker_but_get_order_updates_it(installed, broker):
    pid = create()
    confirmed = post(f"/api/paper/proposals/{pid}/confirm", CONFIRM).json()
    order_id = confirmed["brokerOrderId"]
    assert confirmed["brokerStatus"] == "accepted"

    broker.fill(order_id, "1", "100", final=True)  # the order fills at the broker
    broker.calls.clear()

    local = get(f"/api/paper/proposals/{pid}").json()
    assert broker.calls == []  # SQLite only
    assert local["brokerStatus"] == "accepted" and local["filledQty"] == "0"
    assert local["reservation"]["state"] == "acknowledged"

    order = get(f"/api/paper/orders/{order_id}").json()
    assert broker.calls == ["get_order"]
    assert order["status"] == "filled" and order["proposalId"] == pid

    updated = get(f"/api/paper/proposals/{pid}").json()
    assert updated["brokerStatus"] == "filled" and updated["filledQty"] == "1"
    assert updated["reservation"]["state"] == "released"
    assert updated["reservation"]["releaseReason"] == "order_terminal"
    assert len(broker.submits) == 1


def test_uncertain_submission_is_resolved_only_by_reconcile_without_resending(installed, broker):
    pid = create()
    broker.submit_mode = "unknown_missing"
    first = post(f"/api/paper/proposals/{pid}/confirm", CONFIRM)
    assert first.status_code == 409 and first.json()["code"] == "SUBMISSION_UNCERTAIN"

    broker.calls.clear()
    local = get(f"/api/paper/proposals/{pid}").json()
    assert broker.calls == []
    assert local["submissionStatus"] == "submission_unknown" and local["brokerOrderId"] is None

    not_yet = post(f"/api/paper/proposals/{pid}/reconcile")
    assert not_yet.status_code == 409 and not_yet.json()["code"] == "SUBMISSION_UNCERTAIN"

    broker._store(dict(broker.submits[0]))  # the order appears at Alpaca later
    found = post(f"/api/paper/proposals/{pid}/reconcile")
    assert found.status_code == 200
    body = found.json()
    assert body["submissionStatus"] == "submitted" and body["brokerOrderId"]

    assert len(broker.submits) == 1  # the original attempt only
    assert "submit_order" not in broker.calls
    assert set(broker.calls) <= {"get_order_by_client_id", "get_order"}


def test_live_lease_returns_in_progress_and_reading_sqlite_never_recovers_it(installed, broker, clock, tmp_path):
    pid = create()
    # The process that claimed the proposal was interrupted while sending; its lease is still live.
    lease_until = (clock() + timedelta(seconds=120)).isoformat(timespec="microseconds")
    Repository(tmp_path / "paper.sqlite3").transition(
        pid, {"status": ("open",)},
        {"status": "confirmed", "submission_status": "submitting", "submit_lease_until": lease_until},
        {"at": "t", "type": "submission_intent"})
    proposal = get(f"/api/paper/proposals/{pid}").json()
    broker._store({"client_order_id": proposal["clientOrderId"], "symbol": "NVDA", "side": "buy",
                   "type": "market", "time_in_force": "day", "notional": "100.00"})
    broker.calls.clear()

    busy = post(f"/api/paper/proposals/{pid}/reconcile")
    assert busy.status_code == 409 and busy.json()["code"] == "SUBMISSION_IN_PROGRESS"
    again = post(f"/api/paper/proposals/{pid}/confirm", CONFIRM)
    assert again.status_code == 409 and again.json()["code"] == "SUBMISSION_IN_PROGRESS"
    assert broker.calls == []

    clock.advance(121)
    assert get(f"/api/paper/proposals/{pid}").json()["submissionStatus"] == "submitting"
    assert broker.calls == []  # reading never recovers an interrupted submission

    recovered = post(f"/api/paper/proposals/{pid}/reconcile")
    assert recovered.status_code == 200
    assert recovered.json()["submissionStatus"] == "submitted"
    assert broker.submits == [] and "submit_order" not in broker.calls


def test_pending_cancel_is_not_final_until_the_order_is_read_again(installed, broker):
    pid = create()
    order_id = post(f"/api/paper/proposals/{pid}/confirm", CONFIRM).json()["brokerOrderId"]
    canceled = post(f"/api/paper/orders/{order_id}/cancel", {"confirmation": "CANCEL_PAPER_ORDER"}).json()
    assert canceled["order"]["status"] == "pending_cancel"
    pending = get(f"/api/paper/proposals/{pid}").json()
    assert pending["brokerStatus"] == "pending_cancel"
    assert pending["reservation"]["state"] == "acknowledged"

    broker.finish_cancel(order_id)
    assert get(f"/api/paper/proposals/{pid}").json()["brokerStatus"] == "pending_cancel"
    assert get(f"/api/paper/orders/{order_id}").json()["status"] == "canceled"
    final = get(f"/api/paper/proposals/{pid}").json()
    assert final["brokerStatus"] == "canceled"
    assert final["reservation"]["state"] == "released"

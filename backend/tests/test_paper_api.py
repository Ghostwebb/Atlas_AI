"""HTTP contract for /api/paper. No test reaches Alpaca."""

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.paper import routes
from app.paper.client import AlpacaPaperClient
from app.paper.repository import Repository
from app.paper.service import PaperTradingService
from tests.paper_fakes import PAPER_KEY, PAPER_SECRET, Clock, FakeBroker, make_service, settings

client = TestClient(main.app)
ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture
def broker():
    return FakeBroker()


@pytest.fixture
def installed(monkeypatch, tmp_path, broker):
    service = make_service(tmp_path, broker)
    monkeypatch.setitem(routes._state, "service", service)
    return service


def post(path, body=None, headers=ORIGIN):
    return client.post(path, json=body, headers=headers)


def _proposal(body=None):
    return post("/api/paper/proposals", body or {"symbol": "NVDA", "side": "buy", "notional": "100.00"})


# --- 1. disabled by default ------------------------------------------------------

def test_default_server_is_disabled_and_makes_no_calls():
    assert main.paper_settings.enabled is False and main.paper_client is None
    status = client.get("/api/paper/status").json()
    assert status["enabled"] is False and status["environment"] == "paper"
    response = _proposal()
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "PAPER_DISABLED" and set(body) >= {"error", "message", "code", "correlationId"}
    assert response.headers["X-Correlation-Id"] == body["correlationId"]


# --- contract ----------------------------------------------------------------------

def test_full_flow_over_http(installed, broker):
    created = _proposal({"symbol": "nvda", "side": "buy", "notional": "100.00", "analysisReference": "NVDA@2026-09-30"})
    assert created.status_code == 201
    proposal = created.json()
    assert proposal["notional"] == "100.00" and proposal["symbol"] == "NVDA"
    assert proposal["status"] == "open" and proposal["environment"] == "paper"
    assert broker.submits == []

    fetched = client.get(f"/api/paper/proposals/{proposal['id']}").json()
    assert fetched == proposal

    confirmed = post(f"/api/paper/proposals/{proposal['id']}/confirm", {"confirmation": "CONFIRM_PAPER_ORDER"})
    assert confirmed.status_code == 200
    order_id = confirmed.json()["brokerOrderId"]
    assert confirmed.json()["submissionStatus"] == "submitted"

    assert client.get(f"/api/paper/orders/{order_id}").json()["proposalId"] == proposal["id"]
    assert client.get("/api/paper/orders?status=all&limit=5").status_code == 200
    canceled = post(f"/api/paper/orders/{order_id}/cancel", {"confirmation": "CANCEL_PAPER_ORDER"})
    assert canceled.status_code == 200
    assert canceled.json()["cancelRequested"] is True
    assert canceled.json()["order"]["status"] == "pending_cancel"


def test_account_positions_and_clock(installed, broker):
    broker.add_position("NVDA", "2.5")
    account = client.get("/api/paper/account").json()
    assert account["environment"] == "paper" and account["buyingPower"] == "200000"
    positions = client.get("/api/paper/positions").json()
    assert positions[0]["qty"] == "2.5" and positions[0]["environment"] == "paper"
    assert client.get("/api/paper/clock").json()["isOpen"] is True
    assert PAPER_SECRET not in str(account) and PAPER_KEY not in str(account)


# --- 4. invalid amounts and fields ---------------------------------------------

@pytest.mark.parametrize("body", [
    {"symbol": "NVDA", "side": "buy", "notional": "0"},
    {"symbol": "NVDA", "side": "buy", "notional": "0.50"},          # below $1
    {"symbol": "NVDA", "side": "buy", "notional": "-5"},
    {"symbol": "NVDA", "side": "buy", "notional": "NaN"},
    {"symbol": "NVDA", "side": "buy", "notional": "Infinity"},
    {"symbol": "NVDA", "side": "buy", "notional": "1e3"},
    {"symbol": "NVDA", "side": "buy", "notional": "10.001"},        # more than cents: not rounded
    {"symbol": "NVDA", "side": "buy", "notional": 100.0},           # JSON number, not a string
    {"symbol": "NVDA", "side": "buy", "qty": "1"},                  # buy needs notional
    {"symbol": "NVDA", "side": "buy", "notional": "10", "qty": "1"},
    {"symbol": "NVDA", "side": "sell", "notional": "10"},           # sell needs qty
    {"symbol": "NVDA", "side": "sell", "qty": "0"},
    {"symbol": "NVDA", "side": "sell", "qty": "1.0000000001"},      # > 9 decimals
    {"symbol": "NVDA", "side": "short", "qty": "1"},
    {"symbol": "NVDA", "side": "buy", "notional": "10", "type": "limit"},
    {"symbol": "NVDA", "side": "buy", "notional": "10", "extended_hours": True},
    {"symbol": "NVDA", "side": "buy", "notional": "10", "baseUrl": "https://api.alpaca.markets"},
    {"symbol": "1BAD", "side": "buy", "notional": "10"},
])
def test_invalid_requests_are_rejected_without_calls(installed, broker, body):
    response = _proposal(body)
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert broker.calls == []


@pytest.mark.parametrize("body", [{}, {"confirmation": "yes"}, {"confirmation": "CONFIRM_PAPER_ORDER", "qty": "5"}])
def test_confirmation_requires_exact_value_and_cannot_change_order(installed, broker, body):
    proposal = _proposal().json()
    response = post(f"/api/paper/proposals/{proposal['id']}/confirm", body)
    assert response.status_code == 400 and response.json()["code"] == "INVALID_CONFIRMATION"
    assert broker.submits == []


def test_unknown_proposal_is_404(installed):
    response = post("/api/paper/proposals/" + "0" * 32 + "/confirm", {"confirmation": "CONFIRM_PAPER_ORDER"})
    assert response.status_code == 404 and response.json()["code"] == "PROPOSAL_NOT_FOUND"


def test_state_conflicts_are_409(installed, broker):
    proposal = _proposal().json()
    broker.submit_mode = "unknown_missing"
    response = post(f"/api/paper/proposals/{proposal['id']}/confirm", {"confirmation": "CONFIRM_PAPER_ORDER"})
    assert response.status_code == 409 and response.json()["code"] == "SUBMISSION_UNCERTAIN"
    assert response.json()["proposalId"] == proposal["id"]


# --- Origin check (CORS is not authentication) -----------------------------------

@pytest.mark.parametrize("headers", [{}, {"Origin": "https://evil.example"}])
def test_mutations_require_allowed_origin(installed, broker, headers):
    response = post("/api/paper/proposals", {"symbol": "NVDA", "side": "buy", "notional": "10"}, headers=headers)
    assert response.status_code == 403 and response.json()["code"] == "ORIGIN_NOT_ALLOWED"
    assert broker.calls == []


def test_explicit_local_flag_allows_requests_without_origin(monkeypatch, tmp_path, broker):
    service = make_service(tmp_path, broker, allow_requests_without_origin=True)
    monkeypatch.setitem(routes._state, "service", service)
    assert post("/api/paper/proposals", {"symbol": "NVDA", "side": "buy", "notional": "10"}, headers={}).status_code == 201


# --- 24. broker errors are sanitized ----------------------------------------------

def test_broker_errors_are_sanitized(monkeypatch, tmp_path, caplog):
    def handler(request):
        return httpx.Response(500, text=f"internal error trace key={PAPER_KEY}")

    real = AlpacaPaperClient(settings(), transport=httpx.MockTransport(handler))
    service = PaperTradingService(settings(), real, Repository(tmp_path / "p.sqlite3"), now=Clock())
    monkeypatch.setitem(routes._state, "service", service)
    response = client.get("/api/paper/account")
    assert response.status_code == 503 and response.json()["code"] == "BROKER_UNAVAILABLE"
    assert "trace" not in response.text and PAPER_KEY not in response.text
    assert PAPER_SECRET not in caplog.text and PAPER_KEY not in caplog.text


def test_live_url_cannot_be_injected_through_paths(installed, broker):
    response = client.get("/api/paper/orders/..%2F..%2Fv2%2Faccount")
    assert response.status_code == 404
    assert "get_order" not in broker.calls


# --- 25. analysis and narrative never touch the broker ---------------------------

def test_analysis_and_report_make_no_broker_calls(installed, broker):
    assert client.post("/api/analyze", json={"symbol": "NVDA"}).status_code == 200
    assert client.post("/api/report", json={"symbol": "NVDA"}).status_code == 200
    assert broker.calls == [] and broker.submits == []

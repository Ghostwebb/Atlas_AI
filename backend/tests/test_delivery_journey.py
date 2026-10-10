"""Delivery journey over the INTEGRATED app (PR #3 + #7 + #8 on main).

Simulated transports only: LM Studio is mocked, Alpaca is the test FakeBroker. Nothing here reaches a
real model, a real broker or the network.
"""

import dataclasses

import httpx

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.committee.integrity import validate_committee
from app.data.demo_provider import DemoDataProvider
from app.paper import routes
from tests.narration_helpers import client_with_handler, enabled_settings
from tests.paper_fakes import FakeBroker, make_service

client = TestClient(main.app)
ORIGIN = {"Origin": "http://localhost:3000"}
SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]


@pytest.fixture
def broker(monkeypatch, tmp_path):
    fake = FakeBroker()
    monkeypatch.setitem(routes._state, "service", make_service(tmp_path, fake))
    return fake


def test_health_and_symbol_errors_on_every_symbol_route():
    assert client.get("/health").json() == {"status": "ok", "service": "atlas-ai-backend"}
    for path in ("/api/analyze", "/api/agents/analyze", "/api/committee/analyze", "/api/report"):
        assert client.post(path, json={"symbol": "ZZZZ"}).status_code == 404, path
        assert client.post(path, json={"symbol": "N1"}).status_code == 400, path
        assert client.post(path, json={"symbol": "nvda "}).status_code == 200, path


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_analysis_agents_committee_share_one_synthetic_snapshot(symbol):
    analysis = client.post("/api/analyze", json={"symbol": symbol}).json()
    agents = client.post("/api/agents/analyze", json={"symbol": symbol}).json()
    committee = client.post("/api/committee/analyze", json={"symbol": symbol}).json()
    assert analysis["isSimulated"] is True and analysis["dataSource"] == "demo_dataset"
    snap = agents["snapshot"]
    assert (snap["symbol"], snap["dataSource"], snap["provenance"], snap["isSimulated"], snap["lastDate"]) == \
        (symbol, "demo_dataset", "synthetic", True, analysis["dataAsOf"])
    assert committee["agents"] == agents
    validate_committee(committee)


def test_report_with_model_disabled_is_deterministic():
    body = client.post("/api/report", json={"symbol": "NVDA"}).json()
    assert body["narrative"]["status"] == "disabled" and body["narrative"]["generationMode"] == "deterministic"
    assert body["analysis"] == client.post("/api/analyze", json={"symbol": "NVDA"}).json()


def test_model_failure_falls_back_without_breaking_the_analysis(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("LM Studio down", request=request)
    monkeypatch.setattr(main, "narration_settings", enabled_settings())
    monkeypatch.setattr(main, "narration_client", client_with_handler(refuse))
    body = client.post("/api/report", json={"symbol": "NVDA"}).json()
    assert body["narrative"]["status"] == "fallback" and body["narrative"]["reason"]["code"] == "MODEL_UNAVAILABLE"
    assert body["analysis"]["recommendation"] in ("BUY", "HOLD", "SELL")
    # Agents and committee do not depend on the model at all.
    assert client.post("/api/committee/analyze", json={"symbol": "NVDA"}).status_code == 200


def test_paper_disabled_and_not_configured(monkeypatch, tmp_path):
    response = client.post("/api/paper/proposals", json={"symbol": "NVDA", "side": "buy", "notional": "100.00"},
                           headers=ORIGIN)
    assert response.status_code == 503 and response.json()["code"] == "PAPER_DISABLED"
    no_keys = make_service(tmp_path, FakeBroker(), api_key="", secret_key="")
    monkeypatch.setitem(routes._state, "service", no_keys)
    response = client.post("/api/paper/proposals", json={"symbol": "NVDA", "side": "buy", "notional": "100.00"},
                           headers=ORIGIN)
    assert response.status_code == 503 and response.json()["code"] == "PAPER_NOT_CONFIGURED"


def test_prepare_confirm_read_cancel_with_fake_broker(broker):
    created = client.post("/api/paper/proposals", json={"symbol": "NVDA", "side": "buy", "notional": "100.00"},
                          headers=ORIGIN)
    assert created.status_code == 201 and broker.submits == []          # preparing never submits
    pid = created.json()["id"]
    assert client.post(f"/api/paper/proposals/{pid}/confirm", json={}, headers=ORIGIN).status_code == 400
    confirmed = client.post(f"/api/paper/proposals/{pid}/confirm", json={"confirmation": "CONFIRM_PAPER_ORDER"},
                            headers=ORIGIN).json()
    assert confirmed["submissionStatus"] == "submitted" and len(broker.submits) == 1
    order_id = confirmed["brokerOrderId"]
    assert client.get(f"/api/paper/orders/{order_id}").json()["proposalId"] == pid
    canceled = client.post(f"/api/paper/orders/{order_id}/cancel", json={"confirmation": "CANCEL_PAPER_ORDER"},
                           headers=ORIGIN).json()
    assert canceled["cancelRequested"] is True and canceled["order"]["status"] == "pending_cancel"
    assert len(broker.submits) == 1


def test_uncertain_submission_is_reconciled_without_resending(broker):
    pid = client.post("/api/paper/proposals", json={"symbol": "NVDA", "side": "buy", "notional": "100.00"},
                      headers=ORIGIN).json()["id"]
    broker.submit_mode = "unknown_missing"
    first = client.post(f"/api/paper/proposals/{pid}/confirm", json={"confirmation": "CONFIRM_PAPER_ORDER"},
                        headers=ORIGIN)
    assert first.status_code == 409 and first.json()["code"] == "SUBMISSION_UNCERTAIN"
    again = client.post(f"/api/paper/proposals/{pid}/confirm", json={"confirmation": "CONFIRM_PAPER_ORDER"},
                        headers=ORIGIN)
    assert again.status_code == 409 and len(broker.submits) == 1       # never resent
    broker._store(dict(broker.submits[0]))                              # the order appears at the broker
    reconciled = client.post(f"/api/paper/proposals/{pid}/reconcile", headers=ORIGIN).json()
    assert reconciled["submissionStatus"] == "submitted" and len(broker.submits) == 1


def test_invalid_prices_produce_no_favorable_conclusion(monkeypatch):
    class Corrupt(DemoDataProvider):
        def get_snapshot(self, symbol):
            snap = super().get_snapshot(symbol)
            bars = list(snap.bars)
            for index in (-1, -15, -40):
                bars[index] = dataclasses.replace(bars[index], close=0.0)
            return dataclasses.replace(snap, bars=bars)

    monkeypatch.setattr(main, "market_data_provider", Corrupt())
    body = client.post("/api/committee/analyze", json={"symbol": "NVDA"}).json()
    vector = next(e for e in body["agents"]["evaluations"] if e["strategyId"] == "vector")
    assert vector["status"] == "insufficient" and vector["evidence"]["favorable"] == []
    assert body["committee"]["conclusion"]["state"] != "aligned_favorable"
    validate_committee(body)


def test_analysis_agents_committee_and_report_never_touch_paper(broker):
    for path in ("/api/analyze", "/api/agents/analyze", "/api/committee/analyze", "/api/report"):
        for symbol in SYMBOLS:
            assert client.post(path, json={"symbol": symbol}).status_code == 200
    assert broker.calls == [] and broker.submits == []

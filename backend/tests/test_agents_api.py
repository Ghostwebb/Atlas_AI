"""POST /api/agents/analyze: contract, provenance, references, isolation and non-regression."""

import copy

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.agents.engine import EvidenceIntegrityError, validate_references
from app.agents.service import analyze_agents
from app.data.demo_provider import DemoDataProvider
from app.narration.client import LMStudioClient

client = TestClient(main.app)
SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]


def post(body):
    return client.post("/api/agents/analyze", json=body)


@pytest.fixture
def no_outbound(monkeypatch):
    """Any model or network call fails the test."""
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("outbound call during agent evaluation")

    monkeypatch.setattr(LMStudioClient, "complete", boom)
    # Real network transports (the TestClient uses its own in-process transport).
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", boom)
    return calls


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_every_demo_symbol_is_evaluated_by_the_four_strategies(symbol, no_outbound):
    response = post({"symbol": symbol})
    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == "agents.v1.1"
    assert [e["strategyId"] for e in body["evaluations"]] == ["argo", "nova", "vector", "aegis"]
    assert body["snapshot"]["provenance"] == "synthetic" and body["snapshot"]["isSimulated"] is True
    assert "synthetic" in body["notice"] and "not orders" in body["notice"]
    for e in body["evaluations"]:
        assert e["status"] in ("complete", "partial", "insufficient")
        assert e["stance"] in ("favorable", "neutral", "unfavorable", "insufficient_data")
        assert e["version"] == "1.0.1" and 0 <= e["coverage"] <= 1
    validate_references(body)
    assert no_outbound == []


def test_demo_dataset_status_per_profile():
    # With the current demo dataset all four strategies have every criterion's input.
    for symbol in SYMBOLS:
        body = post({"symbol": symbol}).json()
        assert {e["strategyId"]: e["status"] for e in body["evaluations"]} == \
            {"argo": "complete", "nova": "complete", "vector": "complete", "aegis": "complete"}


def test_symbol_is_normalized_and_errors_follow_the_existing_contract():
    assert post({"symbol": "  nvda "}).json()["snapshot"]["symbol"] == "NVDA"
    for body, status in [({"symbol": "NV1DA"}, 400), ({"symbol": ""}, 400), ({}, 400), ({"symbol": 5}, 400),
                         ({"symbol": "ZZZZ"}, 404)]:
        response = post(body)
        assert response.status_code == status
        assert set(response.json()) == {"error", "message"}


@pytest.mark.parametrize("extra", [{"metrics": {"pe_ratio": 5}}, {"weights": {"argo": 1}},
                                   {"recommendation": "BUY"}, {"url": "http://example.com"}, {"strategy": "argo"}])
def test_client_supplied_fields_are_rejected(extra):
    assert post({"symbol": "NVDA", **extra}).status_code == 400


def test_deterministic_output():
    a = post({"symbol": "META"}).json()
    b = post({"symbol": "META"}).json()
    assert a == b


def test_disagreement_on_demo_snapshot_is_data_driven():
    body = post({"symbol": "META"}).json()
    stances = {e["strategyId"]: e["stance"] for e in body["evaluations"]}
    assert stances["nova"] == "favorable" and stances["vector"] == "unfavorable"
    nova = next(e for e in body["evaluations"] if e["strategyId"] == "nova")
    assert {i["criterion"] for i in nova["evidence"]["favorable"]} == {"revenue_growth", "earnings_growth",
                                                                     "margin_sustainability"}


def test_evidence_values_match_the_snapshot():
    body = post({"symbol": "TSLA"}).json()
    metrics = body["snapshot"]["metrics"]
    for e in body["evaluations"]:
        for d in ("favorable", "unfavorable", "neutral"):
            for item in e["evidence"][d]:
                for ref in item["references"]:
                    key = ref["path"].removeprefix("snapshot.metrics.")
                    assert metrics[key]["value"] == ref["value"] is not None


def test_broken_reference_is_detected():
    body = post({"symbol": "NVDA"}).json()
    broken = copy.deepcopy(body)
    broken["evaluations"][0]["evidence"]["unfavorable"][0]["references"][0]["path"] = "snapshot.metrics.nope"
    with pytest.raises(EvidenceIntegrityError):
        validate_references(broken)
    tampered = copy.deepcopy(body)
    tampered["evaluations"][0]["evidence"]["unfavorable"][0]["references"][0]["value"] = 1.0
    with pytest.raises(EvidenceIntegrityError):
        validate_references(tampered)
    outside = copy.deepcopy(body)
    outside["evaluations"][0]["evidence"]["unfavorable"][0]["references"][0]["path"] = "analysis.internal"
    with pytest.raises(EvidenceIntegrityError):
        validate_references(outside)


def test_integrity_error_returns_500(monkeypatch):
    def broken(document):
        raise EvidenceIntegrityError("x")
    monkeypatch.setattr("app.agents.service.validate_references", broken)
    response = post({"symbol": "NVDA"})
    assert response.status_code == 500 and response.json()["error"] == "Agent evaluation integrity error"


def test_one_provider_query_per_request():
    calls = []

    class Counting(DemoDataProvider):
        def get_snapshot(self, symbol):
            calls.append(symbol)
            return super().get_snapshot(symbol)

    assert analyze_agents("NVDA", Counting()) is not None
    assert calls == ["NVDA"]


def _keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _keys(value)


def test_no_orders_proposals_or_committee_decision_in_the_response():
    response = post({"symbol": "NVDA"})
    keys = {k.lower() for k in _keys(response.json())}
    for word in ("order", "proposal", "allocation", "winner", "decision", "action", "recommendation", "quantity"):
        assert not any(word in k for k in keys), word
    text = response.text
    assert "alpaca" not in text.lower() and '"BUY"' not in text and '"SELL"' not in text
    # Integrated app: /api/paper exists, but this route must never reach the paper service or broker.
    _assert_no_paper_activity(lambda: post({"symbol": "NVDA"}))


def test_existing_analyze_and_report_are_unchanged(no_outbound):
    analyze_before = client.post("/api/analyze", json={"symbol": "NVDA"}).json()
    report_before = client.post("/api/report", json={"symbol": "NVDA"}).json()
    post({"symbol": "NVDA"})
    assert client.post("/api/analyze", json={"symbol": "NVDA"}).json() == analyze_before
    assert client.post("/api/report", json={"symbol": "NVDA"}).json() == report_before
    assert analyze_before["recommendation"] == "BUY" and "agents" not in analyze_before


# Results on the healthy demo dataset (unchanged by the input-validity fix of 632f951).
EXPECTED = {
    "AAPL": [("neutral", -0.2), ("neutral", 0.3), ("unfavorable", -0.85), ("neutral", 0.0)],
    "MSFT": [("neutral", -0.2), ("neutral", 0.6), ("neutral", 0.0), ("favorable", 0.5)],
    "NVDA": [("neutral", -0.2), ("favorable", 1.0), ("favorable", 0.85), ("neutral", -0.2)],
    "TSLA": [("unfavorable", -0.7), ("unfavorable", -0.7), ("unfavorable", -0.85), ("unfavorable", -0.85)],
    "AMZN": [("unfavorable", -0.5), ("neutral", 0.3), ("unfavorable", -0.85), ("neutral", -0.15)],
    "GOOGL": [("neutral", 0.3), ("neutral", 0.3), ("neutral", 0.0), ("favorable", 0.85)],
    "META": [("neutral", -0.2), ("favorable", 1.0), ("unfavorable", -0.85), ("neutral", 0.0)],
}


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_healthy_demo_results_are_unchanged(symbol):
    body = post({"symbol": symbol}).json()
    assert [(e["stance"], e["score"]) for e in body["evaluations"]] == EXPECTED[symbol]
    assert all(m["status"] == "ok" and m["issue"] is None for m in body["snapshot"]["metrics"].values())
    assert all(e["risksNotEvaluated"] == [] and e["notEvaluated"] == [] for e in body["evaluations"])


def _assert_no_paper_activity(action):
    """Every paper-service entry point and the paper client fail the test if touched."""
    import pytest as _pytest
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("paper trading touched")

    with _pytest.MonkeyPatch.context() as mp:
        service = main.paper_service if hasattr(main, "paper_service") else None
        if service is not None:
            for name in ("create_proposal", "confirm", "reconcile", "cancel_order", "get_order", "list_orders",
                         "get_proposal", "status", "account", "positions", "clock"):
                mp.setattr(service, name, boom)
        assert action().status_code == 200
    assert calls == []

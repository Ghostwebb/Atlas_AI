"""POST /api/committee/analyze: contract, integrity, isolation and non-regression."""

import copy
import json
import math

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.committee.integrity import CommitteeIntegrityError, validate_committee
from app.committee.service import analyze_committee
from app.data.demo_provider import DemoDataProvider
from app.narration.client import LMStudioClient
from tests.agents_factories import built
from tests.committee_factories import FAVORABLE, response

client = TestClient(main.app)
SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]
# Real committee states on the synthetic demo dataset (policy 1.0.0, strategies 1.0.1).
EXPECTED = {"AAPL": "neutral", "MSFT": "neutral", "NVDA": "caution", "TSLA": "aligned_unfavorable",
            "AMZN": "aligned_unfavorable", "GOOGL": "neutral", "META": "conflicted"}


def post(body):
    return client.post("/api/committee/analyze", json=body)


@pytest.fixture
def no_outbound(monkeypatch):
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("outbound call")

    monkeypatch.setattr(LMStudioClient, "complete", boom)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", boom)
    return calls


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_demo_symbols(symbol, no_outbound):
    r = post({"symbol": symbol})
    assert r.status_code == 200
    body = r.json()
    assert body["schemaVersion"] == "committee.v1" and body["policyVersion"] == "1.0.0"
    assert body["committee"]["conclusion"]["state"] == EXPECTED[symbol]
    assert body["agents"]["snapshot"]["provenance"] == "synthetic" and "does not invest" in body["notice"]
    validate_committee(body)
    assert no_outbound == []


def test_agents_section_is_identical_to_the_agents_endpoint():
    for symbol in SYMBOLS:
        assert post({"symbol": symbol}).json()["agents"] == \
            client.post("/api/agents/analyze", json={"symbol": symbol}).json()


def test_demo_findings_are_data_driven():
    meta = post({"symbol": "META"}).json()["committee"]
    assert {f["kind"] for f in meta["conflicts"]} == {"growth_vs_momentum", "valuation_vs_growth"}
    nvda = post({"symbol": "NVDA"}).json()["committee"]
    assert {r["id"]: r["met"] for r in nvda["conclusion"]["requirements"]} == {
        "R1": True, "R2": True, "R3": True, "R4": True, "R5": True, "R6": False, "R7": False, "R8": True,
        "R9": False}
    assert "momentum_with_high_risk" in {f["kind"] for f in nvda["conflicts"]}


def test_normalization_errors_and_extra_fields():
    assert post({"symbol": " nvda "}).json()["agents"]["snapshot"]["symbol"] == "NVDA"
    for body, status in [({"symbol": "N1"}, 400), ({}, 400), ({"symbol": "ZZZZ"}, 404)]:
        r = post(body)
        assert r.status_code == status and set(r.json()) == {"error", "message"}
    for extra in ({"evaluations": []}, {"votes": {"argo": 1}}, {"weights": {}}, {"metrics": {}},
                  {"url": "http://x"}, {"recommendation": "BUY"}, {"policy": "1.0.0"}):
        assert post({"symbol": "NVDA", **extra}).status_code == 400


def test_one_provider_query():
    calls = []

    class Counting(DemoDataProvider):
        def get_snapshot(self, symbol):
            calls.append(symbol)
            return super().get_snapshot(symbol)

    assert analyze_committee("META", Counting()) is not None and calls == ["META"]


def test_deterministic():
    assert post({"symbol": "NVDA"}).json() == post({"symbol": "NVDA"}).json()


def test_integrity_failure_is_an_error_not_a_neutral_reading(monkeypatch):
    def broken(document):
        raise CommitteeIntegrityError("x")
    monkeypatch.setattr("app.committee.service.validate_committee", broken)
    r = post({"symbol": "NVDA"})
    assert r.status_code == 500 and r.json()["error"] == "Committee integrity error"


def _first_ref(body, key):
    return next(f for f in body["committee"][key] if f["references"])["references"][0]


@pytest.mark.parametrize("tamper", [
    lambda b: _first_ref(b, "arguments").update(path="agents.snapshot.metrics.nope"),
    lambda b: _first_ref(b, "arguments").update(path="agents.evaluations.0"),
    lambda b: _first_ref(b, "arguments").update(value=123.0),
    lambda b: _first_ref(b, "arguments").update(unit="usd"),
    lambda b: _first_ref(b, "arguments").update(direction="unfavorable"),
    lambda b: _first_ref(b, "arguments").update(strategyId="vector" if _first_ref(b, "arguments")["strategyId"]
                                                != "vector" else "nova"),
    lambda b: _first_ref(b, "arguments").update(id="nova.invented"),
    lambda b: _first_ref(b, "arguments").update(path="agents.snapshot.metrics.price_last", value=100.0, unit="usd"),
    lambda b: b["committee"]["participants"][0].update(stance="favorable", status="complete"),
    lambda b: b["agents"]["evaluations"][1]["evidence"]["favorable"][0]["references"][0].update(value=9.0),
])
def test_tampered_references_are_rejected(tamper):
    body = response(**FAVORABLE)
    validate_committee(body)
    broken = copy.deepcopy(body)
    tamper(broken)
    with pytest.raises(CommitteeIntegrityError):
        validate_committee(broken)


def test_null_metric_cannot_be_cited_as_evidence():
    body = response(**FAVORABLE)
    ref = _first_ref(body, "arguments")
    metric = ref["path"].split(".")[-1]
    body["agents"]["snapshot"]["metrics"][metric]["value"] = None
    ref["value"] = None
    with pytest.raises(CommitteeIntegrityError):
        validate_committee(body)


def test_invalid_and_non_finite_inputs_flow_through_without_nan():
    prices = [100.0] * 70
    for index in (30, 31, 60):
        prices[index] = 0.0
    prices[5] = float("nan")
    from app.agents.service import evaluate_snapshot
    from app.committee.service import committee_from_agents
    out = committee_from_agents(evaluate_snapshot(built(prices)).model_dump(mode="json"))
    text = out.model_dump_json()
    assert "NaN" not in text and "Infinity" not in text
    doc = json.loads(text)
    assert doc["committee"]["conclusion"]["state"] == "insufficient_data"
    assert any(o["kind"] == "invalid_input_blocking" for o in doc["committee"]["observations"])

    def walk(node):
        if isinstance(node, dict):
            [walk(v) for v in node.values()]
        elif isinstance(node, list):
            [walk(v) for v in node]
        elif isinstance(node, float):
            assert math.isfinite(node)
    walk(doc)


def test_no_orders_proposals_or_trading_routes():
    body = post({"symbol": "NVDA"}).json()
    keys = set()

    def collect(node):
        if isinstance(node, dict):
            for k, v in node.items():
                keys.add(k.lower())
                collect(v)
        elif isinstance(node, list):
            [collect(v) for v in node]
    collect(body)
    for word in ("order", "proposal", "allocation", "winner", "quantity", "confidence"):
        assert not any(word in k for k in keys), word
    # Integrated app: /api/paper exists, but this route must never reach the paper service or broker.
    _assert_no_paper_activity(lambda: post({"symbol": "NVDA"}))
    assert '"BUY"' not in json.dumps(body["committee"]) and '"SELL"' not in json.dumps(body["committee"])


def test_previous_contracts_unchanged(no_outbound):
    before = {path: client.post(path, json={"symbol": "NVDA"}).json()
              for path in ("/api/analyze", "/api/report", "/api/agents/analyze")}
    post({"symbol": "NVDA"})
    for path, body in before.items():
        assert client.post(path, json={"symbol": "NVDA"}).json() == body
    assert before["/api/agents/analyze"]["schemaVersion"] == "agents.v1.1"
    assert before["/api/analyze"]["recommendation"] == "BUY"   # engine recommendation untouched


def test_unsupported_agents_schema_is_rejected():
    from app.committee.service import committee_from_agents
    body = response(**FAVORABLE)["agents"]
    body["schemaVersion"] = "agents.v9"
    with pytest.raises(CommitteeIntegrityError):
        committee_from_agents(body)


def test_abstention_references_are_validated():
    from tests.committee_factories import response as build
    body = build(**{**FAVORABLE, "pe_ratio": None})
    assert body["committee"]["abstentions"][0]["id"] == "abstention:argo"
    broken = copy.deepcopy(body)
    broken["committee"]["abstentions"][0]["references"][0]["path"] = "agents.snapshot.metrics.nope"
    with pytest.raises(CommitteeIntegrityError):
        validate_committee(broken)


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

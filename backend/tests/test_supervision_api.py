"""HTTP contract for the Phase 3 supervision block and the seven demo symbols."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.analysis.service import analyze_symbol
from app.data.demo_provider import DemoDataProvider
from app.supervision.models import SupervisionIntegrityError
from app.supervision.service import resolve_reference

client = TestClient(main.app)

DEMO_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]
ALLOWED_STATUSES = {"consistent", "caution", "insufficient_data"}
PHASE2_KEYS = {
    "symbol", "companyName", "recommendation", "confidence", "summary",
    "explanation", "signals", "analysis", "isSimulated", "dataSource",
    "dataAsOf", "dataIssues",
}


def _analyze(symbol):
    return client.post("/api/analyze", json={"symbol": symbol})


def test_supervision_block_is_present_and_phase2_fields_are_preserved():
    body = _analyze("NVDA").json()
    assert PHASE2_KEYS.issubset(body)
    assert "supervision" in body
    assert body["isSimulated"] is True


def test_supervision_block_has_documented_shape():
    supervision = _analyze("NVDA").json()["supervision"]
    for key in ("schemaVersion", "policyVersion", "status", "engineRecommendation",
                "dataQuality", "findings", "supportingEvidence", "opposingEvidence",
                "neutralEvidence", "limitations", "report"):
        assert key in supervision, key
    assert supervision["status"] in ALLOWED_STATUSES
    assert supervision["schemaVersion"] == "1.1"
    assert supervision["policyVersion"] == "phase3-v2"
    assert set(supervision["report"]) == {
        "headline", "summary", "keyReasons", "counterpoints", "riskFactors", "dataGaps",
    }


def test_supervisor_does_not_alter_engine_recommendation_or_confidence():
    body = _analyze("NVDA").json()
    assert body["supervision"]["engineRecommendation"] == body["recommendation"]
    assert body["recommendation"] in {"BUY", "HOLD", "SELL"}
    assert 0.0 <= body["confidence"] <= 1.0


@pytest.mark.parametrize("symbol", DEMO_SYMBOLS)
def test_all_seven_demo_symbols_return_a_supervision_report(symbol):
    response = _analyze(symbol)
    assert response.status_code == 200, response.text
    supervision = response.json()["supervision"]
    assert supervision["status"] in ALLOWED_STATUSES
    assert supervision["dataQuality"]["provenance"] == "synthetic"


def test_http_responses_are_deterministic():
    assert _analyze("NVDA").json() == _analyze("NVDA").json()


def test_evidence_references_resolve_against_the_response():
    body = _analyze("NVDA").json()
    # Every reference must resolve in the final HTTP JSON, with no auxiliary objects.
    supervision = body["supervision"]
    refs = [ref for f in supervision["findings"] for ref in f["evidenceRefs"]]
    for key in ("supportingEvidence", "opposingEvidence", "neutralEvidence"):
        refs += [ref for item in supervision[key] for ref in item["refs"]]
    assert refs
    for ref in refs:
        assert resolve_reference(body, ref), ref


def test_integrity_error_returns_500_with_error_contract(monkeypatch):
    def broken(symbol, provider):
        raise SupervisionIntegrityError(["forced integrity failure"])

    monkeypatch.setattr(main, "analyze_symbol", broken)
    response = _analyze("NVDA")
    assert response.status_code == 500
    assert set(response.json()) == {"error", "message"}
    assert "forced" not in response.text  # internal detail is not leaked


def test_unknown_symbol_still_returns_404_with_supervision_layer_present():
    response = _analyze("ZZZZ")
    assert response.status_code == 404
    assert set(response.json()) == {"error", "message"}


def test_service_layer_produces_report_for_each_demo_symbol():
    provider = DemoDataProvider()
    for symbol in DEMO_SYMBOLS:
        result = analyze_symbol(symbol, provider)
        assert result is not None
        assert result.supervision is not None
        assert result.supervision.status.value in ALLOWED_STATUSES

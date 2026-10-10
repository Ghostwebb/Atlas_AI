"""HTTP contract of POST /api/report; /api/analyze stays independent of the model."""

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.analysis.service import analyze_symbol
from app.data.demo_provider import DemoDataProvider
from app.narration.evidence import build_packet
from app.supervision.models import SupervisionIntegrityError
from tests.narration_helpers import client_returning, client_with_handler, enabled_settings, valid_model_output

client = TestClient(main.app)
DEMO_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]


def _report(payload):
    return client.post("/api/report", json=payload)


def _enable(monkeypatch, narration_client):
    monkeypatch.setattr(main, "narration_settings", enabled_settings())
    monkeypatch.setattr(main, "narration_client", narration_client)


# --- 17. Contract ------------------------------------------------------------

def test_report_contract_when_disabled():
    response = _report({"symbol": "nvda"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"analysis", "narrative"}
    narrative = body["narrative"]
    assert set(narrative) == {
        "schemaVersion", "promptVersion", "supervisorPolicyVersion", "status", "generationMode",
        "model", "language", "reason", "facts", "report",
    }
    assert narrative["schemaVersion"] == "1.0"
    assert narrative["promptVersion"] == "narration-v1"
    assert narrative["language"] == "es"          # documented default
    assert narrative["status"] == "disabled"
    assert narrative["reason"]["code"] == "MODEL_DISABLED"
    assert set(narrative["report"]) == {
        "title", "overview", "supportingReasons", "counterpoints", "riskFactors", "dataGaps", "limitations",
    }
    assert body["analysis"]["symbol"] == "NVDA"


def test_generated_report_over_http(monkeypatch):
    analysis = analyze_symbol("TSLA", DemoDataProvider())
    output = valid_model_output(build_packet(analysis), "en")
    _enable(monkeypatch, client_returning(output))
    body = _report({"symbol": "TSLA", "language": "en"}).json()
    assert body["narrative"]["status"] == "generated"
    assert body["narrative"]["model"] == "test-model-id"
    assert body["narrative"]["report"] == output


def test_model_failure_still_returns_valid_analysis(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused")

    _enable(monkeypatch, client_with_handler(refuse))
    response = _report({"symbol": "TSLA", "language": "en"})
    assert response.status_code == 200
    narrative = response.json()["narrative"]
    assert narrative["status"] == "fallback"
    assert narrative["reason"]["code"] == "MODEL_UNAVAILABLE"
    assert "refused" not in response.text


# --- 13. Analysis preserved ---------------------------------------------------

@pytest.mark.parametrize("symbol", DEMO_SYMBOLS)
def test_analysis_in_report_equals_analyze_endpoint(symbol):
    analysis = client.post("/api/analyze", json={"symbol": symbol}).json()
    report = _report({"symbol": symbol, "language": "en"}).json()
    assert report["analysis"] == analysis
    facts = report["narrative"]["facts"]
    assert facts["recommendation"] == analysis["recommendation"]
    assert facts["confidence"] == analysis["confidence"]
    assert facts["supervisorStatus"] == analysis["supervision"]["status"]
    assert facts["provenance"] == "synthetic" and facts["isSimulated"] is True


# --- 15. Invalid and unknown input -------------------------------------------

@pytest.mark.parametrize(("payload", "status"), [
    ({"symbol": "1NVALID"}, 400),
    ({"symbol": ""}, 400),
    ({}, 400),
    ({"symbol": "NVDA", "language": "fr"}, 400),
    ({"symbol": "NVDA", "recommendation": "BUY"}, 400),     # clients cannot send results
    ({"symbol": "NVDA", "baseUrl": "http://evil.example"}, 400),
    ({"symbol": "ZZZZ"}, 404),
])
def test_invalid_requests_keep_error_contract(payload, status):
    response = _report(payload)
    assert response.status_code == status
    assert set(response.json()) == {"error", "message"}


def test_integrity_error_keeps_500_contract(monkeypatch):
    def broken(*args, **kwargs):
        raise SupervisionIntegrityError(["forced"])

    monkeypatch.setattr(main, "build_report_response", broken)
    response = _report({"symbol": "NVDA"})
    assert response.status_code == 500
    assert set(response.json()) == {"error", "message"}


# --- 16. /api/analyze does not depend on the model ---------------------------

def test_analyze_never_calls_the_model(monkeypatch):
    calls = []

    def record(request):
        calls.append(request)
        return httpx.Response(500)

    _enable(monkeypatch, client_with_handler(record))
    response = client.post("/api/analyze", json={"symbol": "NVDA"})
    assert response.status_code == 200
    assert "narrative" not in response.json()
    assert calls == []

"""Phase 1 tests: /health and /api/analyze contract."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ERROR_KEYS = {"error", "message"}


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "atlas-ai-backend"}


def test_analyze_valid_symbol_returns_full_phase2_contract():
    # Phase 2 replaced the fixed Phase 1 payload with a demo-dataset analysis.
    # The Phase 1 fields are still present; the values are now computed.
    response = client.post("/api/analyze", json={"symbol": "NVDA"})
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NVDA"
    assert body["companyName"] == "NVIDIA Corporation"
    assert body["recommendation"] in {"BUY", "HOLD", "SELL"}
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["isSimulated"] is True
    assert body["dataSource"] == "demo_dataset"
    assert set(body["signals"]) == {"momentum", "risk", "trend", "fundamental"}
    assert set(body["analysis"]) == {"momentum", "trend", "risk", "fundamental"}
    assert isinstance(body["explanation"], list) and body["explanation"]


def test_analyze_is_deterministic_over_http():
    first = client.post("/api/analyze", json={"symbol": "TSLA"}).json()
    second = client.post("/api/analyze", json={"symbol": "TSLA"}).json()
    assert first == second


def test_analyze_normalizes_lowercase_and_whitespace():
    response = client.post("/api/analyze", json={"symbol": "  nvda "})
    assert response.status_code == 200
    assert response.json()["symbol"] == "NVDA"


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "TSLA"])
def test_analyze_accepts_other_demo_symbols(symbol):
    response = client.post("/api/analyze", json={"symbol": symbol})
    assert response.status_code == 200
    assert response.json()["symbol"] == symbol


@pytest.mark.parametrize("symbol", ["", "   ", "123", "NV-DA", "TOOLONGSYMBOL"])
def test_analyze_rejects_malformed_symbol_with_400(symbol):
    response = client.post("/api/analyze", json={"symbol": symbol})
    assert response.status_code == 400
    assert set(response.json()) == ERROR_KEYS
    assert response.json()["error"] == "Invalid stock symbol"


def test_analyze_rejects_unknown_symbol_with_404():
    response = client.post("/api/analyze", json={"symbol": "ZZZZ"})
    assert response.status_code == 404
    assert set(response.json()) == ERROR_KEYS


@pytest.mark.parametrize(
    "payload",
    [{}, {"symbol": None}, {"symbol": 42}, {"symbol": "NVDA", "extra": 1}],
)
def test_analyze_rejects_invalid_body_with_error_contract(payload):
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 400
    assert set(response.json()) == ERROR_KEYS

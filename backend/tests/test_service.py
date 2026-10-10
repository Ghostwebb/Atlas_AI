"""End-to-end tests of the analysis service with controlled and demo data."""

from app.analysis.service import analyze_symbol
from app.data.demo_provider import DemoDataProvider
from app.data.provider import Fundamentals
from tests.factories import FixedProvider, alternating_closes, make_snapshot, rising_closes

ALLOWED_RECOMMENDATIONS = {"BUY", "HOLD", "SELL"}
DEMO_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]
STRONG = Fundamentals(revenue_growth=0.38, profit_margin=0.45, pe_ratio=24.0, earnings_growth=0.5)


def test_unknown_symbol_returns_none():
    assert analyze_symbol("ZZZZ", DemoDataProvider()) is None


def test_result_contract_is_complete_for_demo_symbol():
    result = analyze_symbol("NVDA", DemoDataProvider())
    body = result.model_dump()
    assert set(body) == {
        "symbol", "companyName", "recommendation", "confidence", "summary",
        "explanation", "signals", "analysis", "isSimulated", "dataSource",
        "dataAsOf", "dataIssues", "supervision",  # supervision is the additive Phase 3 field
    }
    assert set(body["signals"]) == {"momentum", "risk", "trend", "fundamental"}
    assert set(body["analysis"]) == {"momentum", "trend", "risk", "fundamental"}
    assert body["isSimulated"] is True
    assert body["dataSource"] == "demo_dataset"
    assert body["dataAsOf"] == "2026-09-30"
    assert 0.0 <= body["confidence"] <= 1.0


def test_analysis_is_deterministic_across_runs():
    first = analyze_symbol("MSFT", DemoDataProvider()).model_dump()
    second = analyze_symbol("MSFT", DemoDataProvider()).model_dump()
    assert first == second


def test_all_demo_symbols_produce_valid_recommendations():
    provider = DemoDataProvider()
    results = {symbol: analyze_symbol(symbol, provider) for symbol in DEMO_SYMBOLS}
    assert all(r is not None for r in results.values())
    assert {r.recommendation for r in results.values()} <= ALLOWED_RECOMMENDATIONS


def test_demo_dataset_yields_buy_hold_and_sell():
    # Demonstrates all three outcomes so the live demo can show each one.
    provider = DemoDataProvider()
    outcomes = {analyze_symbol(s, provider).recommendation for s in DEMO_SYMBOLS}
    assert outcomes == ALLOWED_RECOMMENDATIONS


def test_insufficient_history_reports_unavailable_without_inventing_values():
    # TEST 3 from the spec: 30 bars is too short for SMA50 and the trend.
    provider = FixedProvider(make_snapshot(rising_closes(30), fundamentals=STRONG, symbol="SHORT"))
    result = analyze_symbol("SHORT", provider)

    assert result.signals.trend == "unavailable"
    assert result.analysis.trend.score is None
    assert result.analysis.trend.shortMovingAverage is None
    assert result.signals.momentum != "unavailable"  # 2+ bars is enough for momentum
    assert any("excluded" in line.lower() or "Components without enough data" in line
               for line in result.explanation)


def test_missing_fundamentals_are_unavailable_not_negative():
    provider = FixedProvider(make_snapshot(rising_closes(60), fundamentals=None, symbol="NOFUND"))
    result = analyze_symbol("NOFUND", provider)
    assert result.signals.fundamental == "unavailable"
    assert result.analysis.fundamental.score is None
    assert result.analysis.fundamental.metricsUsed == 0


def test_high_volatility_snapshot_is_labelled_high_risk():
    provider = FixedProvider(make_snapshot(alternating_closes(60, swing=0.10), symbol="VOLATILE"))
    result = analyze_symbol("VOLATILE", provider)
    assert result.signals.risk == "high"
    assert result.analysis.risk.volatility > 0.6


def test_explanation_mentions_disclaimer_and_recommendation():
    result = analyze_symbol("AAPL", DemoDataProvider())
    text = " ".join(result.explanation)
    assert "not investment advice" in text
    assert result.recommendation in text

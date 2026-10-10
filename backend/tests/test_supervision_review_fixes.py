"""Regressions for the PR #1 review: trend narrative, public references,
evidence relative to the recommendation, and provenance wording."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.analysis.service import analyze_symbol
from app.data.demo_provider import DemoDataProvider
from app.data.provider import Fundamentals
from app.supervision.config import COMPONENT_ORDER
from app.supervision.evidence import build_evidence, describe
from app.supervision.models import (
    Direction,
    Finding,
    FindingCategory,
    Polarity,
    Severity,
    SupervisionIntegrityError,
    SupervisorStatus,
)
from app.supervision.quality import build_data_quality, build_limitations
from app.supervision.report import build_report
from app.supervision.rules import evaluate_rules, integrity_issues
from app.supervision.service import determine_status, resolve_reference, supervise
from tests.factories import FixedProvider, make_snapshot, rising_closes
from tests.supervision_factories import make_dataset, make_input

client = TestClient(main.app)
DEMO_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]
STRONG = Fundamentals(revenue_growth=0.38, profit_margin=0.45, pe_ratio=24.0, earnings_growth=0.5)

BULLISH_BELOW = [110.0] * 30 + [100.0] * 19 + [120.0]   # bullish, SMA20 101.0 < SMA50 106.4
BEARISH_ABOVE = [100.0] * 30 + [110.0] * 19 + [90.0]    # bearish, SMA20 109.0 > SMA50 103.6


def _all_refs(supervision: dict) -> list[str]:
    refs = [ref for f in supervision["findings"] for ref in f["evidenceRefs"]]
    for key in ("supportingEvidence", "opposingEvidence", "neutralEvidence"):
        refs += [ref for item in supervision[key] for ref in item["refs"]]
    return refs


def _http(monkeypatch, snapshot) -> dict:
    monkeypatch.setattr(main, "market_data_provider", FixedProvider(snapshot))
    response = client.post("/api/analyze", json={"symbol": snapshot.symbol})
    assert response.status_code == 200, response.text
    return response.json()


def _evidence_by_component(supervision: dict) -> dict[str, dict]:
    items = {}
    for key in ("supportingEvidence", "opposingEvidence", "neutralEvidence"):
        for item in supervision[key]:
            items[item["component"]] = item
    return items


def _report_for(inp):
    findings = evaluate_rules(inp)
    supporting, opposing, neutral = build_evidence(inp)
    status = determine_status(inp, findings)
    quality = build_data_quality(inp, status)
    return build_report(inp, status, findings, supporting, opposing, neutral, quality)


# --- 1. Trend narrative is based on the moving averages, not on the label -----

def test_bullish_trend_with_short_average_below_long_is_described_as_below(monkeypatch):
    body = _http(monkeypatch, make_snapshot(BULLISH_BELOW))
    assert body["analysis"]["trend"]["label"] == "bullish"
    assert body["analysis"]["trend"]["shortMovingAverage"] == 101.0
    assert body["analysis"]["trend"]["longMovingAverage"] == 106.4
    trend = _evidence_by_component(body["supervision"])["trend"]
    assert "The 20-day average (101.00) is below the 50-day average (106.40)." in trend["description"]
    assert "above the 50-day" not in trend["description"]
    assert "The price is 18.8% above the 20-day average." in trend["description"]


def test_bearish_trend_with_short_average_above_long_is_described_as_above(monkeypatch):
    body = _http(monkeypatch, make_snapshot(BEARISH_ABOVE))
    assert body["analysis"]["trend"]["label"] == "bearish"
    trend = _evidence_by_component(body["supervision"])["trend"]
    assert "The 20-day average (109.00) is above the 50-day average (103.60)." in trend["description"]
    assert "The price is 17.4% below the 20-day average." in trend["description"]


def test_equal_moving_averages_are_described_as_equal():
    inp = make_input(short_moving_average=100.0, long_moving_average=100.0, price_vs_short_ma=0.0)
    text, _ = describe(inp, "trend")
    assert "The 20-day average (100.00) is equal to the 50-day average (100.00)." in text
    assert "The price equals the 20-day average." in text


def test_missing_moving_averages_produce_no_claim_and_an_integrity_issue():
    inp = make_input(short_moving_average=None, long_moving_average=None)
    text, refs = describe(inp, "trend")
    assert text == "Trend is neutral."
    assert "analysis.trend.shortMovingAverage" not in refs
    assert "trend is available but its moving averages are missing" in integrity_issues(inp)


def test_missing_metrics_are_never_written_as_zero():
    momentum_text, _ = describe(make_input(momentum_change_percent=None), "momentum")
    risk_text, risk_refs = describe(make_input(volatility=None, max_drawdown=None), "risk")
    assert "0.0%" not in momentum_text and "%" not in momentum_text
    assert "%" not in risk_text
    assert "analysis.risk.volatility" not in risk_refs


@pytest.mark.parametrize("drawdown", [0.0, -0.0, -1e-12])
def test_zero_drawdown_never_prints_negative_zero(drawdown):
    text, _ = describe(make_input(max_drawdown=drawdown), "risk")
    assert "maximum drawdown 0%" in text
    assert "-0%" not in text


def test_trend_evidence_references_both_averages_and_they_resolve(monkeypatch):
    body = _http(monkeypatch, make_snapshot(BULLISH_BELOW))
    refs = _evidence_by_component(body["supervision"])["trend"]["refs"]
    for ref in ("analysis.trend.shortMovingAverage", "analysis.trend.longMovingAverage",
                "analysis.trend.priceVsShortMovingAverage"):
        assert ref in refs
        assert resolve_reference(body, ref)


# --- 2. References resolve against the public HTTP JSON ----------------------

def test_insufficient_history_references_resolve_in_final_json(monkeypatch):
    body = _http(monkeypatch, make_snapshot(rising_closes(30), STRONG))
    supervision = body["supervision"]
    assert supervision["status"] == "insufficient_data"
    history = next(f for f in supervision["findings"] if f["ruleId"] == "HISTORY_INSUFFICIENT")
    assert history["evidenceRefs"] == [
        "supervision.dataQuality.historicalObservations",
        "supervision.dataQuality.requiredHistoricalObservations",
    ]
    assert supervision["dataQuality"]["historicalObservations"] == 30
    assert supervision["dataQuality"]["requiredHistoricalObservations"] == 50
    assert "30 observations are available; 50 are required" in history["message"]
    assert "dataset" not in body
    for ref in _all_refs(supervision):
        assert resolve_reference(body, ref), ref


def test_missing_fundamentals_references_resolve_in_final_json(monkeypatch):
    body = _http(monkeypatch, make_snapshot(rising_closes(120), None))
    supervision = body["supervision"]
    assert "FUNDAMENTALS_MISSING" in [f["ruleId"] for f in supervision["findings"]]
    for ref in _all_refs(supervision):
        assert resolve_reference(body, ref), ref


@pytest.mark.parametrize("symbol", DEMO_SYMBOLS)
def test_all_references_resolve_for_each_demo_symbol(symbol):
    body = client.post("/api/analyze", json={"symbol": symbol}).json()
    refs = _all_refs(body["supervision"])
    assert refs
    for ref in refs:
        assert resolve_reference(body, ref), ref


def _inject_finding_with_ref(monkeypatch, ref: str):
    import app.supervision.service as service

    real = service.evaluate_rules

    def with_bad_ref(inp):
        bad = Finding(ruleId="ZZ_TEST", category=FindingCategory.OBSERVATION, severity=Severity.INFO,
                      title="test", message="test", evidenceRefs=[ref])
        return real(inp) + [bad]

    monkeypatch.setattr(service, "evaluate_rules", with_bad_ref)


@pytest.mark.parametrize("ref", ["analysis.trend.missingField", "dataset.observations"])
def test_unresolvable_reference_raises_integrity_error(monkeypatch, ref):
    # "dataset.*" used to be accepted through an internal view; it is not public.
    _inject_finding_with_ref(monkeypatch, ref)
    with pytest.raises(SupervisionIntegrityError) as excinfo:
        analyze_symbol("NVDA", DemoDataProvider())
    assert f"unresolved evidence reference: {ref}" in excinfo.value.issues


def test_unresolvable_reference_returns_500_over_http(monkeypatch):
    _inject_finding_with_ref(monkeypatch, "dataset.requiredObservations")
    response = client.post("/api/analyze", json={"symbol": "NVDA"})
    assert response.status_code == 500
    assert set(response.json()) == {"error", "message"}


def test_dataset_requirement_must_match_engine_requirement():
    inp = make_input(dataset=make_dataset().model_copy(update={"requiredObservations": 40}))
    assert any("differs from the engine requirement 50" in i for i in integrity_issues(inp))


def test_published_requirement_matches_the_one_used_by_the_rules():
    inp = make_input(dataset=make_dataset(observations=30))
    quality = build_data_quality(inp, SupervisorStatus.INSUFFICIENT_DATA)
    assert quality.requiredHistoricalObservations == inp.dataset.requiredObservations == 50


# --- 3. Evidence is relative to the recommendation ----------------------------

def _directions(inp) -> dict[str, Direction]:
    supporting, opposing, neutral = build_evidence(inp)
    return {item.component: item.direction for item in supporting + opposing + neutral}


def test_buy_with_mixed_signals():
    inp = make_input(engine_recommendation="BUY", momentum_label="positive", momentum_score=0.5,
                     trend_label="bearish", trend_score=-0.5)
    assert _directions(inp)["momentum"] is Direction.SUPPORTING
    assert _directions(inp)["trend"] is Direction.OPPOSING
    report = _report_for(inp)
    assert any(r.startswith("Momentum is positive") for r in report.keyReasons)
    assert any(r.startswith("Trend is bearish") for r in report.counterpoints)


def test_sell_with_mixed_signals():
    inp = make_input(engine_recommendation="SELL", momentum_label="negative", momentum_score=-0.5,
                     fundamental_label="positive", fundamental_score=0.5)
    directions = _directions(inp)
    assert directions["momentum"] is Direction.SUPPORTING
    assert directions["fundamental"] is Direction.OPPOSING
    report = _report_for(inp)
    assert any(r.startswith("Momentum is negative") for r in report.keyReasons)
    assert any(r.startswith("Fundamentals are positive") for r in report.counterpoints)


def test_tsla_sell_has_its_negative_signals_as_key_reasons():
    body = client.post("/api/analyze", json={"symbol": "TSLA"}).json()
    assert body["recommendation"] == "SELL"
    supervision = body["supervision"]
    reasons = supervision["report"]["keyReasons"]
    assert reasons
    assert [i["component"] for i in supervision["supportingEvidence"]] == ["momentum", "trend", "fundamental"]
    assert all(i["polarity"] == "unfavorable" for i in supervision["supportingEvidence"])
    assert any(r.startswith("Momentum is negative") for r in reasons)
    assert any(r.startswith("Trend is bearish") for r in reasons)
    # High risk is a risk factor, not a reason to sell.
    assert [i["component"] for i in supervision["neutralEvidence"]] == ["risk"]
    assert any(r.startswith("Historical risk is high") for r in supervision["report"]["riskFactors"])
    assert not any("risk" in r.lower() for r in reasons)


def test_hold_with_neutral_signals():
    inp = make_input()  # HOLD, every directional signal neutral, moderate risk
    supporting, opposing, neutral = build_evidence(inp)
    assert [i.component for i in supporting] == ["momentum", "trend", "fundamental"]
    assert opposing == []
    assert [i.component for i in neutral] == ["risk"]
    report = _report_for(inp)
    assert not any("offset" in r for r in report.keyReasons)


def test_hold_with_offsetting_signals():
    inp = make_input(momentum_label="positive", momentum_score=0.5,
                     trend_label="bearish", trend_score=-0.5)
    supporting, opposing, _ = build_evidence(inp)
    assert {i.component for i in supporting} >= {"momentum", "trend"}
    assert opposing == []
    report = _report_for(inp)
    assert report.keyReasons[0] == (
        "Favorable signals (momentum) and unfavorable signals (trend) offset each other."
    )


def test_hold_with_one_sided_signal_lists_it_as_opposing():
    inp = make_input(momentum_label="positive", momentum_score=0.5)
    assert _directions(inp)["momentum"] is Direction.OPPOSING
    assert any(r.startswith("Momentum is positive") for r in _report_for(inp).counterpoints)


@pytest.mark.parametrize(
    ("recommendation", "risk_label", "risk_score", "direction", "in_risk_factors"),
    [
        ("BUY", "high", 0.8, Direction.OPPOSING, True),
        ("BUY", "low", 0.1, Direction.SUPPORTING, False),
        ("HOLD", "high", 0.8, Direction.NEUTRAL, True),
        ("HOLD", "low", 0.1, Direction.NEUTRAL, False),
        ("SELL", "high", 0.8, Direction.NEUTRAL, True),
        ("SELL", "low", 0.1, Direction.NEUTRAL, False),
    ],
)
def test_risk_matrix(recommendation, risk_label, risk_score, direction, in_risk_factors):
    inp = make_input(engine_recommendation=recommendation, risk_label=risk_label, risk_score=risk_score)
    assert _directions(inp)["risk"] is direction
    report = _report_for(inp)
    risk_lines = [r for r in report.riskFactors if r.startswith("Historical risk")]
    assert bool(risk_lines) is in_risk_factors
    assert not any(r.startswith("Historical risk") for r in report.counterpoints)
    if recommendation == "SELL":
        assert not any(r.startswith("Historical risk") for r in report.keyReasons)


def test_buy_high_risk_warning_is_kept():
    inp = make_input(engine_recommendation="BUY", risk_label="high", risk_score=0.8)
    assert "OPPORTUNITY_RISK_CONFLICT" in [f.ruleId for f in evaluate_rules(inp)]


def test_polarity_does_not_depend_on_recommendation():
    for recommendation in ("BUY", "HOLD", "SELL"):
        inp = make_input(engine_recommendation=recommendation,
                         momentum_label="positive", momentum_score=0.5)
        supporting, opposing, neutral = build_evidence(inp)
        momentum = next(i for i in supporting + opposing + neutral if i.component == "momentum")
        assert momentum.polarity is Polarity.FAVORABLE


@pytest.mark.parametrize("symbol", DEMO_SYMBOLS)
def test_each_component_appears_once_in_stable_order(symbol):
    result = analyze_symbol(symbol, DemoDataProvider())
    s = result.supervision
    components = [i.component for i in s.supportingEvidence + s.opposingEvidence + s.neutralEvidence]
    assert sorted(components) == sorted(set(components))
    for items in (s.supportingEvidence, s.opposingEvidence, s.neutralEvidence):
        order = [i.component for i in items]
        assert order == [c for c in COMPONENT_ORDER if c in order]
    assert analyze_symbol(symbol, DemoDataProvider()) == result


def test_engine_outputs_are_unchanged_by_the_supervisor():
    # Phase 2 values for the demo dataset; the supervisor must not alter them.
    expected = {"AAPL": ("HOLD", 0.64), "NVDA": ("BUY", 0.45), "TSLA": ("SELL", 0.86),
                "META": ("SELL", 0.27)}
    for symbol, (recommendation, confidence) in expected.items():
        result = analyze_symbol(symbol, DemoDataProvider())
        assert (result.recommendation, result.confidence) == (recommendation, confidence)


# --- 4. Provenance wording comes from metadata ---------------------------------

def _texts(report, limitations, findings, evidence) -> str:
    parts = [report.headline, report.summary, *report.keyReasons, *report.counterpoints,
             *report.riskFactors, *report.dataGaps]
    parts += [item.message for item in limitations] + [f.message for f in findings]
    parts += [item.description for item in evidence]
    return " ".join(parts).lower()


@pytest.mark.parametrize("provenance", ["historical", "live"])
def test_non_synthetic_provenance_never_claims_synthetic_data(provenance):
    inp = make_input(engine_recommendation="BUY", risk_label="high", risk_score=0.8,
                     fundamental_metrics_used=2, fundamental_raw_values=(0.1, None, 20.0, None),
                     momentum_label="positive", momentum_score=0.5,
                     trend_label="bearish", trend_score=-0.5,
                     dataset=make_dataset(provenance=provenance))
    findings = evaluate_rules(inp)
    supporting, opposing, neutral = build_evidence(inp)
    status = determine_status(inp, findings)
    quality = build_data_quality(inp, status)
    limitations = build_limitations(inp, quality)
    report = build_report(inp, status, findings, supporting, opposing, neutral, quality)
    text = _texts(report, limitations, findings, supporting + opposing + neutral)
    assert "synthetic" not in text
    assert "demo" not in text
    assert "SYNTHETIC_DATA" not in [item.code for item in limitations]
    phrase = {"historical": "historical market data", "live": "recent market data"}[provenance]
    assert f"on {phrase}." in report.summary


def test_synthetic_provenance_keeps_synthetic_warnings():
    inp = make_input()
    findings = evaluate_rules(inp)
    quality = build_data_quality(inp, determine_status(inp, findings))
    report = _report_for(inp)
    assert "on synthetic demo data." in report.summary
    assert "not real market prices" in report.summary
    assert "SYNTHETIC_DATA" in [item.code for item in build_limitations(inp, quality)]


def test_unknown_data_source_is_still_rejected():
    dataset = make_dataset().model_copy(update={"dataSource": "unknown_source"})
    with pytest.raises(SupervisionIntegrityError):
        supervise({}, dataset)

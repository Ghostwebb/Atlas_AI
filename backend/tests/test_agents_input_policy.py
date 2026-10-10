"""Input validity policy of the shared snapshot (review of 632f951).

A close is valid when finite and > 0; a volume when finite and >= 0. Every observation in a metric's
window must be valid; otherwise the metric is null with status invalid_input and a cause. Bars are
never dropped or filled, and invalid observations outside a window do not affect it.
"""

import json
import math

import pytest

from app.agents.engine import evaluate, validate_references
from app.agents.service import evaluate_snapshot
from app.agents.strategies import AEGIS, ARGO, NOVA, VECTOR
from app.data.provider import Fundamentals
from tests.agents_factories import agent_snapshot, built

BAD = [0.0, -5.0, float("nan"), float("inf"), float("-inf")]
FUND = Fundamentals(revenue_growth=0.1, profit_margin=0.1, pe_ratio=20.0, earnings_growth=0.05)


def snap(prices, volumes=None):
    return built(prices, volumes, FUND)


def metric(s, key):
    return s.metrics[key]


def vector_of(prices, volumes=None):
    return evaluate_snapshot(snap(prices, volumes)).model_dump(mode="json")["evaluations"][2]


# --- the reviewed reproduction ---------------------------------------------------------------

def test_flat_valid_series_is_neutral_for_vector():
    v = vector_of([100.0] * 70)
    assert v["status"] == "complete" and v["stance"] == "neutral" and v["score"] == 0.0


def test_reproduction_zeros_cannot_create_a_favorable_complete_vector():
    prices = [100.0] * 70
    for index in (30, 31, 60):
        prices[index] = 0.0
    s = snap(prices)
    for key in ("sma20", "sma50", "return_20d", "return_60d", "price_vs_sma20", "sma20_vs_sma50"):
        assert metric(s, key).value is None and metric(s, key).status == "invalid_input", key
        assert metric(s, key).issue
    assert "first 2026-03-02" in metric(s, "sma20").issue and "3 invalid" in metric(s, "sma50").issue
    v = vector_of(prices)
    assert v["status"] == "insufficient" and v["stance"] == "insufficient_data"
    assert v["score"] is None and v["coverage"] == 0.0
    assert v["evidence"] == {"favorable": [], "unfavorable": [], "neutral": []}
    assert {i["criterion"]: i["reason"] for i in v["notEvaluated"]} == {
        "return_60d": "invalid_input", "trend_alignment": "invalid_input", "return_20d": "invalid_input",
        "volume_confirmation": "invalid_input"}
    assert {r["id"] for r in v["risksNotEvaluated"]} == {"vector.high_recent_volatility", "vector.divergence"}
    assert v["risks"] == []


# --- every kind of invalid close, at the start / middle / end of each window ----------------

@pytest.mark.parametrize("bad", BAD, ids=["zero", "negative", "nan", "+inf", "-inf"])
@pytest.mark.parametrize("key, size", [("sma20", 20), ("sma50", 50), ("return_20d", 21), ("return_60d", 61),
                                       ("volatility_20d", 21)])
@pytest.mark.parametrize("where", ["start", "middle", "end"])
def test_invalid_close_anywhere_in_a_window_invalidates_it(bad, key, size, where):
    prices = [100.0 + (i % 3) for i in range(80)]
    position = {"start": 80 - size, "middle": 80 - size // 2 - 1, "end": 79}[where]
    prices[position] = bad
    m = metric(snap(prices), key)
    assert m.value is None and m.status == "invalid_input" and f"{size}-bar window" in m.issue


@pytest.mark.parametrize("key, size", [("sma20", 20), ("sma50", 50), ("return_20d", 21), ("return_60d", 61),
                                       ("volatility_20d", 21)])
def test_invalid_close_just_outside_a_window_does_not_invalidate_it(key, size):
    clean = [100.0 + (i % 3) for i in range(80)]
    prices = list(clean)
    prices[80 - size - 1] = 0.0
    assert metric(snap(prices), key).value == metric(snap(clean), key).value is not None
    assert metric(snap(prices), key).status == "ok"


def test_old_invalid_close_only_affects_full_window_metrics():
    prices = [100.0 + (i % 3) for i in range(80)]
    prices[5] = float("nan")
    s = snap(prices)
    for key in ("sma20", "sma50", "return_20d", "return_60d", "volatility_20d", "price_vs_sma20", "sma20_vs_sma50"):
        assert metric(s, key).status == "ok", key
    for key in ("volatility_annualized", "max_drawdown", "current_drawdown"):
        assert metric(s, key).value is None and metric(s, key).status == "invalid_input", key
    assert evaluate(VECTOR, s)["status"] == "complete"
    aegis = evaluate(AEGIS, s)
    assert aegis["status"] == "insufficient" and aegis["score"] is None
    assert {i["reason"] for i in aegis["notEvaluated"]} == {"invalid_input"}


def test_invalid_last_close_invalidates_price_and_dependants():
    prices = [100.0] * 70
    prices[-1] = -1.0
    s = snap(prices)
    assert metric(s, "price_last").status == "invalid_input"
    assert metric(s, "price_vs_sma20").issue == "depends on price_last (invalid_input), sma20 (invalid_input)"


# --- history vs invalid input vs missing ---------------------------------------------------

def test_insufficient_history_is_distinguished_from_invalid_input():
    short = snap([100.0] * 40)
    assert metric(short, "sma50").status == "insufficient_history" and "needs 50 bars, 40" in metric(short, "sma50").issue
    assert metric(short, "sma20_vs_sma50").status == "insufficient_history"
    assert metric(short, "sma20_vs_sma50").issue == "depends on sma50 (insufficient_history)"
    v = evaluate(VECTOR, short)
    assert {i["criterion"]: i["reason"] for i in v["notEvaluated"]}["return_60d"] == "insufficient_history"


def test_ratio_with_one_missing_mean_inherits_the_most_severe_cause():
    prices = [100.0] * 45
    prices[-3] = 0.0                   # sma20 invalid; sma50 lacks history
    s = snap(prices)
    assert metric(s, "sma20_vs_sma50").status == "invalid_input"
    assert metric(s, "sma20_vs_sma50").issue == \
        "depends on sma20 (invalid_input), sma50 (insufficient_history)"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_fundamental_is_invalid_not_missing(bad):
    s = built([100.0] * 70, fundamentals=Fundamentals(revenue_growth=None, profit_margin=bad, pe_ratio=20.0,
                                                      earnings_growth=0.1))
    assert metric(s, "revenue_growth").status == "missing" and metric(s, "profit_margin").status == "invalid_input"
    argo = evaluate(ARGO, s)
    assert {i["criterion"]: i["reason"] for i in argo["notEvaluated"]} == {"margin_quality": "invalid_input"}
    assert argo["status"] == "partial"


# --- volume ---------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")], ids=["negative", "nan", "inf"])
def test_invalid_volume_cannot_confirm(bad):
    prices = [100.0 + i for i in range(70)]          # rising: return_20d > 0
    volumes = [1_000_000] * 50 + [5_000_000] * 20
    volumes[60] = bad
    s = snap(prices, volumes)
    assert metric(s, "volume_ratio_20_60").status == "invalid_input"
    v = evaluate(VECTOR, s)
    assert {i["criterion"]: i["reason"] for i in v["notEvaluated"]} == {"volume_confirmation": "invalid_input"}
    assert all(i["criterion"] != "volume_confirmation" for i in v["evidence"]["favorable"])
    assert v["status"] == "partial"


def test_zero_volume_days_are_valid_and_all_zero_is_not_computable():
    some_zero = snap([100.0] * 70, [1000] * 69 + [0])
    assert metric(some_zero, "volume_ratio_20_60").status == "ok"
    all_zero = snap([100.0] * 70, [0] * 70)
    m = metric(all_zero, "volume_ratio_20_60")
    assert m.value is None and m.status == "not_computable" and "zero" in m.issue
    v = evaluate(VECTOR, all_zero)
    assert {i["criterion"]: i["reason"] for i in v["notEvaluated"]} == {"volume_confirmation": "not_computable"}


# --- risks, core propagation, references, JSON ----------------------------------------------

def test_risks_that_cannot_be_checked_are_reported_not_hidden_or_inflated():
    r = evaluate(VECTOR, agent_snapshot(volatility_20d=None, _status={"volatility_20d": "invalid_input"}))
    assert r["risks"] == []
    assert [(x["id"], x["reason"]) for x in r["risksNotEvaluated"]] == [("vector.high_recent_volatility",
                                                                         "invalid_input")]
    assert r["status"] == "complete" and r["coverage"] == 1.0   # coverage covers scored criteria only
    nova = evaluate(NOVA, agent_snapshot(earnings_growth=None))
    assert [x["id"] for x in nova["risksNotEvaluated"]] == ["nova.growth_not_reaching_earnings"]


def test_invalidating_a_core_criterion_drops_score_and_status():
    healthy = evaluate(VECTOR, agent_snapshot(return_60d=0.2, price_vs_sma20=0.01, sma20_vs_sma50=0.01))
    assert healthy["stance"] == "favorable" and healthy["status"] == "complete"
    broken = evaluate(VECTOR, agent_snapshot(return_60d=None, price_vs_sma20=0.01, sma20_vs_sma50=0.01,
                                             _status={"return_60d": "invalid_input"}))
    assert broken["status"] == "insufficient" and broken["stance"] == "insufficient_data"
    assert broken["score"] is None and broken["coverage"] == 0.65
    assert broken["evidence"]["favorable"]  # still shown, but no stance is derived from a partial core


def test_references_and_json_have_no_nan_or_infinity():
    prices = [100.0] * 70
    prices[10], prices[65] = float("nan"), float("inf")
    response = evaluate_snapshot(snap(prices, [1000] * 69 + [float("nan")]))
    document = json.loads(response.model_dump_json())
    validate_references(document)
    text = response.model_dump_json()
    assert "NaN" not in text and "Infinity" not in text

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, float):
            assert math.isfinite(node)
    walk(document)


def test_no_evidence_cites_an_unavailable_metric():
    prices = [100.0] * 70
    for index in (30, 31, 60):
        prices[index] = 0.0
    document = json.loads(evaluate_snapshot(snap(prices)).model_dump_json())
    metrics = document["snapshot"]["metrics"]
    for e in document["evaluations"]:
        for group in e["evidence"].values():
            for item in group:
                for ref in item["references"]:
                    assert metrics[ref["path"].split(".")[-1]]["status"] == "ok"

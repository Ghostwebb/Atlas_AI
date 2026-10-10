"""Phase 7 strategy rules: exact boundaries, missing data, interpretability, stance and status."""

import pytest

from app.agents import config as C
from app.agents.engine import evaluate
from app.agents.strategies import AEGIS, ARGO, NOVA, REGISTRY, VECTOR
from tests.agents_factories import agent_snapshot


def ev(strategy, **metrics):
    return evaluate(strategy, agent_snapshot(**metrics))


def direction(result, criterion):
    for d in ("favorable", "unfavorable", "neutral"):
        for item in result["evidence"][d]:
            if item["criterion"] == criterion:
                return d
    for item in result["notEvaluated"]:
        if item["criterion"] == criterion:
            return item["reason"]
    raise AssertionError(f"criterion {criterion} not reported")


# --- baseline --------------------------------------------------------------------------------

@pytest.mark.parametrize("strategy", REGISTRY, ids=lambda s: s.id)
def test_neutral_baseline_is_complete_and_neutral(strategy):
    r = ev(strategy)
    assert r["status"] == "complete" and r["stance"] == "neutral" and r["score"] == 0.0 and r["coverage"] == 1.0
    assert r["evidence"]["favorable"] == [] and r["evidence"]["unfavorable"] == [] and r["missingData"] == []


# --- ARGO --------------------------------------------------------------------------------------

@pytest.mark.parametrize("pe, expected", [
    (15.0, "favorable"), (15.000001, "neutral"), (24.999999, "neutral"), (25.0, "unfavorable"), (0.5, "favorable"),
])
def test_argo_pe_boundaries(pe, expected):
    assert direction(ev(ARGO, pe_ratio=pe), "pe_valuation") == expected


@pytest.mark.parametrize("pe", [0.0, -12.0])
def test_argo_non_positive_pe_is_not_interpretable_and_never_cheap(pe):
    r = ev(ARGO, pe_ratio=pe)
    assert direction(r, "pe_valuation") == "not_interpretable"
    assert r["status"] == "insufficient" and r["stance"] == "insufficient_data" and r["score"] is None
    assert [x["id"] for x in r["risks"]] == ["argo.negative_earnings"]
    assert all(item["criterion"] != "pe_valuation" for item in r["evidence"]["favorable"])


def test_argo_missing_pe_is_insufficient_not_cheap():
    r = ev(ARGO, pe_ratio=None)
    assert r["status"] == "insufficient" and r["stance"] == "insufficient_data" and r["score"] is None
    assert r["missingData"] == ["pe_ratio"] and r["coverage"] == 0.5


@pytest.mark.parametrize("margin, expected", [
    (0.15, "favorable"), (0.149999, "neutral"), (0.05, "neutral"), (0.049999, "unfavorable"), (-0.2, "unfavorable"),
])
def test_argo_margin_boundaries_in_decimals(margin, expected):
    assert direction(ev(ARGO, profit_margin=margin), "margin_quality") == expected


def test_argo_margin_in_percentage_points_would_be_misread():
    # 15 (percentage points) is not 0.15: the rules use decimals, documented in config.
    assert direction(ev(ARGO, profit_margin=0.15), "margin_quality") == "favorable"
    assert direction(ev(ARGO, profit_margin=0.12), "margin_quality") == "neutral"


@pytest.mark.parametrize("growth, expected", [(-0.000001, "unfavorable"), (0.0, "neutral"), (0.5, "neutral")])
def test_argo_value_trap(growth, expected):
    assert direction(ev(ARGO, earnings_growth=growth), "value_trap") == expected


def test_argo_cheap_but_shrinking_is_mixed_and_cheap_quality_is_favorable():
    cheap_trap = ev(ARGO, pe_ratio=10.0, profit_margin=0.02, earnings_growth=-0.10)
    assert cheap_trap["score"] == 0.0 and cheap_trap["stance"] == "neutral"
    quality = ev(ARGO, pe_ratio=10.0, profit_margin=0.20, earnings_growth=0.05)
    assert quality["score"] == 0.8 and quality["stance"] == "favorable"


def test_argo_cannot_be_favorable_without_favorable_valuation():
    r = ev(ARGO, pe_ratio=20.0, profit_margin=0.40)
    assert r["score"] == 0.3 and r["stance"] == "neutral"


def test_argo_partial_when_a_non_core_metric_is_missing():
    r = ev(ARGO, pe_ratio=10.0, earnings_growth=None)
    assert r["status"] == "partial" and r["coverage"] == 0.8 and r["missingData"] == ["earnings_growth"]
    assert r["score"] == round(0.5 / 0.8, 4) and r["stance"] == "favorable"


# --- NOVA --------------------------------------------------------------------------------------

@pytest.mark.parametrize("growth, expected", [
    (0.15, "favorable"), (0.149999, "neutral"), (0.05, "neutral"), (0.049999, "unfavorable"), (-0.3, "unfavorable"),
])
def test_nova_revenue_boundaries(growth, expected):
    assert direction(ev(NOVA, revenue_growth=growth), "revenue_growth") == expected


@pytest.mark.parametrize("growth, expected", [(0.15, "favorable"), (0.0, "neutral"), (-0.000001, "unfavorable")])
def test_nova_earnings_boundaries(growth, expected):
    assert direction(ev(NOVA, earnings_growth=growth), "earnings_growth") == expected


def test_nova_ignores_pe_and_momentum():
    a = ev(NOVA, pe_ratio=120.0, return_60d=0.9, return_20d=0.5)
    b = ev(NOVA, pe_ratio=5.0, return_60d=-0.9, return_20d=-0.5)
    assert a["score"] == b["score"] == 0.0 and a["stance"] == b["stance"] == "neutral"


def test_nova_missing_growth_is_not_replaced_by_momentum():
    r = ev(NOVA, revenue_growth=None, return_60d=0.5)
    assert r["status"] == "insufficient" and r["stance"] == "insufficient_data" and r["score"] is None


def test_nova_growth_not_reaching_earnings_and_unprofitable_risks():
    r = ev(NOVA, revenue_growth=0.20, earnings_growth=-0.10, profit_margin=-0.05)
    assert {x["id"] for x in r["risks"]} == {"nova.growth_not_reaching_earnings", "nova.unprofitable"}
    assert r["score"] == round((0.4 - 0.3 - 0.3) / 1.0, 4) and r["stance"] == "neutral"


# --- VECTOR ------------------------------------------------------------------------------------

@pytest.mark.parametrize("ret, expected", [
    (0.10, "favorable"), (0.099999, "neutral"), (-0.099999, "neutral"), (-0.10, "unfavorable"),
])
def test_vector_return_60d_boundaries(ret, expected):
    assert direction(ev(VECTOR, return_60d=ret), "return_60d") == expected


@pytest.mark.parametrize("ret, expected", [(0.03, "favorable"), (0.029999, "neutral"), (-0.03, "unfavorable")])
def test_vector_return_20d_boundaries(ret, expected):
    assert direction(ev(VECTOR, return_20d=ret), "return_20d") == expected


@pytest.mark.parametrize("p, s, expected", [
    (0.01, 0.01, "favorable"), (-0.01, -0.01, "unfavorable"), (0.01, -0.01, "neutral"), (0.0, 0.02, "neutral"),
])
def test_vector_alignment(p, s, expected):
    assert direction(ev(VECTOR, price_vs_sma20=p, sma20_vs_sma50=s), "trend_alignment") == expected


@pytest.mark.parametrize("ratio, r20, expected", [
    (1.2, 0.01, "favorable"), (1.2, -0.01, "unfavorable"), (1.199999, 0.05, "neutral"), (1.5, 0.0, "neutral"),
])
def test_vector_volume_confirmation(ratio, r20, expected):
    assert direction(ev(VECTOR, volume_ratio_20_60=ratio, return_20d=r20), "volume_confirmation") == expected


def test_vector_strong_uptrend_with_risks_is_favorable_but_risks_are_separate():
    r = ev(VECTOR, return_60d=0.3, return_20d=-0.05, price_vs_sma20=0.02, sma20_vs_sma50=0.03,
           volatility_20d=0.55)
    assert r["stance"] == "favorable"
    assert {x["id"] for x in r["risks"]} == {"vector.high_recent_volatility", "vector.divergence"}


def test_vector_needs_history():
    r = ev(VECTOR, return_60d=None)
    assert r["status"] == "insufficient" and r["stance"] == "insufficient_data"


# --- AEGIS -------------------------------------------------------------------------------------

@pytest.mark.parametrize("vol, expected", [
    (0.25, "favorable"), (0.250001, "neutral"), (0.449999, "neutral"), (0.45, "unfavorable"),
])
def test_aegis_volatility_boundaries(vol, expected):
    assert direction(ev(AEGIS, volatility_annualized=vol), "volatility") == expected


@pytest.mark.parametrize("dd, expected", [(0.15, "favorable"), (0.2999, "neutral"), (0.30, "unfavorable")])
def test_aegis_max_drawdown_boundaries(dd, expected):
    assert direction(ev(AEGIS, max_drawdown=dd), "max_drawdown") == expected


@pytest.mark.parametrize("dd, expected", [(0.05, "favorable"), (0.1999, "neutral"), (0.20, "unfavorable")])
def test_aegis_current_drawdown_boundaries(dd, expected):
    assert direction(ev(AEGIS, current_drawdown=dd), "current_drawdown") == expected


def test_aegis_missing_risk_data_is_not_low_risk():
    r = ev(AEGIS, volatility_annualized=None, max_drawdown=None, current_drawdown=0.0, profit_margin=0.5)
    assert r["status"] == "insufficient" and r["stance"] == "insufficient_data" and r["score"] is None
    assert r["evidence"]["favorable"] != []  # still reported, but no stance is produced


def test_aegis_rising_volatility_risk():
    assert [x["id"] for x in ev(AEGIS, volatility_annualized=0.2, volatility_20d=0.3)["risks"]] == \
        ["aegis.rising_volatility"]
    assert ev(AEGIS, volatility_annualized=0.2, volatility_20d=0.29)["risks"] == []


def test_aegis_never_claims_safety():
    r = ev(AEGIS, volatility_annualized=0.1, max_drawdown=0.05, current_drawdown=0.0, profit_margin=0.3)
    assert r["stance"] == "favorable"
    text = (r["stanceMeaning"] + " ".join(r["limitations"])).lower()
    assert "not a statement that the stock is safe" in text and "no hedging" in text


# --- shared ------------------------------------------------------------------------------------

def test_stance_band_edges():
    exact = ev(VECTOR, return_60d=0.10, return_20d=0.0)            # 0.35 points
    assert exact["score"] == 0.35 and exact["stance"] == "favorable"
    below = ev(AEGIS, current_drawdown=0.05, profit_margin=0.15)   # 0.30 points, no core favorable
    assert below["score"] == 0.3 and below["stance"] == "neutral"
    band = ev(ARGO, pe_ratio=10.0, profit_margin=0.02, earnings_growth=-0.01)
    assert band["score"] == 0.0


def test_missing_is_never_zero_or_favorable():
    for strategy in REGISTRY:
        r = evaluate(strategy, agent_snapshot(**{k: None for k in
                                                 ("pe_ratio", "revenue_growth", "earnings_growth", "profit_margin",
                                                  "return_20d", "return_60d", "price_vs_sma20", "sma20_vs_sma50",
                                                  "volatility_annualized", "volatility_20d", "max_drawdown",
                                                  "current_drawdown", "volume_ratio_20_60")}))
        assert r["status"] == "insufficient" and r["score"] is None and r["coverage"] == 0.0
        assert r["evidence"] == {"favorable": [], "unfavorable": [], "neutral": []}
        assert all(item["reason"] == "missing" for item in r["notEvaluated"])


def test_evaluations_vary_with_data_not_names():
    assert ev(NOVA, revenue_growth=0.3)["score"] != ev(NOVA, revenue_growth=0.01)["score"]
    assert ev(AEGIS, volatility_annualized=0.1)["evidence"] != ev(AEGIS, volatility_annualized=0.6)["evidence"]


def test_justified_disagreement_on_one_snapshot():
    snap = agent_snapshot(pe_ratio=60.0, revenue_growth=0.40, earnings_growth=0.50, profit_margin=0.30,
                          return_60d=0.40, return_20d=0.10, price_vs_sma20=0.05, sma20_vs_sma50=0.08,
                          volatility_annualized=0.60, max_drawdown=0.35, current_drawdown=0.02)
    stances = {s.id: evaluate(s, snap)["stance"] for s in REGISTRY}
    assert stances == {"argo": "neutral", "nova": "favorable", "vector": "favorable", "aegis": "unfavorable"}
    argo = evaluate(ARGO, snap)
    assert argo["evidence"]["unfavorable"][0]["criterion"] == "pe_valuation"


def test_weights_and_versions():
    C.validate_config()
    assert [s.id for s in REGISTRY] == ["argo", "nova", "vector", "aegis"]
    assert all(s.version == "1.0.1" for s in REGISTRY)
    for s in REGISTRY:
        assert abs(sum(c.weight for c in s.criteria) - 1.0) < 1e-9 and any(c.core for c in s.criteria)


def test_config_rejects_bad_weights(monkeypatch):
    monkeypatch.setitem(C.ARGO_WEIGHTS, "pe_valuation", 0.9)
    with pytest.raises(ValueError):
        C.validate_config()

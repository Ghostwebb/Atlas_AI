"""Committee policy: states, precedence, requirements, abstentions, risk gate, shared evidence."""

import pytest

from app.committee import config as C
from app.committee.rules import build_committee, independent_bases
from tests.committee_factories import (FAVORABLE, UNFAVORABLE, agents_doc, clone, committee, evaluation, response,
                                       state)


def req(c):
    return {r["id"]: r["met"] for r in c["conclusion"]["requirements"]}


def kinds(c, key="conflicts"):
    return [f["kind"] for f in c[key]]


# --- aligned_favorable and its requirements --------------------------------------------------

def test_aligned_favorable_when_every_requirement_holds():
    c = committee(**FAVORABLE)
    assert c["conclusion"]["state"] == "aligned_favorable" and all(req(c).values())
    agreement = c["agreements"][0]
    assert agreement["strategies"] == ["nova", "vector"] and agreement["independentBases"] == 2
    assert "not a probability" in c["conclusion"]["summary"]
    assert c["conditions"] == [] and c["observedRisks"] == [] and c["unevaluatedRisks"] == []


@pytest.mark.parametrize("override, failed", [
    (dict(volatility_annualized=0.50), "R6"),                      # AEGIS volatility unfavorable
    (dict(max_drawdown=0.30), "R6"),                               # AEGIS drawdown unfavorable
    (dict(volatility_20d=0.45, volatility_annualized=0.30), "R7"),  # VECTOR high recent volatility flag
    (dict(pe_ratio=30.0), "R9"),                                   # ARGO P/E unfavorable
    (dict(pe_ratio=None), "R9"),                                   # valuation not evaluable
])
def test_any_unmet_requirement_turns_alignment_into_caution(override, failed):
    c = committee(**{**FAVORABLE, **override})
    assert c["conclusion"]["state"] == "caution"
    assert req(c)[failed] is False and f"unmet:{failed}" in c["conclusion"]["rulesApplied"]
    assert any(cond["id"] == f"condition:{failed}" for cond in c["conditions"])


def test_high_risk_does_not_disappear_because_others_are_favorable():
    c = committee(**{**FAVORABLE, "volatility_annualized": 0.60, "max_drawdown": 0.40})
    assert c["conclusion"]["state"] == "caution"
    assert {f["kind"] for f in c["observedRisks"]} == {"risk_exposure"}
    assert "momentum_with_high_risk" in kinds(c)
    tension = next(f for f in c["conflicts"] if f["kind"] == "momentum_with_high_risk")
    assert {r["strategyId"] for r in tension["references"]} == {"vector", "aegis"}


def test_unevaluated_risk_is_not_absence_of_risk():
    c = committee(**{**FAVORABLE, "volatility_20d": None, "_status": {"volatility_20d": "invalid_input"}})
    assert c["conclusion"]["state"] == "caution" and req(c)["R8"] is False
    assert {f["id"] for f in c["unevaluatedRisks"]} == {"unevaluated:vector.high_recent_volatility",
                                                        "unevaluated:aegis.rising_volatility"}
    assert all("not the same as no risk" in f["statement"] for f in c["unevaluatedRisks"])
    assert c["observedRisks"] == []   # not converted into a high risk either


def test_aegis_insufficient_blocks_alignment_and_is_not_a_vote():
    c = committee(**{**FAVORABLE, "volatility_annualized": None, "max_drawdown": None})
    assert c["conclusion"]["state"] == "caution" and req(c)["R6"] is False
    assert [a["strategyId"] for a in c["abstentions"]] == ["aegis"]
    assert all(f["references"][0]["strategyId"] != "aegis" for f in c["arguments"])


def test_aegis_favorable_evidence_is_risk_profile_not_argument():
    c = committee(**FAVORABLE)
    assert {r["strategyId"] for f in c["arguments"] for r in f["references"]} <= {"argo", "nova", "vector"}
    assert c["riskProfile"] and all(f["references"][0]["strategyId"] == "aegis" for f in c["riskProfile"])
    assert all("not safety" in f["statement"] for f in c["riskProfile"])


def test_single_favorable_perspective_is_caution_not_consensus():
    c = committee(**{**FAVORABLE, "return_60d": 0.0, "return_20d": 0.0, "price_vs_sma20": 0.0,
                     "sma20_vs_sma50": 0.0})
    assert c["conclusion"]["state"] == "caution" and req(c)["R2"] is False and c["agreements"] == []


@pytest.mark.parametrize("coverage, expected", [(0.75, "aligned_favorable"), (0.7499, "caution")])
def test_coverage_boundary_for_alignment(coverage, expected):
    doc = agents_doc(**FAVORABLE)
    evaluation(doc, "nova")["coverage"] = coverage
    assert build_committee(doc)["conclusion"]["state"] == expected


def test_partial_evaluation_stays_visible_and_low_coverage_blocks_alignment():
    c = committee(**{**FAVORABLE, "earnings_growth": None})       # NOVA coverage 0.7, still favorable
    nova = next(p for p in c["participants"] if p["strategyId"] == "nova")
    assert nova["status"] == "partial" and nova["coverage"] == 0.7 and nova["participates"]
    assert c["conclusion"]["state"] == "caution" and req(c)["R4"] is False
    assert "partial_evaluation" in kinds(c, "observations")
    assert any(m["metric"] == "earnings_growth" for m in c["missingData"])


# --- insufficient_data and abstentions --------------------------------------------------------

def test_all_insufficient():
    c = committee(**{k: None for k in ("pe_ratio", "revenue_growth", "return_60d", "volatility_annualized")})
    assert c["conclusion"]["state"] == "insufficient_data"
    assert len(c["abstentions"]) == 4 and not any(p["participates"] for p in c["participants"])
    assert c["arguments"] == [] and c["counterpoints"] == []


def test_single_available_opportunity_perspective_cannot_produce_consensus():
    c = committee(**{**FAVORABLE, "pe_ratio": None, "revenue_growth": None})
    assert c["conclusion"]["state"] == "insufficient_data" and req(c)["R1"] is False
    assert {a["strategyId"] for a in c["abstentions"]} == {"argo", "nova"}


def test_insufficient_agent_counts_neither_as_neutral_nor_favorable():
    c = committee(**{**FAVORABLE, "pe_ratio": None})
    argo = next(p for p in c["participants"] if p["strategyId"] == "argo")
    assert argo["participates"] is False and argo["stance"] == "insufficient_data"
    assert c["agreements"][0]["strategies"] == ["nova", "vector"]
    assert not any(r["strategyId"] == "argo" for f in c["arguments"] for r in f["references"])


def test_invalid_input_blocks_strong_conclusions():
    c = committee(**{**FAVORABLE, "return_60d": None, "_status": {"return_60d": "invalid_input"}})
    assert c["conclusion"]["state"] == "caution"
    assert "invalid_input_blocking" in kinds(c, "observations")
    assert next(a for a in c["abstentions"] if a["strategyId"] == "vector")["causes"] == ["invalid_input"]


# --- conflicts, unfavorable, neutral, precedence ----------------------------------------------

def test_growth_versus_momentum_is_conflicted():
    c = committee(**{**FAVORABLE, "return_60d": -0.2, "return_20d": -0.05, "price_vs_sma20": -0.02,
                     "sma20_vs_sma50": -0.03})
    assert c["conclusion"]["state"] == "conflicted"
    conflict = next(f for f in c["conflicts"] if f["kind"] == "growth_vs_momentum")
    assert conflict["level"] == "stance"
    assert {(r["strategyId"], r["direction"]) for r in conflict["references"]} == {("nova", "favorable"),
                                                                                   ("vector", "unfavorable")}


def test_valuation_versus_growth_tension_at_criterion_level():
    c = committee(**{**FAVORABLE, "pe_ratio": 30.0, "return_60d": 0.0, "return_20d": 0.0,
                     "price_vs_sma20": 0.0, "sma20_vs_sma50": 0.0})
    tension = next(f for f in c["conflicts"] if f["kind"] == "valuation_vs_growth")
    assert tension["level"] == "criterion" and "limited P/E lens" in tension["statement"]
    assert c["conclusion"]["state"] == "caution"


def test_valuation_versus_growth_at_stance_level_is_conflicted():
    c = committee(**{**FAVORABLE, "pe_ratio": 40.0, "profit_margin": 0.20, "earnings_growth": -0.05,
                     "revenue_growth": 0.30})
    assert evaluation(agents_doc(**{**FAVORABLE, "pe_ratio": 40.0, "earnings_growth": -0.05,
                                    "revenue_growth": 0.30}), "argo")["stance"] == "unfavorable"
    assert c["conclusion"]["state"] == "conflicted"
    assert any(f["kind"] == "valuation_vs_growth" and f["level"] == "stance" for f in c["conflicts"])


def test_aligned_unfavorable():
    c = committee(**UNFAVORABLE)
    assert c["conclusion"]["state"] == "aligned_unfavorable"
    assert c["agreements"][0]["direction"] == "unfavorable" and c["agreements"][0]["independentBases"] >= 2


def test_neutral_and_neutral_is_not_low_risk():
    c = committee()
    assert c["conclusion"]["state"] == "neutral" and "does not mean low risk" in c["conclusion"]["summary"]
    assert "insufficient_directional_evidence" in kinds(c, "observations")


def test_single_unfavorable_perspective_is_neutral_with_counterpoints():
    c = committee(return_60d=-0.2, price_vs_sma20=-0.01, sma20_vs_sma50=-0.01)
    assert c["conclusion"]["state"] == "neutral" and c["counterpoints"]


def test_precedence_insufficient_before_conflicted_and_conflicted_before_alignment():
    assert state(**{**FAVORABLE, "pe_ratio": None, "revenue_growth": None, "return_60d": -0.2}) == "insufficient_data"
    two_fav_one_unf = {**FAVORABLE, "pe_ratio": 40.0, "earnings_growth": -0.05}
    assert state(**two_fav_one_unf) == "conflicted"
    assert C.PRECEDENCE == ("insufficient_data", "conflicted", "aligned_unfavorable", "aligned_favorable",
                            "caution", "neutral")


# --- shared evidence ------------------------------------------------------------------------

def test_shared_metrics_are_listed_once_not_as_independent_sources():
    c = committee(**FAVORABLE)
    margin = next(s for s in c["sharedEvidence"] if s["path"] == "agents.snapshot.metrics.profit_margin")
    assert {x["strategyId"] for x in margin["citedBy"]} == {"argo", "nova", "aegis"}
    assert "not independent confirmation" in margin["statement"]


def test_two_perspectives_on_the_same_core_metric_are_one_base():
    doc = agents_doc(**FAVORABLE)
    vector = evaluation(doc, "vector")
    for item in vector["evidence"]["favorable"]:
        if item["core"]:
            item["references"] = [dict(evaluation(doc, "nova")["evidence"]["favorable"][0]["references"][0])]
    assert independent_bases({e["strategyId"]: e for e in doc["evaluations"]}, ["nova", "vector"], "favorable") \
        == [["nova", "vector"]]
    c = build_committee(doc)
    assert c["conclusion"]["state"] == "caution" and req(c)["R5"] is False
    assert c["agreements"][0]["independentBases"] == 1


# --- traceability and determinism -------------------------------------------------------------

def test_every_finding_cites_published_evidence_and_evaluations_are_untouched():
    for metrics in (FAVORABLE, UNFAVORABLE, {**FAVORABLE, "volatility_annualized": 0.6}, {}):
        doc = agents_doc(**metrics)
        before = clone(doc)
        out = response(**metrics)          # runs validate_committee
        assert out["agents"] == before
        assert build_committee(doc) == build_committee(clone(doc)) and doc == before


def test_no_global_confidence_or_winner():
    c = committee(**FAVORABLE)
    text = str(c).lower()
    for word in ("confidence", "winner", "best_agent", "probability\":", "buy", "sell"):
        assert word not in text, word

"""Supervisor rules: scenarios, exact thresholds, integrity and status precedence.

Expected values here are derived by hand from the rule definitions, not from
the implementation under test.
"""

import math
from dataclasses import replace

import pytest

from app.supervision.config import DIRECTION_MIN_MAGNITUDE
from app.supervision.models import (
    FindingCategory,
    Severity,
    SupervisionIntegrityError,
    SupervisorStatus,
)
from app.supervision.rules import (
    _side,
    evaluate_rules,
    integrity_issues,
    rule_fundamentals_gap,
    rule_history_insufficient,
    rule_momentum_trend_divergence,
    rule_opportunity_risk_conflict,
    rule_technical_fundamental_divergence,
)
from app.supervision.service import determine_status, resolve_reference
from tests.supervision_factories import make_dataset, make_input, make_unavailable_trend


def rule_ids(findings):
    return [f.ruleId for f in findings]


# --- Scenario 1 & 2: momentum vs trend -----------------------------------

def test_positive_momentum_with_bearish_trend_is_flagged():
    inp = make_input(momentum_label="positive", momentum_score=0.50,
                     trend_label="bearish", trend_score=-0.40)
    finding = rule_momentum_trend_divergence(inp)
    assert finding is not None
    assert finding.ruleId == "MOMENTUM_TREND_DIVERGENCE"
    assert finding.severity is Severity.WARNING
    assert finding.category is FindingCategory.CONTRADICTION
    assert finding.message == "Positive momentum coexists with a bearish trend."
    assert finding.evidenceRefs == ["analysis.momentum.score", "analysis.trend.score"]


def test_negative_momentum_with_bullish_trend_is_flagged():
    inp = make_input(momentum_label="negative", momentum_score=-0.50,
                     trend_label="bullish", trend_score=0.40)
    finding = rule_momentum_trend_divergence(inp)
    assert finding is not None
    assert finding.message.startswith("Negative momentum coexists with a bullish trend")


# --- Scenario 3: near zero must not create false conflicts -----------------

def test_near_zero_signals_do_not_conflict():
    inp = make_input(momentum_label="neutral", momentum_score=0.05,
                     trend_label="neutral", trend_score=-0.05)
    assert rule_momentum_trend_divergence(inp) is None


def test_zero_momentum_with_strong_trend_does_not_conflict():
    inp = make_input(momentum_label="neutral", momentum_score=0.0,
                     trend_label="bearish", trend_score=-0.90)
    assert rule_momentum_trend_divergence(inp) is None


# --- Exact threshold boundaries -------------------------------------------

def test_threshold_is_inclusive_at_exactly_0_20():
    assert DIRECTION_MIN_MAGNITUDE == 0.20
    assert _side(0.20) == 1
    assert _side(-0.20) == -1


def test_threshold_excludes_just_below_0_20():
    assert _side(0.1999) == 0
    assert _side(-0.1999) == 0


def test_boundary_case_creates_finding_at_exactly_threshold():
    inp = make_input(momentum_label="positive", momentum_score=0.20,
                     trend_label="bearish", trend_score=-0.20)
    assert rule_momentum_trend_divergence(inp) is not None


def test_boundary_case_below_threshold_creates_no_finding():
    inp = make_input(momentum_label="neutral", momentum_score=0.19,
                     trend_label="bearish", trend_score=-0.20)
    assert rule_momentum_trend_divergence(inp) is None


def test_absent_scores_never_conflict():
    inp = make_unavailable_trend()
    assert rule_momentum_trend_divergence(inp) is None


# --- Scenario 4: technical favorable vs fundamentals unfavorable ----------

def test_favorable_technicals_with_unfavorable_fundamentals_is_flagged():
    # Technical composite = (0.3*0.6 + 0.3*0.2) / 0.6 = 0.40 (hand-computed).
    inp = make_input(momentum_label="positive", momentum_score=0.6,
                     trend_label="bullish", trend_score=0.2,
                     fundamental_label="negative", fundamental_score=-0.5)
    finding = rule_technical_fundamental_divergence(inp)
    assert finding is not None
    assert finding.ruleId == "TECHNICAL_FUNDAMENTAL_DIVERGENCE"
    assert "favorable" in finding.message and "unfavorable" in finding.message


def test_technical_composite_exactly_at_threshold_counts():
    # (0.3*0.2 + 0.3*0.2)/0.6 = 0.20 -> favorable; fundamentals -0.20 -> unfavorable.
    inp = make_input(momentum_label="positive", momentum_score=0.20,
                     trend_label="bullish", trend_score=0.20,
                     fundamental_label="negative", fundamental_score=-0.20)
    assert rule_technical_fundamental_divergence(inp) is not None


def test_technical_composite_below_threshold_does_not_count():
    # (0.3*0.2 + 0.3*0.18)/0.6 = 0.19 -> neutral.
    inp = make_input(momentum_label="positive", momentum_score=0.20,
                     trend_label="neutral", trend_score=0.18,
                     fundamental_label="negative", fundamental_score=-0.5)
    assert rule_technical_fundamental_divergence(inp) is None


def test_no_fundamental_divergence_when_fundamentals_missing():
    inp = make_input(fundamental_label="unavailable", fundamental_score=None,
                     fundamental_metrics_used=0,
                     fundamental_raw_values=(None, None, None, None),
                     momentum_label="positive", momentum_score=0.6,
                     trend_label="bullish", trend_score=0.6)
    assert rule_technical_fundamental_divergence(inp) is None


# --- Scenario 5: BUY with high risk ---------------------------------------

def test_buy_with_high_risk_is_a_caution_conflict_not_an_error():
    inp = make_input(engine_recommendation="BUY", risk_label="high", risk_score=0.8)
    finding = rule_opportunity_risk_conflict(inp)
    assert finding is not None
    assert finding.category is FindingCategory.CAUTION
    assert "not a statement that the recommendation is wrong" in finding.message


@pytest.mark.parametrize(
    ("recommendation", "risk_label"),
    [("HOLD", "high"), ("SELL", "high"), ("BUY", "moderate"), ("BUY", "low")],
)
def test_opportunity_risk_rule_only_fires_for_buy_with_high_risk(recommendation, risk_label):
    inp = make_input(engine_recommendation=recommendation, risk_label=risk_label)
    assert rule_opportunity_risk_conflict(inp) is None


# --- Scenario 6: insufficient history --------------------------------------

def test_insufficient_history_is_reported_as_data_gap():
    inp = make_unavailable_trend(observations=30)
    finding = rule_history_insufficient(inp)
    assert finding is not None
    assert finding.category is FindingCategory.DATA_GAP
    assert "30 observations" in finding.message and "50 are required" in finding.message


def test_insufficient_history_yields_insufficient_status():
    inp = make_unavailable_trend(observations=30)
    findings = evaluate_rules(inp)
    assert determine_status(inp, findings) is SupervisorStatus.INSUFFICIENT_DATA


# --- Scenario 7 & 8: fundamentals partial / absent -------------------------

def test_fundamentals_absent_is_informational_gap():
    inp = make_input(fundamental_label="unavailable", fundamental_score=None,
                     fundamental_metrics_used=0,
                     fundamental_raw_values=(None, None, None, None))
    finding = rule_fundamentals_gap(inp)
    assert finding.ruleId == "FUNDAMENTALS_MISSING"
    assert finding.severity is Severity.INFO
    assert finding.category is FindingCategory.DATA_GAP


def test_fundamentals_partial_is_informational_gap():
    inp = make_input(fundamental_metrics_used=2,
                     fundamental_raw_values=(0.10, None, 20.0, None))
    finding = rule_fundamentals_gap(inp)
    assert finding.ruleId == "FUNDAMENTALS_PARTIAL"
    assert "2 of 4" in finding.message


def test_complete_fundamentals_produce_no_gap():
    assert rule_fundamentals_gap(make_input()) is None


def test_missing_fundamentals_never_count_as_negative_evidence():
    inp = make_input(fundamental_label="unavailable", fundamental_score=None,
                     fundamental_metrics_used=0,
                     fundamental_raw_values=(None, None, None, None))
    findings = evaluate_rules(inp)
    assert "FUNDAMENTALS_MISSING" in rule_ids(findings)
    assert "TECHNICAL_FUNDAMENTAL_DIVERGENCE" not in rule_ids(findings)


# --- Scenario 9 & E: integrity ---------------------------------------------

@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_metrics_are_integrity_issues_not_zeros(bad):
    inp = make_input(momentum_score=bad)
    issues = integrity_issues(inp)
    assert any("not finite" in issue for issue in issues)


def test_out_of_range_score_is_reported():
    issues = integrity_issues(make_input(momentum_score=1.5))
    assert any("out of range" in issue for issue in issues)


def test_negative_volatility_is_reported():
    issues = integrity_issues(make_input(volatility=-0.1))
    assert any("volatility is negative" in issue for issue in issues)


def test_unknown_engine_recommendation_is_reported():
    issues = integrity_issues(make_input(engine_recommendation="MAYBE"))
    assert any("unknown engine recommendation" in issue for issue in issues)


def test_unavailable_component_with_sufficient_history_is_inconsistency():
    inp = make_input(trend_label="unavailable", trend_score=None,
                     short_moving_average=None, long_moving_average=None,
                     dataset=make_dataset(observations=120))
    issues = integrity_issues(inp)
    assert any("unavailable although history is sufficient" in issue for issue in issues)


def test_label_and_score_disagreement_is_reported():
    issues = integrity_issues(make_input(momentum_label="unavailable"))
    assert any("label and score disagree" in issue for issue in issues)


def test_metrics_used_must_match_present_values():
    issues = integrity_issues(make_input(fundamental_metrics_used=3))
    assert any("metricsUsed=3" in issue for issue in issues)


def test_valid_input_has_no_integrity_issues():
    assert integrity_issues(make_input()) == []
    assert integrity_issues(make_unavailable_trend(observations=30)) == []


def test_supervise_refuses_non_finite_input():
    dump = {
        "recommendation": "HOLD", "confidence": 0.5,
        "signals": {"momentum": "positive", "trend": "bullish", "risk": "low", "fundamental": "positive"},
        "analysis": {
            "momentum": {"label": "positive", "score": math.nan, "changePercent": 1.0},
            "trend": {"label": "bullish", "score": 0.1, "shortMovingAverage": 1.0,
                      "longMovingAverage": 1.0, "priceVsShortMovingAverage": 0.0,
                      "priceVsLongMovingAverage": 0.0},
            "risk": {"label": "low", "score": 0.1, "volatility": 0.1, "maxDrawdown": 0.1},
            "fundamental": {"label": "positive", "score": 0.1, "metricsUsed": 4,
                            "revenueGrowth": 0.1, "profitMargin": 0.2,
                            "peRatio": 20.0, "earningsGrowth": 0.1},
        },
    }
    from app.supervision.service import supervise

    with pytest.raises(SupervisionIntegrityError) as excinfo:
        supervise(dump, make_dataset())
    assert any("not finite" in issue for issue in excinfo.value.issues)


# --- Status precedence -----------------------------------------------------

def test_status_precedence_insufficient_beats_caution():
    # Short history AND a BUY/high-risk conflict: insufficient data wins.
    inp = replace(make_unavailable_trend(observations=30),
                  engine_recommendation="BUY", risk_label="high", risk_score=0.9)
    findings = evaluate_rules(inp)
    assert "OPPORTUNITY_RISK_CONFLICT" in rule_ids(findings)
    assert determine_status(inp, findings) is SupervisorStatus.INSUFFICIENT_DATA


def test_status_caution_when_conflict_and_evidence_sufficient():
    inp = make_input(engine_recommendation="BUY", risk_label="high", risk_score=0.8)
    assert determine_status(inp, evaluate_rules(inp)) is SupervisorStatus.CAUTION


def test_status_consistent_when_no_conflicts():
    inp = make_input()
    assert determine_status(inp, evaluate_rules(inp)) is SupervisorStatus.CONSISTENT


def test_observation_findings_do_not_change_status():
    # Low confidence is an observation only; it must not turn consistent into caution.
    inp = make_input(confidence=0.30)
    findings = evaluate_rules(inp)
    assert rule_ids(findings) == ["LOW_CONFIDENCE"]
    assert determine_status(inp, findings) is SupervisorStatus.CONSISTENT


# --- Confidence observation without double counting ------------------------

def test_low_confidence_is_suppressed_when_conflict_already_explains_it():
    inp = make_input(confidence=0.30, momentum_label="positive", momentum_score=0.5,
                     trend_label="bearish", trend_score=-0.5)
    assert "LOW_CONFIDENCE" not in rule_ids(evaluate_rules(inp))


def test_low_confidence_threshold_is_exclusive_at_0_50():
    assert "LOW_CONFIDENCE" not in rule_ids(evaluate_rules(make_input(confidence=0.50)))
    assert "LOW_CONFIDENCE" in rule_ids(evaluate_rules(make_input(confidence=0.49)))


# --- Stable, duplicate-free output ----------------------------------------

def test_findings_are_unique_and_sorted_by_severity_then_rule_id():
    inp = make_input(engine_recommendation="BUY", risk_label="high", risk_score=0.8,
                     momentum_label="positive", momentum_score=0.5,
                     trend_label="bearish", trend_score=-0.5,
                     fundamental_label="unavailable", fundamental_score=None,
                     fundamental_metrics_used=0,
                     fundamental_raw_values=(None, None, None, None),
                     confidence=0.2)
    findings = evaluate_rules(inp)
    ids = rule_ids(findings)
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids, key=lambda rid: (
        {"critical": 0, "warning": 1, "info": 2}[next(f for f in findings if f.ruleId == rid).severity.value],
        rid,
    ))


def test_evaluate_rules_is_deterministic():
    inp = make_input(momentum_label="positive", momentum_score=0.5,
                     trend_label="bearish", trend_score=-0.5)
    assert evaluate_rules(inp) == evaluate_rules(inp)


# --- Reference resolution --------------------------------------------------

def test_resolve_reference_finds_existing_paths():
    view = {"analysis": {"momentum": {"score": None}}, "dataset": {"observations": 120}}
    assert resolve_reference(view, "analysis.momentum.score")  # present, value may be null
    assert resolve_reference(view, "dataset.observations")


def test_resolve_reference_rejects_missing_paths():
    view = {"analysis": {"momentum": {"score": 0.1}}}
    assert not resolve_reference(view, "analysis.momentum.missing")
    assert not resolve_reference(view, "analysis.trend.score")

"""Aggregator tests: thresholds, renormalization, confidence and documented formulas."""

import pytest

from app.analysis.aggregate import aggregate
from app.analysis.config import BUY_THRESHOLD, SELL_THRESHOLD, WEIGHTS


def test_weights_match_the_documented_split():
    assert WEIGHTS == {"momentum": 0.30, "trend": 0.30, "risk": 0.20, "fundamental": 0.20}
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_strongly_positive_signals_produce_buy():
    result = aggregate({"momentum": 1.0, "trend": 1.0, "risk": 0.5, "fundamental": 0.8})
    assert result.recommendation == "BUY"
    assert result.composite >= BUY_THRESHOLD


def test_strongly_negative_signals_produce_sell():
    result = aggregate({"momentum": -1.0, "trend": -1.0, "risk": -0.5, "fundamental": -0.8})
    assert result.recommendation == "SELL"
    assert result.composite <= SELL_THRESHOLD


def test_mixed_signals_produce_hold():
    result = aggregate({"momentum": 0.5, "trend": -0.5, "risk": 0.0, "fundamental": 0.0})
    assert result.recommendation == "HOLD"
    assert SELL_THRESHOLD < result.composite < BUY_THRESHOLD


def test_composite_is_weighted_average():
    result = aggregate({"momentum": 1.0, "trend": 0.0, "risk": 0.0, "fundamental": 0.0})
    assert result.composite == pytest.approx(0.30, abs=1e-4)


def test_unavailable_component_is_excluded_and_weights_renormalized():
    # Without the fundamental component, the other three renormalize over 0.8.
    result = aggregate({"momentum": 1.0, "trend": 1.0, "risk": 1.0, "fundamental": None})
    assert result.composite == pytest.approx(1.0)
    assert result.missing_components == ["fundamental"]
    assert result.coverage == pytest.approx(0.8)


def test_unavailable_component_is_never_counted_as_zero():
    with_missing = aggregate({"momentum": 1.0, "trend": 1.0, "risk": None, "fundamental": None})
    assert with_missing.composite == pytest.approx(1.0)


def test_no_data_at_all_is_hold_with_zero_confidence():
    result = aggregate({"momentum": None, "trend": None, "risk": None, "fundamental": None})
    assert result.recommendation == "HOLD"
    assert result.confidence == 0.0
    assert set(result.missing_components) == set(WEIGHTS)


def test_confidence_is_coverage_times_agreement():
    result = aggregate({"momentum": 0.5, "trend": 0.5, "risk": 0.5, "fundamental": 0.5})
    assert result.agreement == pytest.approx(1.0)  # identical scores agree perfectly
    assert result.coverage == pytest.approx(1.0)
    assert result.confidence == pytest.approx(1.0)


def test_contradictory_signals_lower_confidence():
    agreeing = aggregate({"momentum": 0.5, "trend": 0.5, "risk": 0.5, "fundamental": 0.5})
    conflicting = aggregate({"momentum": 1.0, "trend": -1.0, "risk": 1.0, "fundamental": -1.0})
    assert conflicting.agreement < agreeing.agreement
    assert conflicting.confidence < agreeing.confidence


def test_aggregation_is_deterministic():
    scores = {"momentum": 0.3, "trend": -0.2, "risk": 0.1, "fundamental": 0.4}
    assert aggregate(scores) == aggregate(dict(scores))

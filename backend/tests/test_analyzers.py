"""Tests for technical, risk and fundamental analyzers."""

import pandas as pd

from app.analysis.fundamental import analyze_fundamentals
from app.analysis.risk import analyze_risk
from app.analysis.technical import analyze_momentum, analyze_trend
from app.data.provider import Fundamentals
from tests.factories import alternating_closes, rising_closes


def series(values):
    return pd.Series(values, dtype=float)


# --- Momentum -------------------------------------------------------------

def test_momentum_positive_for_rising_prices():
    result = analyze_momentum(series(rising_closes(60, start=100, step=1)))
    assert result.label == "positive"
    assert result.change_percent == round((159 / 100 - 1) * 100, 2)
    assert result.score == 1.0  # 59% change saturates the scale


def test_momentum_negative_for_falling_prices():
    result = analyze_momentum(series([100, 95, 90, 85]))
    assert result.label == "negative"
    assert result.score < 0


def test_momentum_neutral_for_small_move():
    result = analyze_momentum(series([100, 100.5, 101]))
    assert result.label == "neutral"


# --- Trend ----------------------------------------------------------------

def test_trend_bullish_when_price_and_short_average_above_long():
    result = analyze_trend(series(rising_closes(60)))
    assert result.label == "bullish"
    assert result.short_moving_average > result.long_moving_average
    assert result.price_vs_short_ma > 0


def test_trend_bearish_for_falling_series():
    result = analyze_trend(series([200 - index for index in range(60)]))
    assert result.label == "bearish"


def test_trend_unavailable_with_fewer_than_50_bars():
    assert analyze_trend(series(rising_closes(49))) is None


# --- Risk -----------------------------------------------------------------

def test_risk_flags_high_volatility_scenario():
    # TEST 2 from the spec: alternating +/-10% moves must be classified as high risk.
    result = analyze_risk(series(alternating_closes(60, swing=0.10)))
    assert result.label == "high"
    assert result.volatility > 0.60
    assert result.signal_score < 0


def test_risk_low_for_very_calm_series():
    calm = series([100 + 0.01 * (index % 2) for index in range(60)])
    result = analyze_risk(calm)
    assert result.label == "low"
    assert result.signal_score > 0


def test_risk_maximum_drawdown_reported_as_positive_magnitude():
    closes = series([100] * 10 + [50] * 10)
    result = analyze_risk(closes)
    assert result.max_drawdown == 0.5


def test_risk_unavailable_with_single_bar():
    assert analyze_risk(series([100])) is None


# --- Fundamentals ---------------------------------------------------------

def test_fundamentals_none_when_no_record():
    assert analyze_fundamentals(None) is None


def test_fundamentals_all_missing_is_unavailable_not_negative():
    empty = Fundamentals(None, None, None, None)
    assert analyze_fundamentals(empty) is None


def test_fundamentals_missing_metrics_are_excluded_from_score():
    partial = Fundamentals(revenue_growth=0.20, profit_margin=None, pe_ratio=None, earnings_growth=None)
    result = analyze_fundamentals(partial)
    assert result.metrics_used == 1
    assert result.score == 1.0  # only the revenue metric counts; missing ones add nothing
    assert result.profit_margin is None


def test_fundamentals_pe_scale_is_reversed():
    cheap = analyze_fundamentals(Fundamentals(None, None, pe_ratio=20.0, earnings_growth=None))
    expensive = analyze_fundamentals(Fundamentals(None, None, pe_ratio=60.0, earnings_growth=None))
    assert cheap.score > 0 > expensive.score


def test_fundamentals_strong_company_is_positive():
    strong = Fundamentals(revenue_growth=0.38, profit_margin=0.45, pe_ratio=44.0, earnings_growth=0.52)
    result = analyze_fundamentals(strong)
    assert result.label == "positive"
    assert result.metrics_used == 4

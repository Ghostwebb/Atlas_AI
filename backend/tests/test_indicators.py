"""Unit tests for pure indicator functions with hand-computed expectations."""

import math

import pandas as pd
import pytest

from app.analysis.indicators import (
    annualized_volatility,
    clamp,
    max_drawdown,
    period_change,
    simple_moving_average,
)


def series(values):
    return pd.Series(values, dtype=float)


def test_period_change_is_last_over_first_minus_one():
    assert period_change(series([100, 110, 90, 120])) == pytest.approx(0.20)


def test_period_change_needs_two_points():
    assert period_change(series([100])) is None
    assert period_change(series([])) is None


def test_simple_moving_average_uses_last_window():
    assert simple_moving_average(series([1, 2, 3, 4, 5]), 3) == pytest.approx(4.0)


def test_simple_moving_average_returns_none_when_history_too_short():
    assert simple_moving_average(series([1, 2]), 3) is None


def test_max_drawdown_is_peak_to_trough_magnitude():
    # Peak 100 -> trough 50 is a 50% drawdown, even though the series recovers to 75.
    assert max_drawdown(series([100, 50, 75])) == pytest.approx(0.50)


def test_max_drawdown_is_zero_for_monotonic_rise():
    assert max_drawdown(series([1, 2, 3, 4])) == pytest.approx(0.0)


def test_annualized_volatility_matches_manual_formula():
    closes = series([100, 101, 99, 102, 100])
    log_returns = [math.log(b / a) for a, b in zip(closes[:-1], closes[1:])]
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    expected = math.sqrt(variance) * math.sqrt(252)
    assert annualized_volatility(closes) == pytest.approx(expected)


def test_annualized_volatility_none_for_too_little_data():
    assert annualized_volatility(series([100, 101])) is None


@pytest.mark.parametrize(
    ("value", "expected"), [(2.0, 1.0), (-2.0, -1.0), (0.3, 0.3)]
)
def test_clamp(value, expected):
    assert clamp(value) == pytest.approx(expected)

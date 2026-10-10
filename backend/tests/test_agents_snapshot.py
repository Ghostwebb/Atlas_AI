"""Phase 7 shared snapshot: formulas, windows, minimum history, no look-ahead, non-finite values."""

import math

import numpy as np
import pytest

from app.agents.snapshot import SnapshotIntegrityError, build_agent_snapshot
from app.data.demo_provider import DemoDataProvider
from app.data.provider import Fundamentals
from tests.agents_factories import built, market_snapshot


def values(snapshot):
    return {k: m.value for k, m in snapshot.metrics.items()}


def test_returns_use_exact_windows():
    closes = [100.0 + i for i in range(61)]          # 61 bars: t-60 is the first bar
    v = values(built(closes))
    assert v["return_60d"] == round(160 / 100 - 1, 6)
    assert v["return_20d"] == round(160 / 140 - 1, 6)


def test_minimum_history_returns_none_not_zero():
    v = values(built([100.0 + i for i in range(60)]))  # 60 bars: return_60d needs 61
    assert v["return_60d"] is None and v["return_20d"] is not None and v["sma50"] is not None
    v = values(built([100.0] * 20))                     # 20 bars
    assert v["return_20d"] is None and v["volatility_annualized"] is None and v["max_drawdown"] is None
    assert v["volume_ratio_20_60"] is None and v["sma50"] is None and v["sma20"] == 100.0
    v = values(built([100.0]))
    assert v["price_last"] == 100.0 and all(v[k] is None for k in v if k not in ("price_last",)
                                            and k not in ("revenue_growth", "earnings_growth", "profit_margin",
                                                          "pe_ratio"))


def test_moving_averages_and_alignment():
    closes = [100.0] * 30 + [110.0] * 20               # SMA20 = 110, SMA50 = 104
    v = values(built(closes))
    assert v["sma20"] == 110.0 and v["sma50"] == 104.0
    assert v["price_vs_sma20"] == 0.0 and v["sma20_vs_sma50"] == round(110 / 104 - 1, 6)


def test_volatility_and_drawdowns_match_hand_computation():
    closes = [100, 102, 99, 105, 101, 97, 103, 108, 104, 100, 98, 101, 106, 110, 107, 103, 100, 104, 109, 112, 108]
    v = values(built([float(c) for c in closes]))
    logs = np.diff(np.log(np.array(closes, dtype=float)))
    assert v["volatility_annualized"] == round(float(np.std(logs, ddof=1)) * math.sqrt(252), 6)
    assert v["volatility_20d"] == v["volatility_annualized"]       # exactly 20 returns
    assert v["max_drawdown"] == round(1 - 98 / 108, 6)   # peak 108, trough 98
    assert v["current_drawdown"] == round(1 - 108 / 112, 6)


def test_volume_ratio():
    volumes = [1000] * 40 + [2000] * 20
    v = values(built([100.0] * 60, volumes))
    assert v["volume_ratio_20_60"] == round(2000 / ((40 * 1000 + 20 * 2000) / 60), 6)


def test_no_look_ahead_metrics_anchor_on_last_bar_only():
    closes = [100.0 + i for i in range(80)]
    past = values(built(closes[:70]))
    with_future = values(built(closes))
    assert past != with_future
    # Recomputing on the truncated series gives exactly the truncated snapshot (only bars <= t used).
    assert past["return_20d"] == round(closes[69] / closes[49] - 1, 6)
    # Earlier history outside a window does not change that window's metric.
    shifted = values(built([1.0] * 30 + closes[:70]))
    assert shifted["return_20d"] == past["return_20d"] and shifted["sma50"] == past["sma50"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_fundamentals_become_missing(bad):
    snap = built([100.0] * 70, fundamentals=Fundamentals(revenue_growth=bad, profit_margin=0.1, pe_ratio=bad,
                                                          earnings_growth=0.05))
    v = values(snap)
    assert v["revenue_growth"] is None and v["pe_ratio"] is None and v["profit_margin"] == 0.1


def test_non_positive_prices_do_not_produce_infinities():
    v = values(built([100.0] * 30 + [0.0] + [100.0] * 30))
    assert v["volatility_annualized"] is None and v["max_drawdown"] is None and v["current_drawdown"] is None
    assert all(x is None or math.isfinite(x) for x in v.values())


def test_scales_and_units():
    snap = build_agent_snapshot(DemoDataProvider().get_snapshot("NVDA"))
    m = snap.metrics
    assert m["revenue_growth"].value == 0.38 and m["revenue_growth"].unit == "decimal"   # 38%, not 38
    assert m["pe_ratio"].unit == "multiple" and m["sma20"].unit == "usd"
    assert m["volume_ratio_20_60"].unit == "ratio" and m["pe_ratio"].window is None


def test_synthetic_provenance_and_undated_fundamentals_warning():
    snap = build_agent_snapshot(DemoDataProvider().get_snapshot("AAPL"))
    assert snap.provenance == "synthetic" and snap.is_simulated and snap.observations == 120
    assert snap.last_date == "2026-09-30" and any("undated" in w for w in snap.warnings)


def test_unknown_data_source_is_an_integrity_error():
    market = market_snapshot([100.0] * 30)
    market = market.__class__(**{**market.__dict__, "data_source": "mystery"})
    with pytest.raises(SnapshotIntegrityError):
        build_agent_snapshot(market)


def test_no_fundamentals():
    v = values(built([100.0] * 70, fundamentals=None))
    assert all(v[k] is None for k in ("revenue_growth", "earnings_growth", "profit_margin", "pe_ratio"))

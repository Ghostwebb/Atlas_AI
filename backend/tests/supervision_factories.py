"""Controlled SupervisionInput builders. Overrides force specific scenarios."""

from dataclasses import replace

from app.supervision.models import DatasetInfo, SupervisionInput


def make_dataset(observations: int = 120, provenance: str = "synthetic") -> DatasetInfo:
    return DatasetInfo(
        observations=observations,
        requiredObservations=50,
        firstDate="2026-04-16",
        lastDate="2026-09-30",
        provenance=provenance,
        dataSource="demo_dataset",
    )


def make_input(**overrides) -> SupervisionInput:
    """A fully available, internally consistent case with neutral signals."""
    base = SupervisionInput(
        engine_recommendation="HOLD",
        confidence=0.80,
        momentum_label="neutral",
        momentum_score=0.0,
        momentum_change_percent=0.5,
        trend_label="neutral",
        trend_score=0.0,
        short_moving_average=100.0,
        long_moving_average=100.0,
        risk_label="moderate",
        risk_score=0.5,
        volatility=0.30,
        max_drawdown=0.10,
        fundamental_label="neutral",
        fundamental_score=0.0,
        fundamental_metrics_used=4,
        fundamental_raw_values=(0.10, 0.20, 25.0, 0.10),
        dataset=make_dataset(),
    )
    return replace(base, **overrides)


def make_unavailable_trend(observations: int = 30) -> SupervisionInput:
    """Trend unavailable because history is short (an expected absence)."""
    return make_input(
        trend_label="unavailable",
        trend_score=None,
        short_moving_average=None,
        long_moving_average=None,
        dataset=make_dataset(observations=observations),
    )

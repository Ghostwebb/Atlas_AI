"""Data quality, coverage counts, limitations and provenance checks."""

import pytest

from app.supervision.models import (
    Provenance,
    QualityLabel,
    SupervisionIntegrityError,
    SupervisorStatus,
)
from app.supervision.quality import build_data_quality, build_limitations
from app.supervision.service import supervise
from tests.supervision_factories import make_dataset, make_input, make_unavailable_trend


def test_full_coverage_is_sufficient():
    quality = build_data_quality(make_input(), SupervisorStatus.CONSISTENT)
    assert quality.label is QualityLabel.SUFFICIENT
    assert quality.componentCoverage == 1.0
    assert quality.fundamentalCoverage == 1.0
    assert quality.missingComponents == []


def test_partial_fundamentals_give_exact_coverage_and_limited_label():
    inp = make_input(fundamental_metrics_used=2, fundamental_raw_values=(0.10, None, 20.0, None))
    quality = build_data_quality(inp, SupervisorStatus.CONSISTENT)
    assert quality.availableFundamentalMetrics == 2
    assert quality.expectedFundamentalMetrics == 4
    assert quality.fundamentalCoverage == 0.5
    assert quality.label is QualityLabel.LIMITED


def test_insufficient_status_always_yields_insufficient_label():
    inp = make_unavailable_trend(observations=30)
    quality = build_data_quality(inp, SupervisorStatus.INSUFFICIENT_DATA)
    assert quality.label is QualityLabel.INSUFFICIENT
    assert quality.requiredHistoricalObservations == 50
    assert quality.historicalObservations == 30


def test_unavailable_component_is_listed_as_missing_not_scored():
    inp = make_unavailable_trend(observations=30)
    quality = build_data_quality(inp, SupervisorStatus.INSUFFICIENT_DATA)
    assert "trend" in quality.missingComponents
    assert "trend" not in quality.availableComponents
    assert quality.componentCoverage == 0.75


def test_synthetic_provenance_adds_synthetic_limitation_and_non_predictive_note():
    inp = make_input()
    quality = build_data_quality(inp, SupervisorStatus.CONSISTENT)
    codes = [item.code for item in build_limitations(inp, quality)]
    assert quality.provenance is Provenance.SYNTHETIC
    assert "SYNTHETIC_DATA" in codes
    assert "NON_PREDICTIVE" in codes


def test_missing_fundamentals_limitation():
    inp = make_input(fundamental_label="unavailable", fundamental_score=None,
                     fundamental_metrics_used=0,
                     fundamental_raw_values=(None, None, None, None))
    quality = build_data_quality(inp, SupervisorStatus.CONSISTENT)
    assert "FUNDAMENTALS_MISSING" in [item.code for item in build_limitations(inp, quality)]


def test_partial_fundamentals_limitation():
    inp = make_input(fundamental_metrics_used=1, fundamental_raw_values=(0.10, None, None, None))
    quality = build_data_quality(inp, SupervisorStatus.CONSISTENT)
    assert "FUNDAMENTALS_PARTIAL" in [item.code for item in build_limitations(inp, quality)]


def test_complete_fundamentals_have_no_fundamental_limitation():
    inp = make_input()
    quality = build_data_quality(inp, SupervisorStatus.CONSISTENT)
    codes = [item.code for item in build_limitations(inp, quality)]
    assert "FUNDAMENTALS_MISSING" not in codes
    assert "FUNDAMENTALS_PARTIAL" not in codes


def test_provenance_mismatch_is_an_integrity_error():
    # A dataset claiming "live" for the synthetic demo source must be refused.
    dataset = make_dataset().model_copy(update={"provenance": Provenance.LIVE})
    dump = {"recommendation": "HOLD", "confidence": 0.5, "signals": {}, "analysis": {}}
    with pytest.raises(SupervisionIntegrityError) as excinfo:
        supervise(dump, dataset)
    assert any("does not match" in issue for issue in excinfo.value.issues)

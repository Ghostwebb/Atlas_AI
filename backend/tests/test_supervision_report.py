"""Deterministic report wording: headlines, neutral language, no timestamps."""

import re

from app.supervision.models import SupervisorStatus
from app.supervision.quality import build_data_quality
from app.supervision.report import build_report
from app.supervision.rules import evaluate_rules
from app.supervision.evidence import build_evidence
from tests.supervision_factories import make_input, make_unavailable_trend

FORBIDDEN_WORDS = ("news", "guarantee", "will rise", "will fall", "predict", "sure to", "buy now")


def _report_for(inp, status):
    findings = evaluate_rules(inp)
    supporting, opposing = build_evidence(inp)
    quality = build_data_quality(inp, status)
    return build_report(inp.engine_recommendation, status, findings, supporting, opposing, quality)


def _all_text(report):
    parts = [report.headline, report.summary]
    parts += report.keyReasons + report.riskFactors + report.dataGaps
    return " ".join(parts).lower()


def test_insufficient_status_headline():
    inp = make_unavailable_trend(observations=30)
    report = _report_for(inp, SupervisorStatus.INSUFFICIENT_DATA)
    assert report.headline == "Insufficient evidence for a reliable demo report"


def test_caution_headline_mentions_conflicts():
    inp = make_input(engine_recommendation="BUY", risk_label="high", risk_score=0.8)
    report = _report_for(inp, SupervisorStatus.CAUTION)
    assert report.headline.endswith("conflicts that require caution")
    assert report.headline.startswith("Favorable")


def test_consistent_headline_for_neutral_hold():
    inp = make_input()
    report = _report_for(inp, SupervisorStatus.CONSISTENT)
    assert report.headline == "Mixed or neutral demo signals, internally consistent"


def test_report_is_deterministic_for_identical_input():
    inp = make_input(engine_recommendation="BUY", risk_label="high", risk_score=0.8)
    first = _report_for(inp, SupervisorStatus.CAUTION)
    second = _report_for(inp, SupervisorStatus.CAUTION)
    assert first == second


def test_summary_states_synthetic_basis():
    report = _report_for(make_input(), SupervisorStatus.CONSISTENT)
    assert "synthetic demo data" in report.summary


def test_report_contains_no_timestamps():
    inp = make_input(engine_recommendation="BUY", risk_label="high", risk_score=0.8)
    text = _all_text(_report_for(inp, SupervisorStatus.CAUTION))
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
    assert not re.search(r"\d{2}:\d{2}", text)


def test_report_avoids_speculative_or_news_language():
    inp = make_input(engine_recommendation="BUY", risk_label="high", risk_score=0.8,
                     momentum_label="positive", momentum_score=0.5,
                     trend_label="bearish", trend_score=-0.5)
    text = _all_text(_report_for(inp, SupervisorStatus.CAUTION))
    for word in FORBIDDEN_WORDS:
        assert word not in text, word


def test_data_gaps_list_missing_components():
    inp = make_unavailable_trend(observations=30)
    report = _report_for(inp, SupervisorStatus.INSUFFICIENT_DATA)
    assert any("trend" in gap for gap in report.dataGaps)

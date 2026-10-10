"""Supervisor orchestration. Consumes computed results; never fetches data or recomputes indicators.

Status precedence (first match wins):
    1. insufficient_data  - a core technical component is missing, or history is short
    2. caution            - a contradiction or caution finding exists
    3. consistent         - none of the above
"""

from typing import Any

from app.supervision.config import (
    POLICY_VERSION,
    PROVENANCE_BY_DATA_SOURCE,
    SCHEMA_VERSION,
)
from app.supervision.evidence import build_evidence
from app.supervision.models import (
    DatasetInfo,
    Finding,
    FindingCategory,
    SupervisionIntegrityError,
    SupervisionInput,
    SupervisionReport,
    SupervisorStatus,
)
from app.supervision.quality import build_data_quality, build_limitations, core_components_missing
from app.supervision.report import build_report
from app.supervision.rules import evaluate_rules, integrity_issues


def resolve_reference(view: dict[str, Any], ref: str) -> bool:
    """True if a dotted path such as 'analysis.momentum.score' exists in `view`."""
    node: Any = view
    for part in ref.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def collect_references(report: SupervisionReport) -> list[str]:
    """All references cited by findings and evidence, in report order."""
    refs = [ref for f in report.findings for ref in f.evidenceRefs]
    for item in report.supportingEvidence + report.opposingEvidence + report.neutralEvidence:
        refs += item.refs
    return refs


def validate_references(public_response: dict[str, Any], report: SupervisionReport) -> None:
    """Every reference must resolve in the public JSON the client receives.

    `public_response` is the JSON-mode dump of the analysis response. The view
    adds only the serialized supervision block itself, which is exactly what the
    HTTP response will contain. No internal objects are added.
    """
    view = {**public_response, "supervision": report.model_dump(mode="json")}
    unresolved = [ref for ref in collect_references(report) if not resolve_reference(view, ref)]
    if unresolved:
        raise SupervisionIntegrityError(
            [f"unresolved evidence reference: {ref}" for ref in unresolved]
        )


def build_input(response_dump: dict[str, Any], dataset: DatasetInfo) -> SupervisionInput:
    """Map an already-computed analysis (as a dict) to the supervisor's input view."""
    analysis = response_dump["analysis"]
    signals = response_dump["signals"]
    momentum = analysis["momentum"]
    trend = analysis["trend"]
    risk = analysis["risk"]
    fundamental = analysis["fundamental"]

    return SupervisionInput(
        engine_recommendation=response_dump["recommendation"],
        confidence=response_dump["confidence"],
        momentum_label=signals["momentum"],
        momentum_score=momentum["score"],
        momentum_change_percent=momentum["changePercent"],
        trend_label=signals["trend"],
        trend_score=trend["score"],
        short_moving_average=trend["shortMovingAverage"],
        long_moving_average=trend["longMovingAverage"],
        risk_label=signals["risk"],
        risk_score=risk["score"],
        volatility=risk["volatility"],
        max_drawdown=risk["maxDrawdown"],
        fundamental_label=signals["fundamental"],
        fundamental_score=fundamental["score"],
        fundamental_metrics_used=fundamental["metricsUsed"],
        fundamental_raw_values=(
            fundamental["revenueGrowth"],
            fundamental["profitMargin"],
            fundamental["peRatio"],
            fundamental["earningsGrowth"],
        ),
        dataset=dataset,
        price_vs_short_ma=trend["priceVsShortMovingAverage"],
    )


def determine_status(inp: SupervisionInput, findings: list[Finding]) -> SupervisorStatus:
    if core_components_missing(inp) or inp.dataset.observations < inp.dataset.requiredObservations:
        return SupervisorStatus.INSUFFICIENT_DATA
    if any(f.category in (FindingCategory.CONTRADICTION, FindingCategory.CAUTION) for f in findings):
        return SupervisorStatus.CAUTION
    return SupervisorStatus.CONSISTENT


def supervise(response_dump: dict[str, Any], dataset: DatasetInfo) -> SupervisionReport:
    """Build the supervision report from an analysis result.

    `response_dump` must be the JSON-mode dump of the public analysis response
    (`AnalyzeResponse.model_dump(mode="json")`). `dataset` is used for the rules
    and for the published dataQuality fields only; it is never a reference target.
    Raises SupervisionIntegrityError if inputs are invalid or references do not resolve.
    """
    if dataset.provenance.value != PROVENANCE_BY_DATA_SOURCE.get(dataset.dataSource):
        raise SupervisionIntegrityError(
            [f"provenance {dataset.provenance.value} does not match source {dataset.dataSource}"]
        )

    inp = build_input(response_dump, dataset)

    issues = integrity_issues(inp)
    if issues:
        raise SupervisionIntegrityError(issues)

    findings = evaluate_rules(inp)
    supporting, opposing, neutral = build_evidence(inp)
    status = determine_status(inp, findings)
    quality = build_data_quality(inp, status)
    limitations = build_limitations(inp, quality)
    report = build_report(inp, status, findings, supporting, opposing, neutral, quality)

    supervision = SupervisionReport(
        schemaVersion=SCHEMA_VERSION,
        policyVersion=POLICY_VERSION,
        status=status,
        engineRecommendation=inp.engine_recommendation,
        dataQuality=quality,
        findings=findings,
        supportingEvidence=supporting,
        opposingEvidence=opposing,
        neutralEvidence=neutral,
        limitations=limitations,
        report=report,
    )
    validate_references(response_dump, supervision)
    return supervision

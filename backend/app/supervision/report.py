"""Deterministic report text built from structured results.

Templates only. No timestamps, no random IDs, no language model. Every sentence
maps to a finding, an evidence item, a missing component or a limitation.
"""

from app.supervision.models import (
    DataQuality,
    EvidenceItem,
    Finding,
    FindingCategory,
    Report,
    SupervisorStatus,
)

_RECOMMENDATION_PHRASE = {
    "BUY": "Favorable",
    "HOLD": "Mixed or neutral",
    "SELL": "Unfavorable",
}


def build_report(
    engine_recommendation: str,
    status: SupervisorStatus,
    findings: list[Finding],
    supporting: list[EvidenceItem],
    opposing: list[EvidenceItem],
    quality: DataQuality,
) -> Report:
    phrase = _RECOMMENDATION_PHRASE.get(engine_recommendation, "Unclassified")

    if status is SupervisorStatus.INSUFFICIENT_DATA:
        headline = "Insufficient evidence for a reliable demo report"
    elif status is SupervisorStatus.CAUTION:
        headline = f"{phrase} demo signals with conflicts that require caution"
    else:
        headline = f"{phrase} demo signals, internally consistent"

    warnings = sum(1 for f in findings if f.severity.value == "warning")
    informational = len(findings) - warnings
    summary = (
        f"Engine recommendation {engine_recommendation} on synthetic demo data. "
        f"Supervisor status: {status.value}. "
        f"{len(findings)} finding(s): {warnings} warning(s), {informational} informational. "
        "Results describe the synthetic demo dataset, not real market prices."
    )

    key_reasons = [item.description for item in supporting]

    risk_factors = [item.description for item in opposing]
    risk_factors += [
        f.message for f in findings if f.category in (FindingCategory.CONTRADICTION, FindingCategory.CAUTION)
    ]

    data_gaps = [f.message for f in findings if f.category is FindingCategory.DATA_GAP]
    if quality.missingComponents:
        data_gaps.append("Components without data: " + ", ".join(quality.missingComponents) + ".")

    return Report(
        headline=headline,
        summary=summary,
        keyReasons=key_reasons,
        riskFactors=risk_factors,
        dataGaps=data_gaps,
    )

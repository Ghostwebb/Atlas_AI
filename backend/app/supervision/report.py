"""Deterministic report text built from structured results.

Templates only. No timestamps, no random IDs, no language model. Every sentence
maps to a finding, an evidence item, a missing component or a limitation.
Provenance wording is derived from DataQuality.provenance.

- keyReasons   : reasons that support the recommendation (supporting evidence).
                 For a HOLD with offsetting signals, an explicit offset sentence first.
- counterpoints: signals that point against the recommendation (opposing
                 directional evidence). Risk is not a counterpoint.
- riskFactors  : high historical risk (for any recommendation) plus
                 contradiction and caution findings.
- dataGaps     : data-gap findings and components without data.
"""

from app.supervision.evidence import DIRECTIONAL_COMPONENTS, hold_has_offsetting_signals
from app.supervision.models import (
    DataQuality,
    EvidenceItem,
    Finding,
    FindingCategory,
    Polarity,
    Provenance,
    Report,
    SupervisionInput,
    SupervisorStatus,
)

_RECOMMENDATION_PHRASE = {
    "BUY": "Favorable",
    "HOLD": "Mixed or neutral",
    "SELL": "Unfavorable",
}

# provenance -> (headline qualifier, source phrase, closing sentence)
_PROVENANCE_WORDING: dict[Provenance, tuple[str, str, str]] = {
    Provenance.SYNTHETIC: (
        "demo ",
        "synthetic demo data",
        "Results describe the synthetic demo dataset, not real market prices.",
    ),
    Provenance.HISTORICAL: (
        "",
        "historical market data",
        "Results describe past market data and do not predict future prices.",
    ),
    Provenance.LIVE: (
        "",
        "recent market data",
        "Results describe recent market data and do not predict future prices.",
    ),
}


def provenance_wording(provenance: Provenance) -> tuple[str, str, str]:
    return _PROVENANCE_WORDING[provenance]


def _names(items: list[EvidenceItem], polarity: Polarity) -> str:
    return ", ".join(
        item.component for item in items
        if item.polarity is polarity and item.component in DIRECTIONAL_COMPONENTS
    )


def build_report(
    inp: SupervisionInput,
    status: SupervisorStatus,
    findings: list[Finding],
    supporting: list[EvidenceItem],
    opposing: list[EvidenceItem],
    neutral: list[EvidenceItem],
    quality: DataQuality,
) -> Report:
    recommendation = inp.engine_recommendation
    phrase = _RECOMMENDATION_PHRASE.get(recommendation, "Unclassified")
    qualifier, source_phrase, closing = provenance_wording(quality.provenance)

    if status is SupervisorStatus.INSUFFICIENT_DATA:
        headline = f"Insufficient evidence for a reliable {qualifier}report"
    elif status is SupervisorStatus.CAUTION:
        headline = f"{phrase} {qualifier}signals with conflicts that require caution"
    else:
        headline = f"{phrase} {qualifier}signals, internally consistent"

    warnings = sum(1 for f in findings if f.severity.value == "warning")
    informational = len(findings) - warnings
    summary = (
        f"Engine recommendation {recommendation} on {source_phrase}. "
        f"Supervisor status: {status.value}. "
        f"{len(findings)} finding(s): {warnings} warning(s), {informational} informational. "
        f"{closing}"
    )

    key_reasons: list[str] = []
    if recommendation == "HOLD" and hold_has_offsetting_signals(inp):
        key_reasons.append(
            f"Favorable signals ({_names(supporting, Polarity.FAVORABLE)}) and unfavorable "
            f"signals ({_names(supporting, Polarity.UNFAVORABLE)}) offset each other."
        )
    key_reasons += [item.description for item in supporting]

    counterpoints = [item.description for item in opposing if item.component != "risk"]

    risk_factors = [
        item.description
        for item in supporting + opposing + neutral
        if item.component == "risk" and item.polarity is Polarity.UNFAVORABLE
    ]
    risk_factors += [
        f.message for f in findings
        if f.category in (FindingCategory.CONTRADICTION, FindingCategory.CAUTION)
    ]

    data_gaps = [f.message for f in findings if f.category is FindingCategory.DATA_GAP]
    if quality.missingComponents:
        data_gaps.append("Components without data: " + ", ".join(quality.missingComponents) + ".")

    return Report(
        headline=headline,
        summary=summary,
        keyReasons=key_reasons,
        counterpoints=counterpoints,
        riskFactors=risk_factors,
        dataGaps=data_gaps,
    )

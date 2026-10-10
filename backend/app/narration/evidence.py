"""Bounded evidence packet built only from the validated analysis and supervision.

Stable evidence IDs:
  component ids    momentum, trend, risk, fundamental
  recommendation   the engine recommendation and confidence
  supervisor       the supervisor status
  holdOffset       HOLD with offsetting signals (when present)
  dataQuality      components without data
  finding.<RULE>   a supervisor finding, e.g. finding.HISTORY_INSUFFICIENT
  limitation.<CODE> a limitation, e.g. limitation.SYNTHETIC_DATA

Each output section has "anchors": the IDs a point in that section must cite at
least one of, and that the section must cover in full. This is how the backend
checks that the narrative keeps the supervisor's classification and loses no
evidence. No price rows, configuration or URLs are included.
"""

from app.narration.config import MAX_PACKET_CHARS
from app.narration.models import EvidencePacket, PacketItem, PacketMetric
from app.schemas import AnalyzeResponse
from app.supervision.evidence import DIRECTIONAL_COMPONENTS

OUTPUT_SECTIONS = ("supportingReasons", "counterpoints", "riskFactors", "dataGaps", "limitations")
_PACKET_SECTION = {
    "supportingReasons": "supporting",
    "counterpoints": "counterpoint",
    "riskFactors": "risk",
    "dataGaps": "dataGap",
    "limitations": "limitation",
}

CONFIDENCE_MEANING = (
    "Confidence = data coverage x agreement between signals. "
    "It is not a probability of return or of being correct."
)
STATUS_MEANING = {
    "consistent": "No internal contradictions were found. This is not a forecast.",
    "caution": "Signals conflict, or a favorable signal coexists with material risk.",
    "insufficient_data": "There is not enough evidence for a reliable report.",
}


class PacketTooLargeError(ValueError):
    pass


def finding_id(rule_id: str) -> str:
    return f"finding.{rule_id}"


def limitation_id(code: str) -> str:
    return f"limitation.{code}"


def hold_offset_present(analysis: AnalyzeResponse) -> bool:
    s = analysis.supervision
    polarities = {i.polarity.value for i in s.supportingEvidence if i.component in DIRECTIONAL_COMPONENTS}
    return analysis.recommendation == "HOLD" and {"favorable", "unfavorable"} <= polarities


def _metrics(analysis: AnalyzeResponse) -> list[PacketMetric]:
    a = analysis.analysis
    rows = [
        ("momentum.changePercent", "momentum", "Period change", a.momentum.changePercent, "percent"),
        ("trend.shortMovingAverage", "trend", "20-day simple moving average", a.trend.shortMovingAverage, "price"),
        ("trend.longMovingAverage", "trend", "50-day simple moving average", a.trend.longMovingAverage, "price"),
        ("trend.priceVsShortMovingAverage", "trend", "Price vs 20-day average", a.trend.priceVsShortMovingAverage, "ratio"),
        ("risk.volatility", "risk", "Annualized volatility", a.risk.volatility, "ratio"),
        ("risk.maxDrawdown", "risk", "Maximum drawdown (magnitude)", a.risk.maxDrawdown, "ratio"),
        ("fundamental.revenueGrowth", "fundamental", "Revenue growth", a.fundamental.revenueGrowth, "ratio"),
        ("fundamental.profitMargin", "fundamental", "Profit margin", a.fundamental.profitMargin, "ratio"),
        ("fundamental.peRatio", "fundamental", "Price/earnings", a.fundamental.peRatio, "multiple"),
        ("fundamental.earningsGrowth", "fundamental", "Earnings growth", a.fundamental.earningsGrowth, "ratio"),
    ]
    return [
        PacketMetric(id=mid, evidenceId=eid, name=name, value=value, unit=unit)
        for mid, eid, name, value, unit in rows
    ]


def build_packet(analysis: AnalyzeResponse) -> EvidencePacket:
    s = analysis.supervision
    if s is None:
        raise ValueError("analysis has no supervision block")
    items: list[PacketItem] = [
        PacketItem(
            id="recommendation", section="context", polarity=None,
            text=f"Engine recommendation {analysis.recommendation}, confidence {analysis.confidence:.2f}.",
        ),
        PacketItem(id="supervisor", section="context", polarity=None,
                   text=f"Supervisor status {s.status.value}. {STATUS_MEANING[s.status.value]}"),
    ]

    if hold_offset_present(analysis):
        items.append(PacketItem(id="holdOffset", section="supporting", polarity=None,
                                text=s.report.keyReasons[0]))
    for item in s.supportingEvidence:
        items.append(PacketItem(id=item.component, section="supporting",
                                polarity=item.polarity.value, text=item.description))
    for item in s.opposingEvidence:
        section = "risk" if item.component == "risk" else "counterpoint"
        items.append(PacketItem(id=item.component, section=section,
                                polarity=item.polarity.value, text=item.description))
    for item in s.neutralEvidence:
        section = "risk" if item.component == "risk" and item.polarity.value == "unfavorable" else "context"
        items.append(PacketItem(id=item.component, section=section,
                                polarity=item.polarity.value, text=item.description))

    for finding in s.findings:
        section = {
            "contradiction": "risk",
            "caution": "risk",
            "data_gap": "dataGap",
            "observation": "limitation",
        }[finding.category.value]
        items.append(PacketItem(id=finding_id(finding.ruleId), section=section,
                                polarity=None, text=finding.message))
    if s.dataQuality.missingComponents:
        items.append(PacketItem(
            id="dataQuality", section="dataGap", polarity=None,
            text="Components without data: " + ", ".join(s.dataQuality.missingComponents) + ".",
        ))
    for limitation in s.limitations:
        items.append(PacketItem(id=limitation_id(limitation.code), section="limitation",
                                polarity=None, text=limitation.message))

    packet = EvidencePacket(
        symbol=analysis.symbol,
        companyName=analysis.companyName,
        recommendation=analysis.recommendation,
        confidence=analysis.confidence,
        confidenceMeaning=CONFIDENCE_MEANING,
        supervisorStatus=s.status.value,
        supervisorStatusMeaning=STATUS_MEANING[s.status.value],
        provenance=s.dataQuality.provenance.value,
        isSimulated=analysis.isSimulated,
        firstDate=s.dataQuality.firstDate,
        lastDate=s.dataQuality.lastDate,
        componentCoverage=s.dataQuality.componentCoverage,
        fundamentalCoverage=s.dataQuality.fundamentalCoverage,
        metrics=_metrics(analysis),
        items=items,
    )
    if len(packet.model_dump_json()) > MAX_PACKET_CHARS:
        raise PacketTooLargeError("evidence packet exceeds the size limit")
    return packet


def all_ids(packet: EvidencePacket) -> set[str]:
    return {item.id for item in packet.items}


def anchors(packet: EvidencePacket) -> dict[str, list[str]]:
    """Output section -> IDs it must cite (stable order, no duplicates)."""
    result: dict[str, list[str]] = {}
    for section in OUTPUT_SECTIONS:
        wanted = _PACKET_SECTION[section]
        ids: list[str] = []
        for item in packet.items:
            if item.section == wanted and item.id not in ids:
                ids.append(item.id)
        result[section] = ids
    return result

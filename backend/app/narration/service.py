"""Narrative orchestration: deterministic analysis -> packet -> model -> validation -> report.

A model failure never blocks the analysis: it yields the deterministic fallback
with a reason code. A supervision integrity error still propagates (HTTP 500).
"""

from app.analysis.service import analyze_symbol
from app.data.provider import MarketDataProvider
from app.narration.client import LMStudioClient, NarrationError
from app.narration.config import NARRATION_SCHEMA_VERSION, PROMPT_VERSION, NarrationSettings
from app.narration.evidence import build_packet
from app.narration.fallback import build_fallback
from app.narration.models import (
    Narrative,
    NarrativeFacts,
    NarrativeReason,
    NarrativeReport,
    NarrativeStatus,
    ReasonCode,
    ReportResponse,
)
from app.narration.prompts import build_messages
from app.narration.validation import InvalidNarrativeError, parse_model_content, validate_narrative
from app.schemas import AnalyzeResponse

REASON_MESSAGES = {
    ReasonCode.MODEL_DISABLED: "Model narration is disabled; the deterministic report is shown.",
    ReasonCode.MODEL_UNAVAILABLE: "The local model is unavailable; the deterministic report is shown.",
    ReasonCode.MODEL_TIMEOUT: "The local model did not answer in time; the deterministic report is shown.",
    ReasonCode.MODEL_BUSY: "The local model is busy with another report; the deterministic report is shown.",
    ReasonCode.INVALID_MODEL_OUTPUT: "The model output failed validation; the deterministic report is shown.",
}


def _facts(analysis: AnalyzeResponse) -> NarrativeFacts:
    s = analysis.supervision
    return NarrativeFacts(
        recommendation=analysis.recommendation,
        confidence=analysis.confidence,
        supervisorStatus=s.status.value,
        provenance=s.dataQuality.provenance.value,
        isSimulated=analysis.isSimulated,
        dataAsOf=analysis.dataAsOf,
    )


def _narrative(analysis, language, status, report: NarrativeReport, model=None, code=None) -> Narrative:
    return Narrative(
        schemaVersion=NARRATION_SCHEMA_VERSION,
        promptVersion=PROMPT_VERSION,
        supervisorPolicyVersion=analysis.supervision.policyVersion,
        status=status,
        generationMode="llm" if status is NarrativeStatus.GENERATED else "deterministic",
        model=model,
        language=language,
        reason=NarrativeReason(code=code, message=REASON_MESSAGES[code]) if code else None,
        facts=_facts(analysis),
        report=report,
    )


def narrate(analysis: AnalyzeResponse, language: str, settings: NarrationSettings,
            client: LMStudioClient | None) -> Narrative:
    if not settings.enabled or client is None:
        return _narrative(analysis, language, NarrativeStatus.DISABLED,
                          build_fallback(analysis, language), code=ReasonCode.MODEL_DISABLED)

    packet = build_packet(analysis)
    try:
        content = client.complete(build_messages(packet, language))
        report = validate_narrative(parse_model_content(content), packet, language, mode="llm")
    except NarrationError as error:
        code = error.code
    except InvalidNarrativeError:
        code = ReasonCode.INVALID_MODEL_OUTPUT
    else:
        return _narrative(analysis, language, NarrativeStatus.GENERATED, report, model=client.model)

    return _narrative(analysis, language, NarrativeStatus.FALLBACK,
                      build_fallback(analysis, language), code=code)


def build_report_response(symbol: str, language: str, provider: MarketDataProvider,
                          settings: NarrationSettings, client: LMStudioClient | None) -> ReportResponse | None:
    analysis = analyze_symbol(symbol, provider)  # integrity errors propagate
    if analysis is None:
        return None
    return ReportResponse(analysis=analysis, narrative=narrate(analysis, language, settings, client))

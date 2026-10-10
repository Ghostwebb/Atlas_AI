"""Deterministic narrative built from the supervisor output, in es or en.

Used when generation is disabled, LM Studio is unavailable, busy or times out,
or the model output is invalid. Same analysis + language + policy -> same text.
Numbers come from the backend analysis. It is never presented as model output.
"""

from app.analysis.config import LONG_MA_WINDOW, SHORT_MA_WINDOW, WEIGHTS
from app.narration.evidence import anchors, build_packet
from app.narration.models import NarrativePoint, NarrativeReport, OverviewPoint
from app.schemas import AnalyzeResponse
from app.supervision.config import CONFIDENCE_LOW_THRESHOLD, EXPECTED_FUNDAMENTAL_METRICS

_LABELS_ES = {
    "momentum": {"positive": "positivo", "negative": "negativo", "neutral": "neutral"},
    "trend": {"bullish": "alcista", "bearish": "bajista", "neutral": "neutral"},
    "risk": {"low": "bajo", "moderate": "moderado", "high": "alto"},
    "fundamental": {"positive": "positivos", "negative": "negativos", "neutral": "neutrales"},
}
_COMPONENT_ES = {"momentum": "momentum", "trend": "tendencia", "risk": "riesgo",
                 "fundamental": "fundamentales"}
_STATUS = {
    "en": {"consistent": "consistent (no internal contradictions; not a forecast)",
           "caution": "caution (conflicting signals or material risk)",
           "insufficient_data": "insufficient data"},
    "es": {"consistent": "coherente (sin contradicciones internas; no es una previsión)",
           "caution": "precaución (señales en conflicto o riesgo relevante)",
           "insufficient_data": "datos insuficientes"},
}
_PROVENANCE = {
    "en": {"synthetic": "The data is a synthetic demo dataset, not real market prices.",
           "historical": "The data is historical market data and does not predict future prices.",
           "live": "The data is recent market data and does not predict future prices."},
    "es": {"synthetic": "Los datos son un conjunto sintético de demostración, no precios reales de mercado.",
           "historical": "Los datos son históricos de mercado y no predicen precios futuros.",
           "live": "Los datos son recientes de mercado y no predicen precios futuros."},
}
_LIMITATIONS_ES = {
    "SYNTHETIC_DATA": "Los precios y fundamentales proceden de un conjunto de datos de demostración sintético.",
    "FUNDAMENTALS_MISSING": "Las métricas fundamentales no están disponibles y no se incluyen en la puntuación.",
    "NON_PREDICTIVE": "Las reglas y umbrales son educativos. Describen datos pasados y no predicen rentabilidades.",
}


def _pct(value: float, digits: int = 0) -> str:
    return f"{round(value * 100, digits) + 0.0:.{digits}f}%"


def _relation_es(a: float, b: float) -> str:
    if a > b:
        return "por encima de"
    if a < b:
        return "por debajo de"
    return "igual a"


def _component_es(analysis: AnalyzeResponse, component: str) -> str:
    a = analysis.analysis
    label = _LABELS_ES[component][getattr(analysis.signals, component)]
    if component == "momentum":
        if a.momentum.changePercent is None:
            return f"El momentum es {label}."
        return f"El momentum es {label} ({a.momentum.changePercent:+.1f}% en el periodo analizado)."
    if component == "trend":
        parts = [f"La tendencia es {label}."]
        short_ma, long_ma = a.trend.shortMovingAverage, a.trend.longMovingAverage
        if short_ma is not None and long_ma is not None:
            parts.append(
                f"La media de {SHORT_MA_WINDOW} días ({short_ma:.2f}) está "
                f"{_relation_es(short_ma, long_ma)} la media de {LONG_MA_WINDOW} días ({long_ma:.2f})."
            )
        gap = a.trend.priceVsShortMovingAverage
        if gap is not None:
            if gap == 0:
                parts.append(f"El precio es igual a la media de {SHORT_MA_WINDOW} días.")
            else:
                side = "por encima" if gap > 0 else "por debajo"
                parts.append(f"El precio está un {_pct(abs(gap), 1)} {side} de la media de {SHORT_MA_WINDOW} días.")
        return " ".join(parts)
    if component == "risk":
        details = []
        if a.risk.volatility is not None:
            details.append(f"volatilidad anualizada {_pct(a.risk.volatility)}")
        if a.risk.maxDrawdown is not None:
            details.append(f"caída máxima {_pct(a.risk.maxDrawdown)}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"El riesgo histórico es {label}{suffix}."
    return (f"Los fundamentales son {label} según {a.fundamental.metricsUsed} de "
            f"{EXPECTED_FUNDAMENTAL_METRICS} métricas.")


def _finding_es(analysis: AnalyzeResponse, rule_id: str) -> str:
    a, s = analysis.analysis, analysis.supervision
    if rule_id == "MOMENTUM_TREND_DIVERGENCE":
        return (f"El momentum {_LABELS_ES['momentum'][analysis.signals.momentum]} coexiste con una "
                f"tendencia {_LABELS_ES['trend'][analysis.signals.trend]}.")
    if rule_id == "TECHNICAL_FUNDAMENTAL_DIVERGENCE":
        technical = (WEIGHTS["momentum"] * a.momentum.score + WEIGHTS["trend"] * a.trend.score)
        technical_word, fundamental_word = (
            ("favorable", "desfavorables") if technical > 0 else ("desfavorable", "favorables")
        )
        return (f"El bloque técnico es {technical_word} mientras que los fundamentales son "
                f"{fundamental_word}.")
    if rule_id == "OPPORTUNITY_RISK_CONFLICT":
        return ("La recomendación del motor es BUY mientras el riesgo histórico es alto. Es un "
                "conflicto entre señales favorables y riesgo, no una afirmación de que la "
                "recomendación sea errónea.")
    if rule_id == "HISTORY_INSUFFICIENT":
        q = s.dataQuality
        return (f"Hay {q.historicalObservations} observaciones disponibles; se requieren "
                f"{q.requiredHistoricalObservations} para los indicadores técnicos.")
    if rule_id == "FUNDAMENTALS_MISSING":
        return "No hay métricas fundamentales disponibles; no se incluyen en la puntuación."
    if rule_id == "FUNDAMENTALS_PARTIAL":
        return (f"Hay {a.fundamental.metricsUsed} de {EXPECTED_FUNDAMENTAL_METRICS} métricas "
                "fundamentales disponibles.")
    if rule_id == "LOW_CONFIDENCE":
        return (f"La confianza es {analysis.confidence:.2f}, inferior a {CONFIDENCE_LOW_THRESHOLD:.2f}. "
                "Refleja la cobertura de datos y el acuerdo entre señales, no la probabilidad de acierto.")
    raise KeyError(f"no Spanish template for finding {rule_id}")


def _limitation_es(analysis: AnalyzeResponse, code: str) -> str:
    if code == "FUNDAMENTALS_PARTIAL":
        return (f"Solo hay {analysis.analysis.fundamental.metricsUsed} de "
                f"{EXPECTED_FUNDAMENTAL_METRICS} métricas fundamentales disponibles.")
    if code in _LIMITATIONS_ES:
        return _LIMITATIONS_ES[code]
    raise KeyError(f"no Spanish template for limitation {code}")


def _overview(analysis: AnalyzeResponse, language: str) -> str:
    s = analysis.supervision
    status = _STATUS[language][s.status.value]
    provenance = _PROVENANCE[language][s.dataQuality.provenance.value]
    if language == "es":
        text = (f"{analysis.companyName} ({analysis.symbol}): la recomendación del motor es "
                f"{analysis.recommendation} con una confianza de {analysis.confidence:.2f}. La confianza "
                "mide la cobertura de datos y el acuerdo entre señales; no es una probabilidad de "
                f"rentabilidad. Estado del supervisor: {status}. {provenance}")
        if analysis.recommendation == "SELL":
            text += " SELL es la etiqueta del motor para una lectura desfavorable; no implica abrir una posición corta."
        return text
    text = (f"{analysis.companyName} ({analysis.symbol}): the engine recommendation is "
            f"{analysis.recommendation} with confidence {analysis.confidence:.2f}. Confidence measures "
            "data coverage and agreement between signals; it is not a probability of return. "
            f"Supervisor status: {status}. {provenance}")
    if analysis.recommendation == "SELL":
        text += " SELL is the engine's label for an unfavorable reading; it does not mean opening a short position."
    return text


def build_fallback(analysis: AnalyzeResponse, language: str) -> NarrativeReport:
    s = analysis.supervision
    packet = build_packet(analysis)
    texts_en = {item.id: item.text for item in packet.items}

    def text_for(evidence_id: str) -> str:
        if language == "en":
            return texts_en[evidence_id]
        if evidence_id in ("momentum", "trend", "risk", "fundamental"):
            return _component_es(analysis, evidence_id)
        if evidence_id.startswith("finding."):
            return _finding_es(analysis, evidence_id.removeprefix("finding."))
        if evidence_id.startswith("limitation."):
            return _limitation_es(analysis, evidence_id.removeprefix("limitation."))
        if evidence_id == "dataQuality":
            names = ", ".join(_COMPONENT_ES[c] for c in s.dataQuality.missingComponents)
            return f"Componentes sin datos: {names}."
        if evidence_id == "holdOffset":
            fav = [i.component for i in s.supportingEvidence if i.polarity.value == "favorable"
                   and i.component != "risk"]
            unf = [i.component for i in s.supportingEvidence if i.polarity.value == "unfavorable"
                   and i.component != "risk"]
            return (f"Las señales favorables ({', '.join(_COMPONENT_ES[c] for c in fav)}) y "
                    f"desfavorables ({', '.join(_COMPONENT_ES[c] for c in unf)}) se compensan.")
        raise KeyError(evidence_id)

    sections = {
        section: [NarrativePoint(text=text_for(i), evidenceIds=[i]) for i in ids]
        for section, ids in anchors(packet).items()
    }
    title = (f"Informe de análisis: {analysis.symbol}" if language == "es"
             else f"Analysis report: {analysis.symbol}")
    return NarrativeReport(
        title=title,
        overview=OverviewPoint(text=_overview(analysis, language),
                                evidenceIds=["recommendation", "supervisor"]),
        **sections,
    )

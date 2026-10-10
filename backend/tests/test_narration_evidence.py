"""Evidence packet, configuration and deterministic fallback."""

import pytest

from app.analysis.service import analyze_symbol
from app.data.demo_provider import DemoDataProvider
from app.narration.config import MAX_PACKET_CHARS, NarrationConfigError, NarrationSettings, load_settings
from app.narration.evidence import anchors, build_packet
from app.narration.fallback import build_fallback
from app.narration.validation import validate_narrative
from tests.factories import FixedProvider, make_snapshot, rising_closes

DEMO_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]


def _analysis(symbol="NVDA"):
    return analyze_symbol(symbol, DemoDataProvider())


# --- Packet ---------------------------------------------------------------

@pytest.mark.parametrize("symbol", DEMO_SYMBOLS)
def test_packet_is_bounded_and_has_no_price_rows(symbol):
    packet = build_packet(_analysis(symbol))
    dumped = packet.model_dump_json()
    assert len(dumped) <= MAX_PACKET_CHARS
    assert "bars" not in packet.model_dump() and "http" not in dumped


def test_packet_copies_engine_values():
    analysis = _analysis("TSLA")
    packet = build_packet(analysis)
    assert packet.recommendation == analysis.recommendation == "SELL"
    assert packet.confidence == analysis.confidence
    assert packet.supervisorStatus == analysis.supervision.status.value
    assert packet.provenance == "synthetic"
    metric = next(m for m in packet.metrics if m.id == "trend.shortMovingAverage")
    assert metric.value == analysis.analysis.trend.shortMovingAverage


def test_packet_ids_are_unique_and_anchors_follow_supervision():
    packet = build_packet(_analysis("TSLA"))
    ids = [item.id for item in packet.items]
    assert len(ids) == len(set(ids))
    sections = anchors(packet)
    assert sections["supportingReasons"] == ["momentum", "trend", "fundamental"]
    assert sections["riskFactors"] == ["risk"]
    assert sections["counterpoints"] == []
    assert sections["limitations"] == ["limitation.SYNTHETIC_DATA", "limitation.NON_PREDICTIVE"]


def test_missing_values_stay_null_in_packet():
    analysis = analyze_symbol("TEST", FixedProvider(make_snapshot(rising_closes(30), None)))
    packet = build_packet(analysis)
    values = {m.id: m.value for m in packet.metrics}
    assert values["trend.shortMovingAverage"] is None
    assert values["fundamental.peRatio"] is None
    assert "finding.HISTORY_INSUFFICIENT" in anchors(packet)["dataGaps"]
    assert "dataQuality" in anchors(packet)["dataGaps"]


# --- Configuration --------------------------------------------------------

def test_defaults_are_disabled():
    settings = load_settings({})
    assert settings.enabled is False
    assert settings.base_url == "http://127.0.0.1:1234/v1"
    assert settings.max_concurrent_requests == 1
    assert settings.temperature == 0.0


def test_env_values_are_parsed():
    settings = load_settings({
        "ATLAS_NARRATION_ENABLED": "true", "ATLAS_LM_STUDIO_MODEL": "my-model",
        "ATLAS_LM_STUDIO_TIMEOUT_SECONDS": "30", "ATLAS_LM_STUDIO_MAX_OUTPUT_TOKENS": "900",
        "ATLAS_NARRATION_MAX_CONCURRENT_REQUESTS": "2",
    })
    assert (settings.enabled, settings.model, settings.timeout_seconds) == (True, "my-model", 30.0)
    assert (settings.max_output_tokens, settings.max_concurrent_requests) == (900, 2)


@pytest.mark.parametrize("env", [
    {"ATLAS_NARRATION_ENABLED": "true"},                                   # model required
    {"ATLAS_LM_STUDIO_BASE_URL": "https://api.openai.com/v1"},             # not loopback
    {"ATLAS_LM_STUDIO_BASE_URL": "ftp://127.0.0.1/v1"},                    # bad scheme
    {"ATLAS_LM_STUDIO_TIMEOUT_SECONDS": "abc"},
    {"ATLAS_LM_STUDIO_TIMEOUT_SECONDS": "0"},
    {"ATLAS_LM_STUDIO_MAX_OUTPUT_TOKENS": "100000"},
    {"ATLAS_LM_STUDIO_TEMPERATURE": "5"},
    {"ATLAS_NARRATION_MAX_CONCURRENT_REQUESTS": "0"},
    {"ATLAS_NARRATION_ENABLED": "maybe"},
])
def test_invalid_configuration_is_rejected(env):
    with pytest.raises(NarrationConfigError):
        load_settings(env)


def test_settings_object_validates_directly():
    with pytest.raises(NarrationConfigError):
        NarrationSettings(enabled=True, model="  ")


# --- Fallback -------------------------------------------------------------

@pytest.mark.parametrize("symbol", DEMO_SYMBOLS)
@pytest.mark.parametrize("language", ["es", "en"])
def test_fallback_passes_structural_validation(symbol, language):
    analysis = _analysis(symbol)
    report = build_fallback(analysis, language)
    validate_narrative(report.model_dump(), build_packet(analysis), language, mode="deterministic")


@pytest.mark.parametrize("symbol", DEMO_SYMBOLS)
def test_fallback_has_same_evidence_in_both_languages(symbol):
    analysis = _analysis(symbol)
    es, en = build_fallback(analysis, "es"), build_fallback(analysis, "en")
    for section in ("supportingReasons", "counterpoints", "riskFactors", "dataGaps", "limitations"):
        assert [p.evidenceIds for p in getattr(es, section)] == [p.evidenceIds for p in getattr(en, section)]


def test_fallback_english_reuses_supervision_text():
    analysis = _analysis("TSLA")
    report = build_fallback(analysis, "en")
    assert [p.text for p in report.supportingReasons] == analysis.supervision.report.keyReasons
    assert "does not mean opening a short position" in report.overview.text


def test_fallback_spanish_uses_backend_numbers():
    report = build_fallback(_analysis("TSLA"), "es")
    assert report.title == "Informe de análisis: TSLA"
    assert report.supportingReasons[1].text == (
        "La tendencia es bajista. La media de 20 días (178.92) está por debajo de la media de "
        "50 días (186.31). El precio está un 14.9% por debajo de la media de 20 días."
    )
    assert "no implica abrir una posición corta" in report.overview.text
    assert "sintético" in report.overview.text


def test_fallback_hold_offset_in_spanish():
    report = build_fallback(_analysis("AAPL"), "es")
    assert report.supportingReasons[0].text == (
        "Las señales favorables (fundamentales) y desfavorables (tendencia) se compensan."
    )


def test_fallback_insufficient_history_in_spanish():
    analysis = analyze_symbol("TEST", FixedProvider(make_snapshot(rising_closes(30), None)))
    report = build_fallback(analysis, "es")
    gaps = [p.text for p in report.dataGaps]
    assert "Hay 30 observaciones disponibles; se requieren 50 para los indicadores técnicos." in gaps
    assert "Componentes sin datos: tendencia, fundamentales." in gaps


@pytest.mark.parametrize("language", ["es", "en"])
def test_fallback_is_reproducible(language):
    assert build_fallback(_analysis("META"), language) == build_fallback(_analysis("META"), language)

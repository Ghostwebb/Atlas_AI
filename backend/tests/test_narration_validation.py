"""Validation of model output: structure, references, coverage and text checks."""

import copy
import json

import pytest

from app.analysis.service import analyze_symbol
from app.data.demo_provider import DemoDataProvider
from app.narration.evidence import build_packet
from app.narration.models import EvidencePacket
from app.narration.validation import InvalidNarrativeError, parse_model_content, validate_narrative
from tests.narration_helpers import valid_model_output


def _packet(symbol="TSLA") -> EvidencePacket:
    return build_packet(analyze_symbol(symbol, DemoDataProvider()))


def _check(data, packet=None, language="es"):
    return validate_narrative(data, packet or _packet(), language, mode="llm")


def test_valid_output_is_accepted():
    packet = _packet()
    report = _check(valid_model_output(packet), packet)
    assert report.overview.evidenceIds == ["recommendation", "supervisor"]


@pytest.mark.parametrize("symbol", ["AAPL", "NVDA", "TSLA", "META"])
@pytest.mark.parametrize("language", ["es", "en"])
def test_valid_output_for_each_shape(symbol, language):
    packet = _packet(symbol)
    _check(valid_model_output(packet, language), packet, language)


def test_code_fenced_json_is_parsed():
    data = {"a": 1}
    assert parse_model_content("```json\n" + json.dumps(data) + "\n```") == data


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"title": '])
def test_invalid_json_is_rejected(content):
    with pytest.raises(InvalidNarrativeError):
        parse_model_content(content)


def test_raw_output_size_limit():
    with pytest.raises(InvalidNarrativeError):
        parse_model_content("{" + " " * 13_000 + "}")


def _mutated(mutate):
    packet = _packet()
    data = valid_model_output(packet)
    mutate(data)
    return data, packet


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(extra="field"),                                     # extra top-level field
    lambda d: d["overview"].update(confidence=0.99),                       # extra point field
    lambda d: d.pop("limitations"),                                        # missing section
    lambda d: d.update(title=""),                                          # empty title
    lambda d: d["supportingReasons"][0].update(text="x" * 401),            # point too long
    lambda d: d["supportingReasons"][0].update(evidenceIds=[]),            # no ids
    lambda d: d.update(riskFactors=[{"text": "x", "evidenceIds": ["risk"]}] * 7),  # too many points
])
def test_schema_violations_are_rejected(mutate):
    data, packet = _mutated(mutate)
    with pytest.raises(InvalidNarrativeError):
        _check(data, packet)


def test_unknown_evidence_id_is_rejected():
    data, packet = _mutated(lambda d: d["supportingReasons"][0]["evidenceIds"].append("earnings_call"))
    with pytest.raises(InvalidNarrativeError, match="unknown evidence ids"):
        _check(data, packet)


def test_point_in_wrong_section_is_rejected():
    # TSLA risk is a risk factor, not a reason for SELL.
    data, packet = _mutated(lambda d: d["supportingReasons"].append(
        {"text": "El riesgo es una razón de la venta.", "evidenceIds": ["risk"]}))
    with pytest.raises(InvalidNarrativeError, match="cites none of its evidence"):
        _check(data, packet)


def test_omitted_evidence_is_rejected():
    data, packet = _mutated(lambda d: d.update(limitations=d["limitations"][1:]))  # drops SYNTHETIC_DATA
    with pytest.raises(InvalidNarrativeError, match="omits evidence"):
        _check(data, packet)


@pytest.mark.parametrize("foreign_id", ["risk", "recommendation", "limitation.SYNTHETIC_DATA"])
def test_valid_anchor_cannot_mask_foreign_section_evidence(foreign_id):
    data, packet = _mutated(
        lambda d: d["supportingReasons"][0]["evidenceIds"].append(foreign_id)
    )
    with pytest.raises(InvalidNarrativeError, match="outside its section"):
        _check(data, packet)


def test_invented_section_content_is_rejected():
    data, packet = _mutated(lambda d: d.update(counterpoints=[
        {"text": "Una señal contraria inventada.", "evidenceIds": ["momentum"]}]))
    with pytest.raises(InvalidNarrativeError, match="must be empty"):
        _check(data, packet)


def test_overview_must_cite_recommendation():
    data, packet = _mutated(lambda d: d["overview"].update(evidenceIds=["supervisor"]))
    with pytest.raises(InvalidNarrativeError, match="recommendation"):
        _check(data, packet)


@pytest.mark.parametrize(("text", "reason"), [
    ("El momentum cayó un treinta por ciento, es decir 30%.", "digits"),
    ("El precio objetivo de la acción es alto según el análisis.", "banned"),
    ("Las noticias de la empresa explican la caída de la acción.", "banned"),
    ("La señal de la empresa justifica BUY para la acción.", "recommendation"),
])
def test_text_checks_reject_unsafe_prose(text, reason):
    data, packet = _mutated(lambda d: d["supportingReasons"][0].update(text=text))
    with pytest.raises(InvalidNarrativeError, match=reason):
        _check(data, packet)


def test_wrong_language_is_rejected():
    packet = _packet()
    with pytest.raises(InvalidNarrativeError, match="language"):
        _check(valid_model_output(packet, "en"), packet, "es")
    with pytest.raises(InvalidNarrativeError, match="language"):
        _check(valid_model_output(packet, "es"), packet, "en")


def test_non_synthetic_provenance_rejects_synthetic_wording():
    packet = _packet().model_copy(update={"provenance": "historical"})
    data = valid_model_output(packet)  # overview says "sintéticos de demostración"
    with pytest.raises(InvalidNarrativeError, match="synthetic"):
        _check(data, packet)


def test_text_checks_do_not_apply_to_deterministic_mode():
    packet = _packet()
    data = copy.deepcopy(valid_model_output(packet))
    data["supportingReasons"][0]["text"] = "El momentum es negativo (-39.1% en el periodo analizado)."
    validate_narrative(data, packet, "es", mode="deterministic")

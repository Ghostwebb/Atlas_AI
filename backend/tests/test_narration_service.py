"""LM Studio client and narration service with a mocked HTTP transport."""

import json
import threading

import httpx
import pytest

from app.analysis.service import analyze_symbol
from app.data.demo_provider import DemoDataProvider
from app.narration.client import NarrationError
from app.narration.config import NarrationSettings
from app.narration.evidence import build_packet
from app.narration.fallback import build_fallback
from app.narration.models import NarrativeStatus, ReasonCode
from app.narration.service import narrate
from tests.narration_helpers import (
    TEST_MODEL,
    chat_response,
    client_raising,
    client_returning,
    client_with_handler,
    enabled_settings,
    valid_model_output,
)


def _analysis(symbol="TSLA"):
    return analyze_symbol(symbol, DemoDataProvider())


def _narrate(client, language="es", symbol="TSLA"):
    return narrate(_analysis(symbol), language, enabled_settings(), client)


# --- 1. Disabled -----------------------------------------------------------

def test_disabled_returns_deterministic_report_without_calling_model():
    analysis = _analysis()
    narrative = narrate(analysis, "es", NarrationSettings(), None)
    assert narrative.status is NarrativeStatus.DISABLED
    assert narrative.generationMode == "deterministic"
    assert narrative.model is None
    assert narrative.reason.code is ReasonCode.MODEL_DISABLED
    assert narrative.report == build_fallback(analysis, "es")


# --- 2. Valid response --------------------------------------------------------

def test_valid_response_is_generated():
    analysis = _analysis()
    output = valid_model_output(build_packet(analysis), "es")
    narrative = narrate(analysis, "es", enabled_settings(), client_returning(output))
    assert narrative.status is NarrativeStatus.GENERATED
    assert narrative.generationMode == "llm"
    assert narrative.model == TEST_MODEL
    assert narrative.reason is None
    assert narrative.report.model_dump() == output


def test_request_shape_has_no_system_role_and_targets_local_endpoint():
    seen: list[httpx.Request] = []
    analysis = _analysis()
    client = client_returning(valid_model_output(build_packet(analysis)), seen=seen)
    narrate(analysis, "es", enabled_settings(), client)
    request = seen[0]
    assert request.url.path == "/v1/chat/completions"
    assert request.url.host == "127.0.0.1"
    body = json.loads(request.content)
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert body["model"] == TEST_MODEL and body["temperature"] == 0.0 and body["stream"] is False
    assert body["max_tokens"] == 1200
    assert "response_format" not in body
    assert "Authorization" not in request.headers


def test_json_schema_mode_is_opt_in():
    seen: list[httpx.Request] = []
    analysis = _analysis()
    settings = enabled_settings(use_json_schema=True)
    client = client_returning(valid_model_output(build_packet(analysis)), settings=settings, seen=seen)
    narrate(analysis, "es", settings, client)
    body = json.loads(seen[0].content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True


# --- 3-5. Connection, timeout, HTTP error -------------------------------------

@pytest.mark.parametrize(("error", "code"), [
    (httpx.ConnectError("refused"), ReasonCode.MODEL_UNAVAILABLE),
    (httpx.ReadTimeout("slow"), ReasonCode.MODEL_TIMEOUT),
    (httpx.ConnectTimeout("slow"), ReasonCode.MODEL_TIMEOUT),
])
def test_transport_errors_fall_back(error, code):
    narrative = _narrate(client_raising(error))
    assert narrative.status is NarrativeStatus.FALLBACK
    assert narrative.reason.code is code
    assert narrative.generationMode == "deterministic" and narrative.model is None


def test_http_error_falls_back_without_leaking_provider_body():
    narrative = _narrate(client_returning("{}", status=500))
    assert narrative.reason.code is ReasonCode.MODEL_UNAVAILABLE
    assert "stack trace" not in narrative.model_dump_json()


# --- 6-10. Invalid output ----------------------------------------------------

def _valid_tsla():
    return valid_model_output(build_packet(_analysis()), "es")


@pytest.mark.parametrize("make_client", [
    lambda: client_with_handler(lambda r: httpx.Response(200, json={"unexpected": True})),  # malformed
    lambda: client_with_handler(lambda r: httpx.Response(200, text="<html>")),            # not JSON body
    lambda: client_returning("Aquí está el informe: no es JSON"),                         # invalid JSON
    lambda: client_returning({**_valid_tsla(), "price": "extra"}),                        # extra field
    lambda: client_returning({**_valid_tsla(), "supportingReasons": [
        {"text": "Una razón con una fuente inexistente.", "evidenceIds": ["analyst_upgrade"]}]}),  # unknown id
    lambda: client_returning("{" + " " * 13_000 + "}"),                                   # too long
    lambda: client_returning(_valid_tsla(), finish_reason="length"),                      # truncated
    lambda: client_returning(""),                                                         # empty
])
def test_invalid_output_falls_back(make_client):
    narrative = _narrate(make_client())
    assert narrative.status is NarrativeStatus.FALLBACK
    assert narrative.reason.code is ReasonCode.INVALID_MODEL_OUTPUT
    assert narrative.report == build_fallback(_analysis(), "es")


def test_partial_report_is_not_accepted():
    output = _valid_tsla()
    output["riskFactors"] = []
    narrative = _narrate(client_returning(output))
    assert narrative.reason.code is ReasonCode.INVALID_MODEL_OUTPUT


# --- 11. Concurrency limit ----------------------------------------------------

def test_concurrency_limit_returns_busy_immediately():
    release = threading.Event()
    started = threading.Event()
    content = json.dumps(_valid_tsla(), ensure_ascii=False)

    def slow_handler(request):
        started.set()
        release.wait(timeout=5)
        return httpx.Response(200, json=chat_response(content))

    client = client_with_handler(slow_handler)
    results = {}
    worker = threading.Thread(target=lambda: results.setdefault("first", _narrate(client)))
    worker.start()
    assert started.wait(timeout=5)
    second = _narrate(client)          # slot is taken: no queueing
    release.set()
    worker.join(timeout=5)

    assert second.status is NarrativeStatus.FALLBACK
    assert second.reason.code is ReasonCode.MODEL_BUSY
    assert results["first"].status is NarrativeStatus.GENERATED
    assert _narrate(client).status is NarrativeStatus.GENERATED  # slot released afterwards


def test_client_raises_busy_code_directly():
    client = client_returning("{}", settings=enabled_settings(max_concurrent_requests=1))
    client._slots.acquire()
    with pytest.raises(NarrationError) as excinfo:
        client.complete([{"role": "user", "content": "x"}])
    assert excinfo.value.code is ReasonCode.MODEL_BUSY
    client._slots.release()


def test_client_close_releases_resources():
    client = client_returning("{}")
    client.close()
    with pytest.raises(RuntimeError):
        client._http.post("chat/completions", json={})


# --- 12-14, 18. Fallback language, preserved facts, reproducibility -----------

@pytest.mark.parametrize("language", ["es", "en"])
def test_fallback_respects_language(language):
    narrative = _narrate(client_raising(httpx.ConnectError("x")), language=language)
    assert narrative.language == language
    expected = "Informe de análisis: TSLA" if language == "es" else "Analysis report: TSLA"
    assert narrative.report.title == expected


def test_engine_facts_come_from_backend_not_model():
    analysis = _analysis("NVDA")
    output = valid_model_output(build_packet(analysis), "es")
    narrative = narrate(analysis, "es", enabled_settings(), client_returning(output))
    assert narrative.facts.recommendation == analysis.recommendation
    assert narrative.facts.confidence == analysis.confidence
    assert narrative.facts.supervisorStatus == analysis.supervision.status.value
    assert narrative.supervisorPolicyVersion == "phase3-v2"


def test_synthetic_provenance_is_visible_in_every_mode():
    analysis = _analysis()
    for narrative in (
        narrate(analysis, "es", NarrationSettings(), None),
        _narrate(client_raising(httpx.ConnectError("x"))),
        _narrate(client_returning(_valid_tsla())),
    ):
        assert narrative.facts.provenance == "synthetic" and narrative.facts.isSimulated is True
        cited = {i for p in narrative.report.limitations for i in p.evidenceIds}
        assert "limitation.SYNTHETIC_DATA" in cited


def test_fallback_is_reproducible_across_calls():
    first = _narrate(client_raising(httpx.ConnectError("x")))
    second = _narrate(client_raising(httpx.ConnectError("x")))
    assert first == second

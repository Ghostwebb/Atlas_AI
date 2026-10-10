"""Helpers for narration tests. No test needs a running LM Studio."""

import json

import httpx

from app.narration.client import LMStudioClient
from app.narration.config import NarrationSettings
from app.narration.evidence import OUTPUT_SECTIONS, anchors
from app.narration.models import EvidencePacket

TEST_MODEL = "test-model-id"  # placeholder for the mocked server, not a real model id


def enabled_settings(**overrides) -> NarrationSettings:
    values = {"enabled": True, "model": TEST_MODEL, "timeout_seconds": 5.0}
    values.update(overrides)
    return NarrationSettings(**values)


def valid_model_output(packet: EvidencePacket, language: str = "es") -> dict:
    """A qualitative, fully referenced output that passes every check."""
    rec = packet.recommendation
    if language == "es":
        overview = (f"El motor emite {rec}; la confianza mide la cobertura de los datos y el acuerdo "
                    "entre señales, no es una probabilidad. Los datos son sintéticos de demostración.")
        point = "La evidencia de este apartado se describe de forma cualitativa y sin cifras."
        title = f"Informe de {packet.symbol}"
    else:
        overview = (f"The engine emits {rec}; the confidence measures data coverage and the agreement "
                    "of signals, it is not a probability. The data is synthetic demo data.")
        point = "The evidence for this section is described in a qualitative way, with no figures."
        title = f"Report for {packet.symbol}"
    output = {"title": title, "overview": {"text": overview, "evidenceIds": ["recommendation", "supervisor"]}}
    for section in OUTPUT_SECTIONS:
        output[section] = [{"text": point, "evidenceIds": [i]} for i in anchors(packet)[section]]
    return output


def chat_response(content: str, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": finish_reason}],
    }


def client_returning(content: str | dict, finish_reason: str = "stop", status: int = 200,
                     settings: NarrationSettings | None = None, seen: list | None = None) -> LMStudioClient:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, text="internal provider detail: stack trace")
        return httpx.Response(200, json=chat_response(text, finish_reason))

    return LMStudioClient(settings or enabled_settings(), transport=httpx.MockTransport(handler))


def client_raising(error: Exception, settings: NarrationSettings | None = None) -> LMStudioClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return LMStudioClient(settings or enabled_settings(), transport=httpx.MockTransport(handler))


def client_with_handler(handler, settings: NarrationSettings | None = None) -> LMStudioClient:
    return LMStudioClient(settings or enabled_settings(), transport=httpx.MockTransport(handler))

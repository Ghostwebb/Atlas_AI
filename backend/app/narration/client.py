"""Minimal client for LM Studio's local OpenAI-compatible HTTP API.

- One attempt per request (no retries), explicit timeout.
- A bounded semaphore limits concurrent generations. When it is full the call
  fails immediately with MODEL_BUSY instead of queueing behind a slow model.
- Errors are mapped to stable reason codes; provider bodies are never exposed.
"""

import threading

import httpx

from app.narration.config import MAX_RAW_OUTPUT_CHARS, NarrationSettings
from app.narration.models import NarrativeReport, ReasonCode


class NarrationError(Exception):
    def __init__(self, code: ReasonCode, detail: str = ""):
        self.code = code
        self.detail = detail  # internal only
        super().__init__(f"{code.value}: {detail}")


class LMStudioClient:
    def __init__(self, settings: NarrationSettings, transport: httpx.BaseTransport | None = None):
        self._settings = settings
        self._slots = threading.BoundedSemaphore(settings.max_concurrent_requests)
        self._http = httpx.Client(
            base_url=settings.base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(settings.timeout_seconds),
            transport=transport,
        )

    @property
    def model(self) -> str:
        return self._settings.model

    def _payload(self, messages: list[dict[str, str]]) -> dict:
        payload = {
            "model": self._settings.model,
            "messages": messages,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_output_tokens,
            "stream": False,
        }
        if self._settings.use_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "atlas_narrative",
                    "strict": True,
                    "schema": NarrativeReport.model_json_schema(),
                },
            }
        return payload

    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return the assistant message content, or raise NarrationError."""
        if not self._slots.acquire(blocking=False):
            raise NarrationError(ReasonCode.MODEL_BUSY, "concurrency limit reached")
        try:
            response = self._http.post("chat/completions", json=self._payload(messages))
        except httpx.TimeoutException as error:
            raise NarrationError(ReasonCode.MODEL_TIMEOUT, type(error).__name__) from error
        except httpx.HTTPError as error:
            raise NarrationError(ReasonCode.MODEL_UNAVAILABLE, type(error).__name__) from error
        finally:
            self._slots.release()

        if response.status_code != 200:
            raise NarrationError(ReasonCode.MODEL_UNAVAILABLE, f"HTTP {response.status_code}")
        try:
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise NarrationError(ReasonCode.INVALID_MODEL_OUTPUT, "malformed provider response") from error
        if not isinstance(content, str) or not content.strip():
            raise NarrationError(ReasonCode.INVALID_MODEL_OUTPUT, "empty content")
        if choice.get("finish_reason") == "length":
            raise NarrationError(ReasonCode.INVALID_MODEL_OUTPUT, "output truncated at max tokens")
        if len(content) > MAX_RAW_OUTPUT_CHARS:
            raise NarrationError(ReasonCode.INVALID_MODEL_OUTPUT, "output too long")
        return content

    def list_models(self) -> list[str]:
        """Installed/loaded model ids (used by the manual check script)."""
        response = self._http.get("models")
        response.raise_for_status()
        return [item["id"] for item in response.json().get("data", [])]

    def close(self) -> None:
        self._http.close()

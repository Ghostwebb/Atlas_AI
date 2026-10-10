"""Narration settings, read from environment variables and validated.

The backend does not load a .env file. Variables must be exported in the shell
that starts uvicorn (see README). Invalid values raise NarrationConfigError at
startup instead of being silently replaced.

The provider URL is server-side configuration only; API clients cannot send one.
It must point to a loopback host so evidence never leaves the machine.
"""

import os
from dataclasses import dataclass
from urllib.parse import urlparse

NARRATION_SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "narration-v1"
DEFAULT_LANGUAGE = "es"
SUPPORTED_LANGUAGES = ("es", "en")

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Output limits enforced on the model output (see validation.py).
MAX_TITLE_CHARS = 120
MAX_POINT_CHARS = 400
MAX_OVERVIEW_CHARS = 700
MAX_POINTS_PER_SECTION = 6
MAX_EVIDENCE_IDS_PER_POINT = 5
MAX_RAW_OUTPUT_CHARS = 12_000
# Upper bound for the serialized evidence packet sent to the model.
MAX_PACKET_CHARS = 8_000


class NarrationConfigError(ValueError):
    pass


@dataclass(frozen=True)
class NarrationSettings:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:1234/v1"
    model: str = ""
    timeout_seconds: float = 45.0
    max_output_tokens: int = 1200
    temperature: float = 0.0
    max_concurrent_requests: int = 1
    # Send response_format=json_schema. Off by default: enable only after the
    # manual check confirms the loaded model and LM Studio version honour it.
    use_json_schema: bool = False

    def __post_init__(self) -> None:
        errors: list[str] = []
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            errors.append("ATLAS_LM_STUDIO_BASE_URL must be an http(s) URL")
        elif parsed.hostname not in LOOPBACK_HOSTS:
            errors.append("ATLAS_LM_STUDIO_BASE_URL must point to a loopback host (local LM Studio)")
        if self.enabled and not self.model.strip():
            errors.append("ATLAS_LM_STUDIO_MODEL is required when ATLAS_NARRATION_ENABLED=true")
        if not 1 <= self.timeout_seconds <= 300:
            errors.append("ATLAS_LM_STUDIO_TIMEOUT_SECONDS must be between 1 and 300")
        if not 128 <= self.max_output_tokens <= 8192:
            errors.append("ATLAS_LM_STUDIO_MAX_OUTPUT_TOKENS must be between 128 and 8192")
        if not 0.0 <= self.temperature <= 2.0:
            errors.append("ATLAS_LM_STUDIO_TEMPERATURE must be between 0 and 2")
        if not 1 <= self.max_concurrent_requests <= 8:
            errors.append("ATLAS_NARRATION_MAX_CONCURRENT_REQUESTS must be between 1 and 8")
        if errors:
            raise NarrationConfigError("; ".join(errors))


def _bool(env: dict[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    raise NarrationConfigError(f"{name} must be true or false")


def _number(env: dict[str, str], name: str, default, cast):
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return cast(raw.strip())
    except ValueError as error:
        raise NarrationConfigError(f"{name} must be a number") from error


def load_settings(env: dict[str, str] | None = None) -> NarrationSettings:
    env = dict(os.environ) if env is None else env
    return NarrationSettings(
        enabled=_bool(env, "ATLAS_NARRATION_ENABLED", False),
        base_url=(env.get("ATLAS_LM_STUDIO_BASE_URL") or NarrationSettings.base_url).strip(),
        model=(env.get("ATLAS_LM_STUDIO_MODEL") or "").strip(),
        timeout_seconds=_number(env, "ATLAS_LM_STUDIO_TIMEOUT_SECONDS", 45.0, float),
        max_output_tokens=_number(env, "ATLAS_LM_STUDIO_MAX_OUTPUT_TOKENS", 1200, int),
        temperature=_number(env, "ATLAS_LM_STUDIO_TEMPERATURE", 0.0, float),
        max_concurrent_requests=_number(env, "ATLAS_NARRATION_MAX_CONCURRENT_REQUESTS", 1, int),
        use_json_schema=_bool(env, "ATLAS_LM_STUDIO_USE_JSON_SCHEMA", False),
    )

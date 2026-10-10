"""Manual check against a real LM Studio server. Not part of the pytest suite.

Usage (from backend/, with LM Studio's local server running and a model loaded):

    export ATLAS_NARRATION_ENABLED=true
    export ATLAS_LM_STUDIO_MODEL=<id printed by: curl http://127.0.0.1:1234/v1/models>
    ./.venv/bin/python scripts/manual_lmstudio_check.py NVDA es

It lists the models the server exposes, checks the configured id is among them,
generates one narrative and prints status, reason code and elapsed time. The
JSON result is written to scripts/manual_lmstudio_result.json (git-ignored).
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis.service import analyze_symbol  # noqa: E402
from app.data.demo_provider import DemoDataProvider  # noqa: E402
from app.narration.client import LMStudioClient  # noqa: E402
from app.narration.config import load_settings  # noqa: E402
from app.narration.service import narrate  # noqa: E402


def main() -> int:
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "NVDA").upper()
    language = sys.argv[2] if len(sys.argv) > 2 else "es"
    settings = load_settings()
    if not settings.enabled:
        print("Set ATLAS_NARRATION_ENABLED=true and ATLAS_LM_STUDIO_MODEL first.")
        return 2

    client = LMStudioClient(settings)
    try:
        try:
            models = client.list_models()
        except Exception as error:  # manual tool: report and stop
            print(f"LM Studio not reachable at {settings.base_url}: {type(error).__name__}")
            return 1
        print("Models exposed by LM Studio:", models)
        if settings.model not in models:
            print(f"Configured model '{settings.model}' is not in that list.")
            return 1

        analysis = analyze_symbol(symbol, DemoDataProvider())
        if analysis is None:
            print(f"Unknown demo symbol {symbol}")
            return 1
        started = time.perf_counter()
        narrative = narrate(analysis, language, settings, client)
        elapsed = time.perf_counter() - started
    finally:
        client.close()

    print(f"model={settings.model} json_schema={settings.use_json_schema} "
          f"temperature={settings.temperature} max_tokens={settings.max_output_tokens}")
    print(f"status={narrative.status.value} reason={narrative.reason.code.value if narrative.reason else None} "
          f"elapsed={elapsed:.1f}s")
    out = Path(__file__).with_name("manual_lmstudio_result.json")
    out.write_text(json.dumps(narrative.model_dump(mode="json"), indent=2, ensure_ascii=False))
    print(f"Narrative written to {out}")
    return 0 if narrative.status.value == "generated" else 1


if __name__ == "__main__":
    raise SystemExit(main())

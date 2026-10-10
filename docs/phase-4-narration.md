# Phase 4: narrative report with a local model (LM Studio)

`POST /api/report` returns the full deterministic analysis plus a narrative that
explains it. The narrative can be written by a model served locally by LM Studio
(for example a Gemma model) or, when that is not possible, by a deterministic
fallback built from the supervisor.

The recommendation, metrics, confidence and supervisor status are always computed by
the deterministic backend. The model only writes prose. It does not trade, browse or
change any computed result.

## Pipeline

```text
analysis (deterministic) -> supervisor (deterministic) -> evidence packet
  -> LM Studio /v1/chat/completions -> parse + validate -> narrative
  (any failure)                                         -> deterministic fallback
```

Code: `backend/app/narration/` (`config`, `models`, `evidence`, `prompts`, `client`,
`validation`, `fallback`, `service`). The analyzers and supervisor rules have no network code.

## Deterministic analysis vs generated narrative

| | `/api/analyze` and `analysis` | `narrative.report` (`generationMode: "llm"`) |
|---|---|---|
| Source | Engine and supervisor | Local model, validated by the backend |
| Deterministic | Yes | No, even at temperature 0 |
| Numbers | Yes, computed | None: model text with digits is rejected |
| Trust | Computed values | Bounded and referenced, but not proven true |

`/api/analyze` never calls the model.

## Running LM Studio

1. In LM Studio, download and load a model (for example a Gemma instruct model that fits
   16 GB of RAM). ATLAS does not download models and has no built-in model id.
2. Start the local server (Developer tab → Start Server; default port 1234).
3. Find the exact model id:
   ```bash
   curl http://127.0.0.1:1234/v1/models
   ```
4. Configure the backend. **It does not read `.env` by itself.** Export the variables in
   the same shell that starts uvicorn:
   ```bash
   cd backend
   export ATLAS_NARRATION_ENABLED=true
   export ATLAS_LM_STUDIO_MODEL="<id from step 3>"
   ./.venv/bin/uvicorn app.main:app --port 8000
   ```
   Or copy `.env.example` to `.env`, edit it, and run `set -a; source .env; set +a` first.
   Invalid values (non-loopback URL, missing model, out-of-range numbers) stop the server
   at startup with a clear message.
5. Try it:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/api/report \
     -H 'Content-Type: application/json' -d '{"symbol":"NVDA","language":"es"}'
   ```

### Settings

| Variable | Default | Range / rule |
|---|---|---|
| `ATLAS_NARRATION_ENABLED` | `false` | `true`/`false` |
| `ATLAS_LM_STUDIO_BASE_URL` | `http://127.0.0.1:1234/v1` | http(s), loopback host only |
| `ATLAS_LM_STUDIO_MODEL` | empty | required when enabled; must match an installed id |
| `ATLAS_LM_STUDIO_TIMEOUT_SECONDS` | `45` | 1–300 |
| `ATLAS_LM_STUDIO_MAX_OUTPUT_TOKENS` | `1200` | 128–8192 |
| `ATLAS_LM_STUDIO_TEMPERATURE` | `0` | 0–2 |
| `ATLAS_NARRATION_MAX_CONCURRENT_REQUESTS` | `1` | 1–8 |
| `ATLAS_LM_STUDIO_USE_JSON_SCHEMA` | `false` | sends `response_format: json_schema` |

No API key is used and the remote OpenAI service is never called. The prompt uses a single
`user` message, because some Gemma chat templates reject a `system` role. Structured output
(`json_schema`) is opt-in because support depends on the LM Studio version and model; the
backend validates the output either way.

## API: `POST /api/report`

Request: `{"symbol": "NVDA", "language": "es"}`. `language` is `es` (default) or `en`.
Extra fields are rejected, so clients cannot send metrics, recommendations or a provider URL.

Response: `{"analysis": AnalyzeResponse, "narrative": Narrative}`. `analysis` is exactly
what `/api/analyze` returns.

`narrative`:

| Field | Meaning |
|---|---|
| `schemaVersion` | `"1.0"` |
| `promptVersion` | `"narration-v1"` |
| `supervisorPolicyVersion` | supervisor policy used (`"phase3-v2"`) |
| `status` | `generated` (model output accepted), `fallback` (model failed), `disabled` |
| `generationMode` | `llm` or `deterministic` |
| `model` | configured model id when generated, otherwise `null` |
| `language` | `es` or `en` |
| `reason` | `null` when generated, else `{code, message}` |
| `facts` | `recommendation`, `confidence`, `supervisorStatus`, `provenance`, `isSimulated`, `dataAsOf`, copied from the backend |
| `report` | `title`, `overview`, `supportingReasons`, `counterpoints`, `riskFactors`, `dataGaps`, `limitations` |

Every point is `{"text": "...", "evidenceIds": [...]}`. `overview` is a point too.

Reason codes: `MODEL_DISABLED`, `MODEL_UNAVAILABLE` (connection or HTTP error),
`MODEL_TIMEOUT`, `MODEL_BUSY` (concurrency limit reached; the request does not wait),
`INVALID_MODEL_OUTPUT`. Messages are fixed text; provider bodies and traces are never returned.

Errors are unchanged: `400` for an invalid body, symbol or language, `404` for an unknown
symbol, `500` for a supervision integrity error, all as `{error, message}`. A model failure
never produces an error status; it produces a fallback.

## What happens when the model fails

One attempt with an explicit timeout, no retries. A connection error, timeout, HTTP error,
busy slot, malformed response, truncated output (`finish_reason: length`) or failed
validation all return the deterministic report with `status: "fallback"` and a reason code.
A partially valid output is never accepted.

## Evidence packet

The model receives a bounded JSON packet (≤ 8,000 characters; about 3 KB for the demo
symbols) built from validated results only: symbol, company, recommendation, confidence and
its meaning, supervisor status and its meaning, provenance, dates, coverage, ten metrics
with units, and evidence items with stable IDs. It contains no price rows, configuration,
secrets or URLs.

Evidence IDs: `momentum`, `trend`, `risk`, `fundamental`, `recommendation`, `supervisor`,
`holdOffset`, `dataQuality`, `finding.<RULE_ID>`, `limitation.<CODE>`.

## Output validation

Structural (model and fallback):

- strict schema with no extra fields; title ≤ 120, point ≤ 400, overview ≤ 700 characters;
  ≤ 6 points per list; 1–5 evidence IDs per point; every ID must exist;
- each list must cite every ID the supervisor assigned to it and only those (supporting
  reasons follow `supportingEvidence`; counterpoints the non-risk `opposingEvidence`; risk
  factors the high-risk item and contradiction or caution findings; data gaps the
  data-gap findings and missing components; limitations the limitations and observations);
  a list with no evidence must be empty;
- the overview cites `recommendation`.

Model text only:

- no digits (numbers come from `analysis`, shown by the UI);
- no banned phrases (price targets, guarantees, expected returns, news, "will rise/fall",
  trade instructions), in English and Spanish;
- no BUY/HOLD/SELL other than the engine's;
- no synthetic or demo wording when provenance is not synthetic;
- the requested language, by a stop-word heuristic.

**Limitation:** these checks bound and audit the output, but they do not prove the prose is
true. A sentence can be valid, well referenced and still mischaracterize the evidence. That
is why figures and the recommendation are shown from `facts` and `analysis`, never from model
text, and why the UI must label generated text as generated.

## Deterministic fallback

Built from the supervisor in `es` or `en`. English reuses the supervisor's sentences. Spanish
uses templates with the same backend numbers. Both cite the same evidence IDs. The same
analysis, language and policy always give the same fallback. It reports
`generationMode: "deterministic"` and `model: null`, and is never presented as model output.

## Guidance for the frontend (Codex)

- Call `/api/report` only when the user asks for the narrative. Keep `/api/analyze` for the
  dashboard: it is fast and never depends on the model.
- Show figures, the recommendation, confidence and status from `analysis` / `narrative.facts`,
  never parsed from text.
- Label the source: `generationMode: "llm"` → "Generated by local model `<model>`";
  `deterministic` → "Deterministic report". Show `reason.message` for `fallback` and `disabled`.
- Render `overview`, then `supportingReasons` ("Why"), `counterpoints`, `riskFactors`,
  `dataGaps` and `limitations` as separate sections. Use `evidenceIds` to link each point to
  the matching supervision evidence or finding.
- When `facts.provenance` is `synthetic`, always show the synthetic-data notice.
- A generated report can take tens of seconds on a laptop; show a loading state and do not
  send concurrent requests (they return `MODEL_BUSY`).

## Tests and manual check

`cd backend && ./.venv/bin/python -m pytest -q` runs every test with a mocked HTTP transport
(`httpx.MockTransport`). No test needs LM Studio.

Manual check with a real server (not part of the suite):

```bash
cd backend
export ATLAS_NARRATION_ENABLED=true ATLAS_LM_STUDIO_MODEL="<id>"
./.venv/bin/python scripts/manual_lmstudio_check.py NVDA es
```

It lists the server's models, checks the configured id, generates one narrative, prints
status, reason and elapsed time, and writes `scripts/manual_lmstudio_result.json`
(git-ignored). Requirements: LM Studio server running on this machine, a model loaded, and the
id exported. **Status:** the user reports having generated real reports with Gemma through LM
Studio on their machine. Claude has not reproduced that run (LM Studio is not reachable from its
environment); the automated suite uses a mocked transport. Record the model, settings, time and
result when you run the check.

## Examples

Fallback (real backend output; synthetic demo data; META, Spanish, model disabled):

```json
{
  "schemaVersion": "1.0",
  "promptVersion": "narration-v1",
  "supervisorPolicyVersion": "phase3-v2",
  "status": "disabled",
  "generationMode": "deterministic",
  "model": null,
  "language": "es",
  "reason": {
    "code": "MODEL_DISABLED",
    "message": "Model narration is disabled; the deterministic report is shown."
  },
  "facts": {
    "recommendation": "SELL",
    "confidence": 0.27,
    "supervisorStatus": "caution",
    "provenance": "synthetic",
    "isSimulated": true,
    "dataAsOf": "2026-09-30"
  },
  "report": {
    "title": "Informe de análisis: META",
    "overview": {
      "text": "Meta Platforms, Inc. (META): la recomendación del motor es SELL con una confianza de 0.27. La confianza mide la cobertura de datos y el acuerdo entre señales; no es una probabilidad de rentabilidad. Estado del supervisor: precaución (señales en conflicto o riesgo relevante). Los datos son un conjunto sintético de demostración, no precios reales de mercado. SELL es la etiqueta del motor para una lectura desfavorable; no implica abrir una posición corta.",
      "evidenceIds": [
        "recommendation",
        "supervisor"
      ]
    },
    "supportingReasons": [
      {
        "text": "El momentum es negativo (-17.8% en el periodo analizado).",
        "evidenceIds": [
          "momentum"
        ]
      },
      {
        "text": "La tendencia es bajista. La media de 20 días (448.41) está por debajo de la media de 50 días (481.30). El precio está un 8.3% por debajo de la media de 20 días.",
        "evidenceIds": [
          "trend"
        ]
      }
    ],
    "counterpoints": [
      {
        "text": "Los fundamentales son positivos según 4 de 4 métricas.",
        "evidenceIds": [
          "fundamental"
        ]
      }
    ],
    "riskFactors": [
      {
        "text": "El bloque técnico es desfavorable mientras que los fundamentales son favorables.",
        "evidenceIds": [
          "finding.TECHNICAL_FUNDAMENTAL_DIVERGENCE"
        ]
      }
    ],
    "dataGaps": [],
    "limitations": [
      {
        "text": "Los precios y fundamentales proceden de un conjunto de datos de demostración sintético.",
        "evidenceIds": [
          "limitation.SYNTHETIC_DATA"
        ]
      },
      {
        "text": "Las reglas y umbrales son educativos. Describen datos pasados y no predicen rentabilidades.",
        "evidenceIds": [
          "limitation.NON_PREDICTIVE"
        ]
      }
    ]
  }
}
```

"Generated" shape (a **mocked** model response produced by the test helper, not Gemma output;
TSLA, English), showing how an accepted model output appears:

```json
{
  "schemaVersion": "1.0",
  "promptVersion": "narration-v1",
  "supervisorPolicyVersion": "phase3-v2",
  "status": "generated",
  "generationMode": "llm",
  "model": "test-model-id",
  "language": "en",
  "reason": null,
  "facts": {
    "recommendation": "SELL",
    "confidence": 0.86,
    "supervisorStatus": "consistent",
    "provenance": "synthetic",
    "isSimulated": true,
    "dataAsOf": "2026-09-30"
  },
  "report": {
    "title": "Report for TSLA",
    "overview": {
      "text": "The engine emits SELL; the confidence measures data coverage and the agreement of signals, it is not a probability. The data is synthetic demo data.",
      "evidenceIds": [
        "recommendation",
        "supervisor"
      ]
    },
    "supportingReasons": [
      {
        "text": "The evidence for this section is described in a qualitative way, with no figures.",
        "evidenceIds": [
          "momentum"
        ]
      },
      {
        "text": "The evidence for this section is described in a qualitative way, with no figures.",
        "evidenceIds": [
          "trend"
        ]
      },
      {
        "text": "The evidence for this section is described in a qualitative way, with no figures.",
        "evidenceIds": [
          "fundamental"
        ]
      }
    ],
    "counterpoints": [],
    "riskFactors": [
      {
        "text": "The evidence for this section is described in a qualitative way, with no figures.",
        "evidenceIds": [
          "risk"
        ]
      }
    ],
    "dataGaps": [],
    "limitations": [
      {
        "text": "The evidence for this section is described in a qualitative way, with no figures.",
        "evidenceIds": [
          "limitation.SYNTHETIC_DATA"
        ]
      },
      {
        "text": "The evidence for this section is described in a qualitative way, with no figures.",
        "evidenceIds": [
          "limitation.NON_PREDICTIVE"
        ]
      }
    ]
  }
}
```

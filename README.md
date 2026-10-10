# ATLAS AI

**Multi-Agent Investment Intelligence Platform** — a hackathon prototype that will
analyze US equities with specialized analysts and a supervisor, producing an
explainable report.

> **Current status: Phase 1 (base functional).** The analysis response is
> **simulated**. No real market data is used yet. The UI marks every simulated
> result clearly.

## Architecture

```
frontend/  Next.js + TypeScript + Tailwind   ──POST /api/analyze──▶  backend/  FastAPI
(UI: symbol input, loading, error, result)                          (validation + analysis service)
```

- **Frontend** (`frontend/`): single-page UI. It talks to the backend only through
  `lib/api.ts`. The backend URL comes from `NEXT_PUBLIC_API_URL`.
- **Backend** (`backend/`): FastAPI app. Layers:
  - `symbols.py` — ticker format validation.
  - `catalog.py` — local demo catalog of supported symbols (simulated).
  - `analysis.py` — analysis service. **Simulated in Phase 1.**
  - `schemas.py` — Pydantic models that define the API contract.
  - `main.py` — routes, CORS, error mapping.

### What is simulated vs. real (Phase 1)

| Part | Status |
| --- | --- |
| Symbol format validation | Real logic |
| Symbol existence check | **Simulated** — static demo catalog (`catalog.py`) |
| Company name | **Simulated** — from the demo catalog |
| Recommendation, confidence, signals, summary | **Simulated** — fixed placeholder values |
| API contract, error handling, UI states | Real |

Phase 2 replaces the catalog and analysis with market data and the technical,
risk and fundamental analyzers. Phase 3 adds the supervisor.

## Requirements

- Python 3.11+ (tested with 3.13)
- Node.js 20+ and npm (tested with Node 22)

## Installation

```bash
# Backend
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

## Running locally

Start the backend (port 8000):

```bash
cd backend
./.venv/bin/uvicorn app.main:app --reload --port 8000
```

Start the frontend (port 3000) in a second terminal:

```bash
cd frontend
npm run dev        # development
# or: npm run build && npm start   (production)
```

Open http://localhost:3000, enter a symbol (for example `NVDA`) and press **Analyze**.

### Configuration (optional)

- `backend/.env.example` → `ATLAS_CORS_ORIGINS` (default `http://localhost:3000`).
- `frontend/.env.example` → `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

Copy the example to `.env` / `.env.local` only if you need to change a value.
No credentials are required in Phase 1.

## Tests

```bash
cd backend
./.venv/bin/python -m pytest -q
```

Frontend checks:

```bash
cd frontend
npx tsc --noEmit
npm run lint
npm run build
```

## Endpoints

### `GET /health`

```json
{ "status": "ok", "service": "atlas-ai-backend" }
```

### `POST /api/analyze`

Request:

```json
{ "symbol": "NVDA" }
```

Success (`200`):

```json
{
  "symbol": "NVDA",
  "companyName": "NVIDIA Corporation",
  "recommendation": "HOLD",
  "confidence": 0.72,
  "summary": "Simulated analysis for Phase 1",
  "signals": { "momentum": "neutral", "risk": "moderate", "trend": "positive" },
  "isSimulated": true
}
```

Errors:

- `400` — malformed symbol or invalid request body.
- `404` — well-formed symbol that is not in the demo catalog.

Both use the same shape:

```json
{ "error": "Invalid stock symbol", "message": "Please provide a valid stock symbol." }
```

Symbols are trimmed and uppercased before validation, so `nvda` is accepted.

## Current limitations

- Analysis results are placeholders and do not reflect the market.
- Only a small fixed set of symbols is recognized (see `backend/app/catalog.py`).
- No market data provider, no historical prices, no indicators yet.
- No charts yet (Phase 4).
- No LLM integration (Phase 6, optional).
- The UI was verified by production build, typecheck and lint, and the API
  integration was verified with HTTP requests. Interactive browser testing of the
  UI has not been run.

## Next steps

1. **Phase 2 — analytical engine:** market data provider interface and demo dataset
   with provenance; technical, risk and limited fundamental analyzers returning
   structured results; tests for each analyzer.
2. **Phase 3 — supervisor:** rule-based validation, contradiction detection and an
   explainable conclusion.
3. **Phase 4 — dashboard:** price chart, indicators, agent cards and report panel.
4. **Phase 5 — validation:** integration tests, offline run, error hardening.
5. **Phase 6 — optional:** local Ollama explanations with deterministic fallback.

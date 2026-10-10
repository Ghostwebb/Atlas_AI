# Final frontend handoff (backend delivery)

Checked against the code of `feat/backend-delivery-ready`. Every example below is real output of
this code on the **synthetic demo dataset**.

The backend is complete for the demo, but the **product is not**:

- the visual integration still has to be done;
- real Gemma and real Alpaca Paper still need an explicit manual check.

## 1. Which backend to use

| Item | Value |
|---|---|
| Branch | `feat/backend-delivery-ready` (PR to `main`; not merged) |
| Base | `main` @ `e1294f8` (analysis, supervisor, Gemma report) |
| Incorporated | PR #3 `feat/phase-5-paper-trading` @ `cd951e7`; PR #7 `feat/phase-7-investment-agents` @ `fd24f75`; PR #8 `feat/phase-8-investment-committee` @ `fd81c05` (merge commits, history preserved) |
| Changed by the integration | Only conflict resolution (`backend/app/main.py` docstring, README lists), two test assertions made valid with paper routes present, a journey test file, this document |
| Not included | Any frontend. Frontend PRs #4 → #5 → #6 and the friend's `codex/agents-workspace` stay separate |

Code under `backend/app/paper`, `backend/app/agents`, `backend/app/committee`,
`backend/app/analysis`, `backend/app/supervision` and `backend/app/narration` is **identical** to
the reviewed commits (checked with `git diff`).

**Integration order for the last phase:**

1. Merge this PR (or PR #3, #7 and #8 in that order) into `main`.
2. Merge the frontend chain #4 → #5 → #6.
3. Open one coordinated PR that wires the friend's committee view to `/api/committee/analyze`.

## 2. Install and run (local only)

```bash
# Backend (terminal 1)
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --port 8000        # http://localhost:8000/health

# Frontend (terminal 2), once the frontend PRs are integrated
cd frontend && npm ci && npm run dev                  # http://localhost:3000
```

The backend has **no authentication**: never expose it or the app on the internet.

## 3. Environment variables (names only; never commit values)

The backend does not read `.env` by itself. Export the variables in the shell that runs uvicorn
(`set -a; source .env; set +a`). Template: `backend/.env.example`.

| Variable | Default | Effect |
|---|---|---|
| `ATLAS_CORS_ORIGINS` | `http://localhost:3000` | Browser origins. It is also the **Origin allow-list for paper POSTs** (otherwise 403 `ORIGIN_NOT_ALLOWED`) |
| `ATLAS_NARRATION_ENABLED` | `false` | `false` → `/api/report` is deterministic (`status: disabled`) |
| `ATLAS_LM_STUDIO_BASE_URL`, `ATLAS_LM_STUDIO_MODEL`, `ATLAS_LM_STUDIO_TIMEOUT_SECONDS`, … | loopback, empty, 45 | Local LM Studio (Gemma). Loopback URLs only |
| `ATLAS_PAPER_TRADING_ENABLED` | `false` | `false` → `/api/paper/*` never calls Alpaca or opens the database |
| `ATLAS_ALPACA_PAPER_API_KEY`, `ATLAS_ALPACA_PAPER_SECRET_KEY` | empty | **Backend only.** Paper keys; live `AK…` keys are rejected |
| `ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD`, `ATLAS_PAPER_PROPOSAL_TTL_SECONDS`, `ATLAS_PAPER_DATABASE_PATH` | 1000, 300, `backend/var/…` | Limits and local SQLite |
| `NEXT_PUBLIC_API_URL` (frontend) | `http://localhost:8000` | The only frontend setting. **No secrets in the frontend** |

## 4. Routes (all JSON; symbol routes accept only `{"symbol": "..."}`)

| Route | Body | Success | Errors |
|---|---|---|---|
| `GET /health` | — | `{"status":"ok","service":"atlas-ai-backend"}` | — |
| `POST /api/analyze` | `{symbol}` | Engine analysis + `supervision` | 400 invalid / extra fields, 404 unknown, 500 integrity |
| `POST /api/agents/analyze` | `{symbol}` | `agents.v1.1`: shared `snapshot` + 4 `evaluations` | same |
| `POST /api/committee/analyze` | `{symbol}` | `committee.v1`: `agents` (identical to the route above) + `committee` | same |
| `POST /api/report` | `{symbol, language: "es"\|"en"}` | `{analysis, narrative}` | same |
| `/api/paper/*` | see `docs/phase-6-integration-handoff.md` §4 | Paper Trading lab | Paper error envelope `{error, message, code, correlationId, proposalId}` |

- Symbols are normalized (trim + uppercase).
- Symbol-route errors use `{error, message}`.
- Demo symbols: AAPL, MSFT, NVDA, TSLA, AMZN, GOOGL, META.

### Real examples (synthetic data)

`/api/analyze` NVDA:
`{"symbol":"NVDA","recommendation":"BUY","confidence":0.45,"isSimulated":true,"dataSource":"demo_dataset","dataAsOf":"2026-09-30"}`,
`supervision.status: "caution"`.

`/api/agents/analyze` NVDA (version 1.0.1 for all):

| strategyId | name | style | status | stance | score | coverage |
|---|---|---|---|---|---|---|
| argo | ARGO | value | complete | neutral | -0.2 | 1.0 |
| nova | NOVA | growth | complete | favorable | 1.0 | 1.0 |
| vector | VECTOR | momentum | complete | favorable | 0.85 | 1.0 |
| aegis | AEGIS | defensive | complete | neutral | -0.2 | 1.0 |

`/api/committee/analyze` NVDA:

- `state: "caution"`, `rulesApplied: ["unmet:R6","unmet:R7","unmet:R9"]`;
- summary: "Favorable reading from NOVA, VECTOR, with unmet requirements: R6, R7, R9.";
- every participant has `participates: true`.

Committee states on the 7 symbols:

| AAPL | MSFT | NVDA | TSLA | AMZN | GOOGL | META |
|---|---|---|---|---|---|---|
| neutral | neutral | caution | aligned_unfavorable | aligned_unfavorable | neutral | conflicted |

**Important for the UI:** the engine's `recommendation` (`/api/analyze`, e.g. NVDA `BUY`) is the
Phase 2 aggregate label, while the committee reads NVDA as `caution`. They are different readings,
and neither is an order. Never render either as a trade button.

## 5. Agents → visual profiles

| `strategyId` | Profile in `codex/agents-workspace` (`agents-data.ts`) | What it really evaluates |
|---|---|---|
| `argo` | ARGO, value | **A limited P/E lens** (P/E, margin, value-trap check). No intrinsic value or margin of safety |
| `nova` | NOVA, growth | Single-period revenue and earnings growth, margin |
| `vector` | VECTOR, momentum | 60/20-bar returns, moving-average alignment, volume; risks shown separately |
| `aegis` | AEGIS, defensive | Observed volatility and drawdowns; **a risk gate, never "safe"** |

For each evaluation:

- show `stance` together with `stanceMeaning` (never "Comprar" or "Esperar");
- show `status`, `coverage` (scored criteria only) and `score` (only when not null);
- show `evidence.{favorable, unfavorable, neutral}`, `notEvaluated` (with `reason`), `risks`, `risksNotEvaluated`, `missingData` and `limitations`;
- explain an unavailable metric with `snapshot.metrics.<id>.status` and `issue`. **Never display null as 0.**

## 6. Committee display

- **Replace the authored fixture `Decision`** with `committee.conclusion`: `state`, `summary`, the `requirements` with `met`, and `conditions`.
- **There is no `selectedAgentId`:** the committee never picks a winning agent, so do not derive one from scores.
- **Disagreements:** `conflicts[]` with `kind` and `level` (`stance`, `criterion` or `risk`). `agreements[]` with `independentBases`.
- **Abstentions:** `abstentions[]`, with `causes`. An abstention is not neutral.
- **Evidence:** `arguments` / `counterpoints`, `observedRisks`, `riskProfile` (AEGIS, "not safety"), `unevaluatedRisks` ("not evaluated ≠ no risk"), `missingData`, `sharedEvidence` (one fact cited by several agents) and `limitations`.
- **References:** every `references[].path` (`agents.snapshot.metrics.<id>`) resolves inside the same response. Show its `value` with its `unit` (decimals as %).
- **Always visible:** `notice` and `committee.conclusion.notice`.

## 7. What `/api/report` produces, and what it does not

- **Produces:** a narrative of the **engine analysis and its Phase 3 supervisor** (`narrative.report`: title, overview, supportingReasons, counterpoints, riskFactors, dataGaps, limitations), in `es` or `en`.
  - With LM Studio enabled and reachable → `status: "generated"`, `generationMode: "llm"`, after strict validation.
  - Otherwise → the deterministic report: `status: "disabled"` (`MODEL_DISABLED`) or `"fallback"` (`MODEL_UNAVAILABLE`, `MODEL_TIMEOUT`, `MODEL_BUSY` or `INVALID_MODEL_OUTPUT`).
- **Does not produce:**
  - it does **not** narrate the agents or the committee, so do not label it "informe del comité";
  - it never creates proposals or orders (tested).

## 8. Paper Trading (unchanged from PR #3 `cd951e7`)

The frontend controller of PR #5/#6 consumes this contract unchanged. The full contract is in
`docs/phase-6-integration-handoff.md`: states §5, errors §6, **polling §7**, invariants §8.

- **Polling:**
  - **`GET /api/paper/proposals/{id}` reads local state only**; it never discovers fills;
  - with a `brokerOrderId`, follow `GET /api/paper/orders/{orderId}`;
  - for `submission_unknown` or `submitting`, use `POST /api/paper/proposals/{id}/reconcile` (lease 120 s, `SUBMISSION_IN_PROGRESS`), which never resends;
  - 2–5 s with backoff up to 30 s, never overlapping, and stop on a final status;
  - `pending_cancel` is **not** final.
- **Confirmation:** `{"confirmation":"CONFIRM_PAPER_ORDER"}` from an explicit human click only. Cancel uses `{"confirmation":"CANCEL_PAPER_ORDER"}`.
- **Safeguards unchanged:** reservations, fill ledger, v5 migration, no resubmission and uncertainty handling. The database is never reset and the audit trail is never deleted.

## 9. Mandatory notices and error states

- **Notices:**
  - every paper screen: **"Paper Trading — dinero ficticio"**;
  - analysis, agents, committee and report: synthetic demo data (`isSimulated`, `provenance: "synthetic"`, `notice`).
- **Paper status** (`GET /api/paper/status`):
  - `enabled: false` → "Deshabilitado";
  - `configured: false` → "Sin configurar";
  - `brokerReachable: false` → "Alpaca inaccesible";
  - `marketOpen: false` → "Mercado cerrado".
  - **Never invent an account** when the backend fails.
- **Errors:** show `message` plus `code` and `correlationId` when present. Covered codes:
  - `PAPER_DISABLED`, `PAPER_NOT_CONFIGURED`, `BROKER_UNAVAILABLE`, `MARKET_CLOSED`;
  - `RESOURCE_RESERVED`, `RECONCILIATION_REQUIRED`, `PROPOSAL_EXPIRED`, `BROKER_REJECTED`;
  - `SUBMISSION_UNCERTAIN` / `SUBMISSION_IN_PROGRESS` → "Consultar estado" only; never a resend button;
  - `ORIGIN_NOT_ALLOWED`;
  - 500 integrity errors on analysis, agents and committee.

## 10. Available, limited, not implemented

| Available | Limited | Not implemented |
|---|---|---|
| Deterministic analysis + supervisor; 4 strategy evaluations; deterministic committee; report with deterministic fallback; paper prepare/confirm/read/reconcile/cancel | Synthetic, undated data; ARGO = P/E lens; AEGIS single-symbol; report narrates analysis only; paper needs the user's keys and an open market | Real market data, intrinsic valuation/DCF, portfolio/objective, committee-driven or automatic trading, WebSockets, authentication, public hosting |

## 11. Demo script (short and reproducible)

1. Start the backend (narration and paper disabled) and the frontend. `GET /health` → ok.
2. **Analysis:** analyze `NVDA`. Point out "datos sintéticos" and the supervision status.
3. **Agents:** show ARGO neutral, NOVA and VECTOR favorable, AEGIS neutral, with evidence and units.
4. **Committee:** NVDA → `caution`. Explain the unmet R6 (volatility), R7 (risk flag) and R9 (P/E 44, unfavorable). Then META → `conflicted` (growth vs momentum).
5. **Report:** with narration disabled it shows the deterministic report. Say "Gemma disabled → deterministic report".
6. **Paper Trading:** show the visible state ("Deshabilitado" or "Sin configurar"). Do not show an invented account.

Honest alternatives:

- **Gemma not available:** the report shows `fallback` / `MODEL_UNAVAILABLE` and the analysis stays. This was verified on a live server with LM Studio unreachable.
- **Alpaca not configured:** `status.configured: false` and proposals return 503 `PAPER_NOT_CONFIGURED`. Verified live.
- **Market closed:** prepare and confirm both check the regular session and return `MARKET_CLOSED` (409). **The hackathon is on a weekend, so the US market is closed and no paper order can be confirmed under the current policy.** Do not promise an executable order without checking account and hours first.
- **Fixtures:** only in automated tests (`backend/tests/paper_fakes.py`, frontend `e2e`), or in a demo explicitly labelled as simulated. Never present them as a real Alpaca connection.

## 12. Verification of this branch

- **Integrated suite (one run on this branch): 810 passed.** It uses simulated transports only: mocked LM Studio, test FakeBroker.
- **`tests/test_delivery_journey.py`** covers:
  - health and symbol errors on every route;
  - analysis → agents → committee on one synthetic snapshot;
  - deterministic report, and model failure → fallback;
  - paper disabled and not configured;
  - prepare → explicit confirm → read → cancel, and uncertain → reconcile without resend;
  - invalid prices → no favorable conclusion;
  - analysis, agents, committee and report never touching paper.
- **Live server checks** (uvicorn on this branch, no external services) are separate from those tests:
  - health, analyze 200/404, agents (normalized symbol, extra field 400), committee (META `conflicted`, invalid 400);
  - report `disabled`, and `fallback` / `MODEL_UNAVAILABLE` with LM Studio unreachable;
  - paper status `enabled: false`, proposals 503 `PAPER_DISABLED`;
  - with paper enabled and no keys: `PAPER_NOT_CONFIGURED`, and `ORIGIN_NOT_ALLOWED` without an Origin header;
  - CORS preflight from `http://localhost:3000` allowed.
- **Not verified here:** real Gemma (the user reported real reports earlier; not reproduced in this environment) and a real Alpaca Paper account (needs the user's keys, an open market and explicit authorization).

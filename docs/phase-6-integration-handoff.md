# Phase 6: integration handoff (backend → frontend)

Contract of the backend as implemented on `feat/phase-5-paper-trading` (PR #3), for integrating the
approved frontend (PR #4) and the paper trading UI. Everything below is checked against the code
(`backend/app/paper/*`, `backend/app/main.py`). **Nothing here is implemented in the frontend yet,
and nothing has been validated against real Alpaca Paper or a real Gemma model.**

## 1. Branches and order of work

| Branch | State when written | Content |
|---|---|---|
| `feat/phase-5-paper-trading` (PR #3) | open, pending Codex review | paper trading backend (5 → 5.8) |
| `feat/frontend-approved-design` (PR #4, `fbf3ae3`) | open | approved dashboard + report panel; no paper UI |
| `feat/paper-ui` | **not on GitHub yet** | friend's work in `frontend/components/paper/` |

Suggested order once reviewed:
1. Merge PR #3 (backend).
2. Merge PR #4 (frontend base).
3. Rebase `feat/paper-ui` on `main` and open its PR.

Shared dashboard files (`frontend/app/page.tsx`, `globals.css`, `frontend/lib/*`) change only
through reviewed PRs. Nobody rebases someone else's branch.

## 2. Local configuration

The backend does **not** read `.env` by itself. Export the variables in the shell that starts
uvicorn, or run `set -a; source .env; set +a`. Names only, never commit values:

| Variable | Default | Purpose |
|---|---|---|
| `ATLAS_CORS_ORIGINS` | `http://localhost:3000` | Browser origins; also the allow-list for paper POSTs (Origin check) |
| `ATLAS_PAPER_TRADING_ENABLED` | `false` | When false: no Alpaca call, no database |
| `ATLAS_ALPACA_PAPER_API_KEY`, `ATLAS_ALPACA_PAPER_SECRET_KEY` | empty | Paper keys, **backend only** (live `AK…` keys are rejected) |
| `ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD` | `1000` | Per-buy limit (1–100000) |
| `ATLAS_PAPER_PROPOSAL_TTL_SECONDS` | `300` | Proposal lifetime (30–3600) |
| `ATLAS_PAPER_DATABASE_PATH` | `backend/var/paper_trading.sqlite3` | Local SQLite (git-ignored) |
| `ATLAS_PAPER_ALLOW_REQUESTS_WITHOUT_ORIGIN` | `false` | Only for curl tests |
| `ATLAS_NARRATION_ENABLED`, `ATLAS_LM_STUDIO_*` | disabled | Report narrative (see `docs/phase-4-narration.md`) |
| `NEXT_PUBLIC_API_URL` (frontend) | `http://localhost:8000` | Backend URL; the only frontend setting |

The Alpaca endpoint is fixed to `https://paper-api.alpaca.markets`. A live URL in `APCA_API_BASE_URL`
or `ATLAS_ALPACA_BASE_URL` stops the server. **The frontend never sees or sends credentials**; it
only calls the ATLAS backend.

## 3. Synthetic analysis vs paper account

| Data | Source | How the UI must label it |
|---|---|---|
| `/api/analyze`, `/api/report` | Synthetic demo dataset | "Datos sintéticos de demostración" (`isSimulated: true`, `facts.provenance: "synthetic"`) |
| `/api/paper/*` | Alpaca **Paper** account (simulated money) | Permanent "Paper Trading — dinero ficticio" |

- Never show synthetic prices next to paper orders.
- Never estimate shares or prices: there is no reference quote.
- Never create a proposal from a BUY/SELL recommendation: the user chooses side and amount.
- `/api/analyze` and `/api/report` never call the broker (tested).

## 4. Endpoints

All paper routes are under `/api/paper`.
- **Amounts and quantities** are **decimal strings** in requests and responses. JSON numbers are
  rejected.
- **POST requests** need an `Origin` header listed in `ATLAS_CORS_ORIGINS`. Browsers send it
  automatically.
- **Every error** carries `X-Correlation-Id`.

| Method | Path | Body | Success | Notes |
|---|---|---|---|---|
| GET | `/status` | — | 200 `PaperStatus` | No broker call when disabled; otherwise reads the Alpaca clock |
| GET | `/account` | — | 200 `Account` | |
| GET | `/positions` | — | 200 `Position[]` | |
| GET | `/clock` | — | 200 `Clock` | |
| POST | `/proposals` | `{symbol, side:"buy", notional}` or `{symbol, side:"sell", qty}`, optional `analysisReference` | **201** `Proposal` | Validates, persists, **never submits**, reserves nothing |
| GET | `/proposals/{id}` | — | 200 `Proposal` | Marks it `expired` when due |
| POST | `/proposals/{id}/confirm` | `{"confirmation":"CONFIRM_PAPER_ORDER"}` exactly | 200 `Proposal` | Re-validates, reserves, submits at most once |
| POST | `/proposals/{id}/reconcile` | none | 200 `Proposal` | Read-only lookup at Alpaca; never resubmits |
| GET | `/orders?status=open\|closed\|all&limit=1..100` | — | 200 `BrokerOrder[]` | Defaults: `all`, 50 |
| GET | `/orders/{orderId}` | — | 200 `BrokerOrder` | Updates the linked proposal and reservation |
| POST | `/orders/{orderId}/cancel` | `{"confirmation":"CANCEL_PAPER_ORDER"}` exactly | 200 `{cancelRequested: true, order}` | `order.status` is Alpaca's current status (`pending_cancel` ≠ `canceled`) |

Request rules:
- buy → `notional`: ≤ 2 decimals, ≥ 1.00, ≤ the limit.
- sell → `qty`: ≤ 9 decimals, > 0.
- No extra fields; no `type`, `extended_hours` or URL fields.
- `symbol` uses the same format as `/api/analyze`.
- `analysisReference` is `[A-Za-z0-9._:@-]{1,64}`.
- Market orders with `time_in_force=day`, regular session only.

### Response shapes (real output with the test fake broker)

`PaperStatus`:
```json
{
  "environment": "paper",
  "enabled": true,
  "configured": true,
  "brokerReachable": true,
  "marketOpen": true,
  "maxOrderNotionalUsd": "1000",
  "proposalTtlSeconds": 300,
  "analysisDataNotice": "ATLAS analysis uses a synthetic demo dataset. It is not market data and is not linked to paper orders, balances or prices.",
  "message": "Connected to Alpaca Paper."
}
```

`Account` and `Position[]`:
```json
{
  "environment": "paper",
  "status": "ACTIVE",
  "currency": "USD",
  "cash": "1000",
  "buyingPower": "1000",
  "nonMarginableBuyingPower": "1000",
  "equity": "100000",
  "tradingBlocked": false,
  "accountBlocked": false
}
```
```json
[
  {
    "environment": "paper",
    "symbol": "NVDA",
    "side": "long",
    "qty": "2",
    "qtyAvailable": "2",
    "avgEntryPrice": "100",
    "marketValue": "500",
    "assetClass": "us_equity"
  }
]
```

`Proposal` after confirmation (the `checks` list is shortened here):
```json
{
  "id": "f2406d492a234150a1b55f42213afdb5",
  "environment": "paper",
  "symbol": "NVDA",
  "side": "buy",
  "notional": "100.00",
  "qty": null,
  "orderType": "market",
  "timeInForce": "day",
  "clientOrderId": "atlas-f2406d492a234150a1b55f42213afdb5",
  "analysisReference": null,
  "createdAt": "2026-10-05T15:00:00.000000+00:00",
  "expiresAt": "2026-10-05T15:05:00.000000+00:00",
  "status": "confirmed",
  "submissionStatus": "submitted",
  "brokerOrderId": "e5cada46-bc39-4ebe-b78d-1aec343a423e",
  "brokerStatus": "accepted",
  "filledQty": "0",
  "filledAvgPrice": null,
  "lastErrorCode": null,
  "checks": [
    {
      "name": "account_tradable",
      "passed": true,
      "detail": "paper account active, not blocked"
    },
    {
      "name": "market_open",
      "passed": true,
      "detail": "regular session open"
    },
    "…"
  ],
  "warnings": [
    "Paper trading: simulated money in an Alpaca Paper account.",
    "Market order: the execution price is not known in advance and is not guaranteed.",
    "Preparing does not reserve funds or shares; confirmation re-checks them and Alpaca may still reject the order.",
    "ATLAS analysis uses a synthetic demo dataset. It is not market data and is not linked to paper orders, balances or prices."
  ],
  "updatedAt": "2026-10-05T15:00:00.000000+00:00",
  "reservation": {
    "resourceType": "cash",
    "symbol": null,
    "amount": "100.00",
    "consumed": "0",
    "state": "acknowledged",
    "releaseReason": null,
    "filledQty": "0",
    "filledNotional": "0"
  }
}
```

`proposal.reservation` after a partial fill and a final cancel (pending part freed, executed part kept):
```json
{
  "resourceType": "cash",
  "symbol": null,
  "amount": "100.00",
  "consumed": "50.0",
  "state": "released",
  "releaseReason": "order_terminal",
  "filledQty": "0.5",
  "filledNotional": "50.0"
}
```

`BrokerOrder` (partial fill) and the cancel response:
```json
{
  "id": "e5cada46-bc39-4ebe-b78d-1aec343a423e",
  "clientOrderId": "atlas-f2406d492a234150a1b55f42213afdb5",
  "symbol": "NVDA",
  "side": "buy",
  "type": "market",
  "timeInForce": "day",
  "qty": null,
  "notional": "100.00",
  "filledQty": "0.5",
  "filledAvgPrice": "100",
  "status": "partially_filled",
  "brokerStatusRaw": "partially_filled",
  "submittedAt": "2026-10-05T15:00:01Z",
  "filledAt": null,
  "canceledAt": null,
  "proposalId": "f2406d492a234150a1b55f42213afdb5",
  "environment": "paper"
}
```
```json
{
  "cancelRequested": true,
  "order": {
    "id": "e5cada46-bc39-4ebe-b78d-1aec343a423e",
    "clientOrderId": "atlas-f2406d492a234150a1b55f42213afdb5",
    "symbol": "NVDA",
    "side": "buy",
    "type": "market",
    "timeInForce": "day",
    "qty": null,
    "notional": "100.00",
    "filledQty": "0.5",
    "filledAvgPrice": "100",
    "status": "pending_cancel",
    "brokerStatusRaw": "pending_cancel",
    "submittedAt": "2026-10-05T15:00:01Z",
    "filledAt": null,
    "canceledAt": null,
    "proposalId": "f2406d492a234150a1b55f42213afdb5",
    "environment": "paper"
  }
}
```

Error envelope (every error):
```json
{
  "error": "Paper trading state conflict",
  "message": "Recent executions are not yet reflected in the broker balance or position. Check the order status and try again.",
  "code": "RECONCILIATION_REQUIRED",
  "correlationId": "3d149542c7dc4e26b5e5ceae8c3f9070",
  "proposalId": null
}
```

## 5. States and allowed actions

Three separate lifecycles: proposal `status`, local `submissionStatus` and Alpaca `brokerStatus`.
The reservation `state` is a fourth.

| Field | Values |
|---|---|
| `status` | `open` → `confirmed` \| `expired` |
| `submissionStatus` | `not_submitted`, `submitting`, `submitted`, `submission_unknown`, `rejected_by_broker`, `failed_before_submit` |
| `brokerStatus` | Alpaca: `new`, `accepted`, `pending_new`, `accepted_for_bidding`, `partially_filled`, `filled`, `done_for_day`, `pending_cancel`, `canceled`, `expired`, `rejected`, `replaced`, `pending_replace`, `stopped`, `suspended`, `calculated`, plus `unrecognized` |
| final broker statuses | `filled`, `canceled`, `expired`, `rejected` |
| `reservation.state` | `held` (local, not acknowledged), `acknowledged` (open at Alpaca), `released` (`not_sent`, `broker_rejected`, `order_terminal`) |

| Situation | Confirm | Check status (`/reconcile`, GET) | Cancel |
|---|---|---|---|
| `open` + `not_submitted`, before `expiresAt` | **yes** (explicit button) | GET | no order yet |
| `open` + `failed_before_submit` (never reached Alpaca) | **yes**, same `clientOrderId` | GET | no |
| `expired` | no (prepare a new one) | GET | no |
| `confirmed` + `submitting` | no (`SUBMISSION_IN_PROGRESS`) | yes, poll; reconcile returns 409 until the 120 s lease ends | no |
| `confirmed` + `submission_unknown` | **never** (no resend) | **yes**: show "Consultar estado" | no |
| `confirmed` + `submitted`, broker status not final | repeat returns the same proposal | yes, poll | **yes** (explicit button) |
| `confirmed` + `submitted`, final broker status | — | GET | no (409 `ORDER_NOT_CANCELABLE`) |
| `confirmed` + `rejected_by_broker` | repeat returns 422 `BROKER_REJECTED` | GET | no |

The server enforces every row. The UI must not show forbidden actions, but it must still handle
the error codes.

## 6. Errors and what the UI does

| Code | HTTP | Meaning | UI |
|---|---|---|---|
| `INVALID_REQUEST`, `INVALID_CONFIRMATION` | 400 | Malformed body or parameters | Fix the form; never retry blindly |
| `ORIGIN_NOT_ALLOWED` | 403 | Origin missing or not allowed | Configuration problem; show the message |
| `PROPOSAL_NOT_FOUND`, `ORDER_NOT_FOUND` | 404 | Unknown id | Return to the list |
| `MARKET_CLOSED` | 409 | Regular session closed | Show `/clock` `nextOpen` |
| `PROPOSAL_EXPIRED` | 409 | TTL passed before confirmation | Offer "Preparar de nuevo" |
| `SUBMISSION_IN_PROGRESS` | 409 | Another confirmation is sending it | Disable controls, poll the proposal |
| `SUBMISSION_UNCERTAIN` | 409 | Result unknown (`submission_unknown`) | "Estado incierto": **only** "Consultar estado"; never resend |
| `RESOURCE_RESERVED` | 409 | Another pending ATLAS order holds the shares or budget | "Hay acciones comprometidas por otra orden" / "Hay presupuesto reservado por una operación pendiente"; link to that order |
| `RECONCILIATION_REQUIRED` | 409 | One of three causes (`message` tells which): (1) an uncertain earlier order blocks the resource; (2) recent executions not yet reflected by Alpaca's balance/position; (3) the measure is unverifiable after a migration | "Debes consultar el estado antes de intentar otra operación". (1) → "Consultar estado" on the uncertain proposal; (2) → retry later; (3) → see `docs/phase-5-paper-trading.md` recovery. No override button |
| `ORDER_NOT_CANCELABLE` | 409 | Already final | Refresh the order |
| `ACCOUNT_NOT_TRADABLE`, `ASSET_NOT_SUPPORTED`, `FRACTIONAL_NOT_SUPPORTED`, `ORDER_LIMIT_EXCEEDED`, `INSUFFICIENT_BUYING_POWER`, `INSUFFICIENT_POSITION`, `BROKER_REJECTED` | 422 | Business rule | Show the message; adjust the amount |
| `PAPER_DISABLED`, `PAPER_NOT_CONFIGURED`, `BROKER_UNAVAILABLE` | 503 | Feature off, keys missing, Alpaca unreachable | Show the state; manual retry |

Show `message` and `correlationId` on every error.

## 7. Polling policy

- No WebSockets. Poll `GET /proposals/{id}` (or `/orders/{orderId}`) every **2–5 s** while
  `submissionStatus` is `submitting`/`submission_unknown`, or while the broker status is not
  final. Stop on a final status.
- `submission_unknown`: poll **and** offer "Consultar estado" (`POST /reconcile`). Never re-confirm
  as a polling mechanism.
- `/status` calls Alpaca's clock on every request. Call it on page load, then at most every 30 s.
- Back off (for example ×2 up to 30 s) on `BROKER_UNAVAILABLE`.
- `pending_cancel` is not `canceled`: keep polling.

## 8. UI invariants (must hold)

- A permanent label on every paper screen: **"Paper Trading — dinero ficticio"**.
- Preparing a proposal never sends an order; the review screen shows `checks`, `warnings` and the
  `expiresAt` countdown.
- One explicit human confirmation button sending `CONFIRM_PAPER_ORDER`. All controls are disabled
  while the request is in flight.
- An uncertain state is visible, with "Consultar estado" only and never a resend.
- Cancelling requires its own explicit button (`CANCEL_PAPER_ORDER`). Show the returned status.
- Generating a report (`/api/report`) never creates, confirms or cancels anything.
- Credentials live only in the backend environment.

## 9. Integration test scenarios (simulated broker)

The simulated broker (`backend/tests/paper_fakes.py`) is **test-only**. The running server has no
fake-broker mode; adding one would be a new Phase 6 decision. Until then the frontend can test
with HTTP fixtures built from the shapes above, and the backend behavior is covered by these tests:

| Scenario | Expected HTTP sequence | Backend test |
|---|---|---|
| Happy path buy | 201 create → 200 confirm (`submitted`) → poll GET → `filled` | `test_paper_api.py::test_full_flow_over_http` |
| Paper disabled | 503 `PAPER_DISABLED`, `/status` `enabled:false` | `test_default_server_is_disabled_and_makes_no_calls` |
| Invalid amounts or extra fields | 400 `INVALID_REQUEST`, no broker call | `test_invalid_requests_are_rejected_without_calls` |
| Missing or foreign Origin | 403 `ORIGIN_NOT_ALLOWED` | `test_mutations_require_allowed_origin` |
| Insufficient buying power or shares | 422 | `test_paper_service.py` (buying power / position tests) |
| Two proposals for the same share | one 200, one 409 `RESOURCE_RESERVED` | `test_paper_reservations.py::test_1_2_…` |
| Uncertain submission | 409 `SUBMISSION_UNCERTAIN`; reconcile 409 until found, then 200 `submitted` | `test_reconcile_by_client_order_id_once_order_appears` |
| Executions not reflected | 409 `RECONCILIATION_REQUIRED`, then allowed when the broker catches up | `test_paper_consumption.py::test_open_acknowledged_order_with_unreflected_fill_then_broker_catches_up` |
| Expired proposal | 409 `PROPOSAL_EXPIRED` | `test_expired_proposal_is_not_submitted` |
| Cancel pending → canceled | 200 `pending_cancel`, then poll → `canceled` | `test_8_pending_cancel_keeps_shares_until_cancel_is_final` |
| Cancel loses the race | 200 with `filled` | `test_cancel_racing_with_fill_reports_fill` |
| Report creates no order | `/api/report` 200, zero broker calls | `test_analysis_and_report_make_no_broker_calls` |

## 10. Limitations and pending items

- **Not validated:** a real Alpaca Paper account (needs the user's paper keys and explicit
  confirmation; script `backend/scripts/manual_alpaca_paper_check.py`) and a real Gemma model.
- **No authentication.** Local use only; the Origin check is not authentication.
- **No reference quote.** No price or share estimates; sells are bounded by the position, not by USD.
- **Single client.** The fill ledger assumes ATLAS is the only client trading the account. External
  increases are not used once ATLAS has filled on that measure (conservative).
- **Migrated databases.** Local databases written by 5.5–5.7 code may have unverifiable measures
  (`RECONCILIATION_REQUIRED`); recovery is manual and documented.
- **No contract changes in Phase 5.8.** The only additions are the data migration and the
  `checkpoint_distrusted` audit event.

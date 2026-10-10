# Phase 6: integration handoff (backend → frontend)

Contract of the backend as implemented on `feat/phase-5-paper-trading` (PR #3), for integrating the
approved frontend (PR #4) and the paper trading UI. Everything below is checked against the code
(`backend/app/paper/*`, `backend/app/main.py`). **Nothing here is implemented in the frontend yet,
and Alpaca Paper has not been validated with a real account.** Evidence about the real model is
described in section 11.

## 1. Branches and order of work

| Branch | State when written | Content |
|---|---|---|
| `feat/phase-5-paper-trading` (PR #3) | open, pending Codex review | paper trading backend (5 → 5.8) |
| `feat/frontend-approved-design` (PR #4, `fbf3ae3`) | open | approved dashboard + report panel; no paper UI |
| `feat/paper-ui` | **not on GitHub** when checked | friend's local work; content not verified |

### Who does what in Phase 6

| Who | Owns |
|---|---|
| Friend | Design, dashboard, navigation, styles and visual components of the frontend |
| Codex (user's side) | An independent technical integration: Paper Trading API client and types; prepare, confirm, read and cancel logic; order tracking and uncertain states (section 7); tests with HTTP fixtures |
| Claude | Backend and documentation (this branch) |

The visual integration is done at the end through one **coordinated PR** that wires Codex's logic
into the friend's components. No folder is declared free here: where Codex's code lives is agreed
with the friend first.

### Collaboration rules

- Separate branches and separate checkouts (or worktrees) for each person.
- Never edit, rebase or force-push someone else's branch.
- Do not modify `frontend/app/page.tsx`, `frontend/app/layout.tsx`, `frontend/app/globals.css`,
  visual components or other shared files without agreeing it first.
- The integration logic does not wait for the design: it is developed and tested in isolation
  (pure functions plus a client), against HTTP fixtures.
- No PR is merged automatically; the user merges after review. Suggested order: PR #3 (backend),
  PR #4 (frontend base), then the paper UI and integration PRs, each rebased by its own author.
- The frontend never receives credentials (section 2).
- The running server has **no simulated-broker mode**. Frontend tests use HTTP fixtures built from
  section 4; they must not present a fixture or a fictitious account as a real connection.

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
| GET | `/proposals/{id}` | — | 200 `Proposal` | **Local read only (SQLite).** Never calls Alpaca, never discovers fills; marks it `expired` when due |
| POST | `/proposals/{id}/confirm` | `{"confirmation":"CONFIRM_PAPER_ORDER"}` exactly | 200 `Proposal` | Re-validates, reserves, submits at most once |
| POST | `/proposals/{id}/reconcile` | none | 200 `Proposal` | Read-only lookup at Alpaca (by `brokerOrderId`, else by `clientOrderId`); never resubmits. 409 `SUBMISSION_IN_PROGRESS` while the submit lease is live; 409 `SUBMISSION_UNCERTAIN` if an uncertain order is still not found |
| GET | `/orders?status=open\|closed\|all&limit=1..100` | — | 200 `BrokerOrder[]` | Defaults: `all`, 50 |
| GET | `/orders/{orderId}` | — | 200 `BrokerOrder` | Reads Alpaca and updates the linked proposal and reservation (if `submitted` or `submission_unknown`) |
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

| Situation | Confirm | How to refresh from Alpaca | Cancel |
|---|---|---|---|
| `open` + `not_submitted`, before `expiresAt` | **yes** (explicit button) | nothing to refresh (GET proposal for expiry) | no order yet |
| `open` + `failed_before_submit` (never reached Alpaca) | **yes**, same `clientOrderId` | nothing to refresh | no |
| `expired` | no (prepare a new one) | — | no |
| `confirmed` + `submitting` | no (`SUBMISSION_IN_PROGRESS`) | `POST /reconcile` with backoff: 409 `SUBMISSION_IN_PROGRESS` until the 120 s lease ends, then a read-only lookup | no |
| `confirmed` + `submission_unknown` (no `brokerOrderId`) | **never** (no resend) | "Consultar estado" → `POST /reconcile` | no |
| `confirmed` + `submitted`, broker status not final (incl. `pending_cancel`) | repeat returns the same proposal | poll `GET /orders/{brokerOrderId}` | **yes** (explicit button; hide it while `pending_cancel`) |
| `confirmed` + `submitted`, final broker status | — | stop polling | no (409 `ORDER_NOT_CANCELABLE`) |
| `confirmed` + `rejected_by_broker` | repeat returns 422 `BROKER_REJECTED` | — (final) | no |

The server enforces the confirm, resend and cancel rules through the error codes in section 6.
The UI must not show forbidden actions, but it must still handle those codes.

## 6. Errors and what the UI does

| Code | HTTP | Meaning | UI |
|---|---|---|---|
| `INVALID_REQUEST`, `INVALID_CONFIRMATION` | 400 | Malformed body or parameters | Fix the form; never retry blindly |
| `ORIGIN_NOT_ALLOWED` | 403 | Origin missing or not allowed | Configuration problem; show the message |
| `PROPOSAL_NOT_FOUND`, `ORDER_NOT_FOUND` | 404 | Unknown id | Return to the list |
| `MARKET_CLOSED` | 409 | Regular session closed | Show `/clock` `nextOpen` |
| `PROPOSAL_EXPIRED` | 409 | TTL passed before confirmation | Offer "Preparar de nuevo" |
| `SUBMISSION_IN_PROGRESS` | 409 | A confirmation holds a live submit lease (120 s) | Disable controls; retry `POST /reconcile` with backoff (section 7) |
| `SUBMISSION_UNCERTAIN` | 409 | Result unknown (`submission_unknown`) | "Estado incierto": **only** "Consultar estado"; never resend |
| `RESOURCE_RESERVED` | 409 | Another pending ATLAS order holds the shares or budget | "Hay acciones comprometidas por otra orden" / "Hay presupuesto reservado por una operación pendiente"; link to that order |
| `RECONCILIATION_REQUIRED` | 409 | One of three causes (`message` tells which): (1) an uncertain earlier order blocks the resource; (2) recent executions not yet reflected by Alpaca's balance/position; (3) the measure is unverifiable after a migration | "Debes consultar el estado antes de intentar otra operación". (1) → "Consultar estado" on the uncertain proposal; (2) → retry later; (3) → see `docs/phase-5-paper-trading.md` recovery. No override button |
| `ORDER_NOT_CANCELABLE` | 409 | Already final | Refresh the order |
| `ACCOUNT_NOT_TRADABLE`, `ASSET_NOT_SUPPORTED`, `FRACTIONAL_NOT_SUPPORTED`, `ORDER_LIMIT_EXCEEDED`, `INSUFFICIENT_BUYING_POWER`, `INSUFFICIENT_POSITION`, `BROKER_REJECTED` | 422 | Business rule | Show the message; adjust the amount |
| `PAPER_DISABLED`, `PAPER_NOT_CONFIGURED`, `BROKER_UNAVAILABLE` | 503 | Feature off, keys missing, Alpaca unreachable | Show the state; manual retry |

Show `message` and `correlationId` on every error.

## 7. Polling policy

`GET /proposals/{id}` reads the **local** state from SQLite. It never calls Alpaca, so it never
learns about a new fill, a final cancel or an order that appeared later. Use it to show what ATLAS
has stored, not to follow the broker. To follow the broker:

| Local state | Request | What it does |
|---|---|---|
| `brokerOrderId` known, broker status not final | `GET /orders/{brokerOrderId}` | Reads Alpaca and updates the proposal and reservation |
| `submission_unknown`, no `brokerOrderId` | `POST /proposals/{id}/reconcile` | Looks the order up by `clientOrderId`. 200 `submitted` once found; 409 `SUBMISSION_UNCERTAIN` while not found. **Never resends** |
| `submitting` | `POST /proposals/{id}/reconcile` | 409 `SUBMISSION_IN_PROGRESS` while the submit lease (120 s from the claim) is live. After it, the proposal becomes `submission_unknown` and the same lookup runs |

About `submitting`:
- The tab that confirmed normally gets the result in the confirm response itself (the backend's HTTP client
  to Alpaca uses a 10 s timeout and no retries). Other tabs, or a page reloaded mid-send, may see `submitting`.
- If the server stopped mid-send, reading the proposal does **not** recover it: it stays
  `submitting` until `/reconcile` is called after the lease, or until a restart runs the startup
  recovery (which also skips live leases).

Rules:
- Interval 2–5 s, with backoff (for example ×2 up to 30 s) on `BROKER_UNAVAILABLE` and on
  repeated `SUBMISSION_IN_PROGRESS` / `SUBMISSION_UNCERTAIN`.
- At most one request in flight per proposal or order: never start a poll while the previous one
  is pending.
- Stop when the screen unmounts and when a final state is reached (`filled`, `canceled`,
  `expired`, `rejected`, or `rejected_by_broker`).
- `pending_cancel` is **not** a final cancel: keep polling `GET /orders/{brokerOrderId}` and show it
  as pending. The reservation stays held until Alpaca reports a final status.
- Never re-confirm as a polling mechanism.
- `/status` calls Alpaca's clock on every request: page load, then at most every 30 s.

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
| Happy path buy | 201 create → 200 confirm (`submitted`) → `GET /orders/{id}` → cancel 200 `pending_cancel` | `test_paper_api.py::test_full_flow_over_http` |
| Fill seen only through the order | GET proposal still `accepted` (no broker call) → `GET /orders/{id}` `filled` → GET proposal `filled`, reservation released | `test_paper_polling_contract.py::test_get_proposal_does_not_reach_the_broker_but_get_order_updates_it` |
| Paper disabled | 503 `PAPER_DISABLED`, `/status` `enabled:false` | `test_default_server_is_disabled_and_makes_no_calls` |
| Invalid amounts or extra fields | 400 `INVALID_REQUEST`, no broker call | `test_invalid_requests_are_rejected_without_calls` |
| Missing or foreign Origin | 403 `ORIGIN_NOT_ALLOWED` | `test_mutations_require_allowed_origin` |
| Insufficient buying power or shares | 422 | `test_paper_service.py` (buying power / position tests) |
| Two proposals for the same share | one 200, one 409 `RESOURCE_RESERVED` | `test_paper_reservations.py::test_1_2_…` |
| Uncertain submission | 409 `SUBMISSION_UNCERTAIN`; reconcile 409 until found, then 200 `submitted`; one submit only | `test_paper_polling_contract.py::test_uncertain_submission_is_resolved_only_by_reconcile_without_resending` |
| Interrupted send, live lease | reconcile and confirm 409 `SUBMISSION_IN_PROGRESS`; GET stays `submitting`; after 120 s reconcile 200 `submitted`, no submit | `test_paper_polling_contract.py::test_live_lease_returns_in_progress_and_reading_sqlite_never_recovers_it` |
| Executions not reflected | 409 `RECONCILIATION_REQUIRED`, then allowed when the broker catches up | `test_paper_consumption.py::test_open_acknowledged_order_with_unreflected_fill_then_broker_catches_up` |
| Expired proposal | 409 `PROPOSAL_EXPIRED` | `test_expired_proposal_is_not_submitted` |
| Cancel pending → canceled | 200 `pending_cancel`; GET proposal stays `pending_cancel`; `GET /orders/{id}` → `canceled` | `test_paper_polling_contract.py::test_pending_cancel_is_not_final_until_the_order_is_read_again`, `test_8_pending_cancel_keeps_shares_until_cancel_is_final` |
| Cancel loses the race | 200 with `filled` | `test_cancel_racing_with_fill_reports_fill` |
| Report creates no order | `/api/report` 200, zero broker calls | `test_analysis_and_report_make_no_broker_calls` |

## 10. Limitations and pending items

- **Alpaca Paper not validated:** no real paper account has been used (needs the user's paper keys
  and explicit confirmation; script `backend/scripts/manual_alpaca_paper_check.py`).
- **Real model (section 11):** reported working by the user; not reproduced by Claude.
- **No authentication.** Local use only; the Origin check is not authentication.
- **No reference quote.** No price or share estimates; sells are bounded by the position, not by USD.
- **Single client.** The fill ledger assumes ATLAS is the only client trading the account. External
  increases are not used once ATLAS has filled on that measure (conservative).
- **Migrated databases.** Local databases written by 5.5–5.7 code may have unverifiable measures
  (`RECONCILIATION_REQUIRED`); recovery is manual and documented.
- **No contract changes in Phase 5.8.** The only additions are the data migration and the
  `checkpoint_distrusted` audit event. The polling correction is documentation plus tests; no
  endpoint changed.

## 11. Evidence about the real model

- **User's evidence:** the user generated real reports with Gemma through LM Studio on their own
  machine.
- **What Claude ran:** only the automated tests, with a mocked HTTP transport for LM Studio. Claude
  has not reproduced a run against a real model, so no claim about latency or output quality is
  made here.
- The deterministic fallback stays the default when the model is disabled or fails
  (`docs/phase-4-narration.md`).

## 12. Pending before starting the Phase 6 integration

1. Codex review of this branch; the user merges PR #3 and PR #4 (never automatically).
2. The friend publishes `feat/paper-ui` (or its successor) so its components are visible.
3. Agree, between the friend and Codex, where the API client, types and state logic live.
4. Codex builds the client and logic against fixtures from section 4, covering section 7.
5. One coordinated PR wires the logic into the visual components.
6. A manual check with the user's own Alpaca Paper keys, with explicit confirmation.

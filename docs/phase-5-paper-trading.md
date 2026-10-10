# Phase 5: Paper Trading Lab (Alpaca Paper)

ATLAS can prepare, confirm and track **simulated** orders in an Alpaca **Paper** account.
There is no live trading code path.

```text
analysis (synthetic) ──(user decides; nothing automatic)──┐
                                                         v
POST /api/paper/proposals   validate, persist, never submit
POST /api/paper/proposals/{id}/confirm   re-validate, atomic claim + persisted intent, one submit
GET  /api/paper/proposals/{id} · /orders/{id}   poll the broker status (fills, cancels)
```

The model narrative (Gemma) and `/api/analyze` never create, confirm or cancel orders.
A BUY or SELL recommendation is never turned into a proposal; the user picks the side and amount.

## Separate sources of truth

| What | Source | Label in the contract |
|---|---|---|
| Analysis, narrative | Synthetic demo dataset | `isSimulated: true`, `facts.provenance: "synthetic"` |
| Account, positions, orders | Alpaca Paper (simulated money) | `environment: "paper"` |
| Reference quote | **Not provided in this phase** | No price, share count or cost estimate is shown |

ATLAS's synthetic prices are never used to estimate execution prices, value positions or
compute buying power. A market order does not guarantee a price.

## Setup

1. Create an Alpaca account and open the **Paper Trading** dashboard. Generate a paper API
   key id and secret (paper key ids start with `PK`). Paper accounts start with simulated funds.
2. Export the variables in the shell that starts uvicorn. The backend does not read `.env`
   by itself (`set -a; source .env; set +a` works if you keep them in `backend/.env`, which is
   git-ignored):
   ```bash
   cd backend
   export ATLAS_PAPER_TRADING_ENABLED=true
   export ATLAS_ALPACA_PAPER_API_KEY=PK...
   export ATLAS_ALPACA_PAPER_SECRET_KEY=...
   ./.venv/bin/uvicorn app.main:app --port 8000
   ```

| Variable | Default | Rule |
|---|---|---|
| `ATLAS_PAPER_TRADING_ENABLED` | `false` | When false, no Alpaca call and no database |
| `ATLAS_ALPACA_PAPER_API_KEY` / `..._SECRET_KEY` | empty | Server only; never returned or logged. Keys starting with `AK` (live) are rejected |
| `ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD` | `1000` | 1–100000 |
| `ATLAS_PAPER_PROPOSAL_TTL_SECONDS` | `300` | 30–3600 |
| `ATLAS_PAPER_DATABASE_PATH` | `backend/var/paper_trading.sqlite3` | SQLite file (git-ignored) |
| `ATLAS_PAPER_ALLOW_REQUESTS_WITHOUT_ORIGIN` | `false` | Local curl testing only |

The endpoint is the constant `https://paper-api.alpaca.markets`. No setting or request can
change it. If `APCA_API_BASE_URL` or `ATLAS_ALPACA_BASE_URL` is set to anything else, the
server refuses to start. Auth headers are `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`.

### Security

This backend is a **local application with no authentication**. Do not expose it publicly.
Mutating routes require an `Origin` header listed in `ATLAS_CORS_ORIGINS`. This reduces
cross-site misuse from a browser, but CORS and the Origin check are **not authentication**.
For curl tests, send `-H 'Origin: http://localhost:3000'` or set
`ATLAS_PAPER_ALLOW_REQUESTS_WITHOUT_ORIGIN=true`.

## Scope (verified against docs.alpaca.markets)

- US equities (`class: us_equity`, `status: active`, `tradable: true`).
- Market orders, `time_in_force: day`, regular session only (`/v2/clock` `is_open`). No
  `extended_hours`.
- **Buy by USD notional.** Alpaca supports notional only for market or day orders, and only on
  `fractionable` assets. Notional uses at most 2 decimals (cents; Alpaca accepts up to 9) with
  a $1 minimum.
- **Sell by quantity** (up to 9 decimals, Alpaca's limit). Fractional quantities need
  `fractionable`; Alpaca marks fractional sells as long.
- No short sales, no leverage requested by ATLAS (buys must fit `non_marginable_buying_power`),
  no options, crypto, limit, stop or bracket orders.
- Unsupported combinations are rejected with a code; ATLAS never converts them into another
  order type.

## Endpoints

All responses use decimal **strings** for money and quantities. Requests must send amounts as
JSON strings; numbers are rejected.

| Method and path | Purpose |
|---|---|
| `GET /api/paper/status` | Enabled, configured, broker reachable, market open, limits, analysis notice. No broker call when disabled |
| `GET /api/paper/account` | Status, cash, buying power, non-marginable buying power, equity, blocks |
| `GET /api/paper/positions` | Broker positions (`qty`, `qtyAvailable`, `avgEntryPrice`, `marketValue`) |
| `GET /api/paper/clock` | `isOpen`, `nextOpen`, `nextClose` |
| `POST /api/paper/proposals` | Prepare a proposal (201). Never submits |
| `GET /api/paper/proposals/{id}` | Proposal state (marks it `expired` when due) |
| `POST /api/paper/proposals/{id}/confirm` | Body `{"confirmation": "CONFIRM_PAPER_ORDER"}`. Validates again and submits once |
| `POST /api/paper/proposals/{id}/reconcile` | Read-only lookup by `client_order_id` for uncertain submissions |
| `GET /api/paper/orders?status=open|closed|all&limit=1..100` | Broker orders (default `all`, 50), linked to proposals when created by ATLAS |
| `GET /api/paper/orders/{orderId}` | Broker status; updates the linked proposal |
| `POST /api/paper/orders/{orderId}/cancel` | Body `{"confirmation": "CANCEL_PAPER_ORDER"}`. Requests cancellation |

Proposal request:

```json
{"symbol": "NVDA", "side": "buy", "notional": "100.00", "analysisReference": null}
{"symbol": "NVDA", "side": "sell", "qty": "0.500000", "analysisReference": null}
```

A buy needs `notional` and no `qty`; a sell needs `qty` and no `notional`. Extra fields are
rejected. `analysisReference` is an optional opaque tag (`[A-Za-z0-9._:@-]`, ≤ 64), stored for
traceability only.

The confirmation body cannot carry symbol, side or amounts (extra fields → 400). To change
anything, create a new proposal.

## States

Three separate lifecycles:

- `status` (proposal): `open` → `confirmed` | `expired`.
- `submissionStatus` (local send): `not_submitted` → `submitting` → `submitted` |
  `rejected_by_broker` | `submission_unknown` | `failed_before_submit`.
- `brokerStatus` (Alpaca, mirrored only from Alpaca responses): `new`, `accepted`, `pending_new`,
  `partially_filled`, `filled`, `done_for_day`, `pending_cancel`, `canceled`, `expired`,
  `rejected`, `replaced`, `pending_replace`, `accepted_for_bidding`, `stopped`, `suspended`,
  `calculated`, or `unrecognized` for a status this version does not know.

| Situation | submissionStatus | Proposal can be confirmed again? |
|---|---|---|
| Connection never established (ConnectError or ConnectTimeout) | `failed_before_submit` | Yes, with the same `clientOrderId` |
| Explicit 4xx from Alpaca (for example 403 insufficient buying power) | `rejected_by_broker` | No (`BROKER_REJECTED` again) |
| Read or write timeout, broken connection, 408/429/5xx, unreadable 200 | `submission_unknown` | **No.** Reconcile only |
| 200 with a matching order | `submitted` | Repeated confirm returns the same proposal |

## Idempotency and concurrency

- `clientOrderId = "atlas-" + proposalId`, generated by the server, `UNIQUE` in SQLite, and
  reused for every attempt of that proposal. ATLAS never creates a new id to repeat an order.
- Confirmation claims the proposal with a conditional `UPDATE` inside a `BEGIN IMMEDIATE`
  transaction (`status = open`, `submissionStatus ∈ {not_submitted, failed_before_submit}`,
  not expired). The `submission_intent` event is written in the same transaction, before the
  HTTP call. Only one confirmation can win; the others get the known result or
  `SUBMISSION_IN_PROGRESS`. This is enforced by the database, not by an in-memory lock.
- Repeated confirmations return the known result: the proposal if submitted, or the same
  error code otherwise.

## Uncertain submissions and recovery

1. The intent is persisted before sending.
2. If the outcome cannot be determined, the proposal becomes `submission_unknown`.
3. ATLAS immediately does one **read-only** lookup:
   `GET /v2/orders:by_client_order_id?client_order_id=…`.
4. If a matching order exists (same `client_order_id`, symbol and side), it is applied
   (`submitted`).
5. Otherwise the proposal stays `submission_unknown`. It is **never resent**; the user calls
   `/reconcile` later or checks the Alpaca dashboard. To trade again, create a new proposal.

**Restart:** on startup, `recover_pending()` turns every `submitting` proposal into
`submission_unknown` (event `recovered_after_restart`) and reconciles it read-only before
anything else can happen to it.

Alpaca's docs do not state what a duplicate `client_order_id` or a missing one on lookup
returns, so ATLAS does not rely on resubmitting with the same id.

## Business checks (prepare and again at confirm)

Account `ACTIVE` and not blocked · market open · asset tradable US equity · `fractionable` for
notional buys and fractional sells · buy ≤ `ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD` · buy ≤
`non_marginable_buying_power` · sell ≤ `qty_available` (Alpaca subtracts open orders) minus
quantities of local sells whose outcome is still uncertain · long position required (no shorts).
Missing broker data needed for a check fails the check (`BROKER_UNAVAILABLE`). Checks do not
reserve funds; Alpaca remains the final authority. The sell side has no USD cap because no
reference quote is used; it is bounded by the position.

## Cancellation

`DELETE /v2/orders/{id}` → 204 means "cancel requested", not canceled. ATLAS then reads the
order and returns Alpaca's status (`pending_cancel`, `canceled`, or `filled` / `partially_filled`
if it filled first). A 422 maps to `ORDER_NOT_CANCELABLE`. Reads never cancel anything.

## Errors

Same shape as the rest of the API, plus a stable `code`, a `correlationId` (also in the
`X-Correlation-Id` header) and `proposalId` when relevant. Broker bodies, traces and secrets
are never returned.

| HTTP | Codes |
|---|---|
| 400 | `INVALID_REQUEST`, `INVALID_CONFIRMATION` |
| 403 | `ORIGIN_NOT_ALLOWED` |
| 404 | `PROPOSAL_NOT_FOUND`, `ORDER_NOT_FOUND` |
| 409 (state conflict) | `MARKET_CLOSED`, `PROPOSAL_EXPIRED`, `SUBMISSION_IN_PROGRESS`, `SUBMISSION_UNCERTAIN`, `ORDER_NOT_CANCELABLE` |
| 422 (business rule) | `ACCOUNT_NOT_TRADABLE`, `ASSET_NOT_SUPPORTED`, `FRACTIONAL_NOT_SUPPORTED`, `ORDER_LIMIT_EXCEEDED`, `INSUFFICIENT_BUYING_POWER`, `INSUFFICIENT_POSITION`, `BROKER_REJECTED` |
| 503 (unavailable) | `PAPER_DISABLED`, `PAPER_NOT_CONFIGURED`, `BROKER_UNAVAILABLE` |

## Audit trail

The SQLite `events` table records `proposal_created`, `validation_failed`, `submission_intent`,
`broker_accepted`, `broker_rejected`, `submission_not_sent`, `submission_unknown`,
`reconciled`, `reconcile_not_found`, `recovered_after_restart`, `order_status`,
`proposal_expired`, `cancel_requested`, `cancel_rejected` and `cancel_result`, with ids,
timestamps, states, amounts and the correlation id. No secrets and no narrative text are stored.

## Examples

Produced through the HTTP API with the **fake broker used by the tests** (not a real Alpaca
response).

Proposal (`POST /api/paper/proposals`, 201):

```json
{
  "id": "36b31cc077484a99a5bb96a7f62859d7",
  "environment": "paper",
  "symbol": "NVDA",
  "side": "buy",
  "notional": "100.00",
  "qty": null,
  "orderType": "market",
  "timeInForce": "day",
  "clientOrderId": "atlas-36b31cc077484a99a5bb96a7f62859d7",
  "analysisReference": "NVDA@2026-09-30",
  "createdAt": "2026-10-05T15:00:00.000000+00:00",
  "expiresAt": "2026-10-05T15:05:00.000000+00:00",
  "status": "open",
  "submissionStatus": "not_submitted",
  "brokerOrderId": null,
  "brokerStatus": null,
  "filledQty": null,
  "filledAvgPrice": null,
  "lastErrorCode": null,
  "updatedAt": "2026-10-05T15:00:00.000000+00:00",
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
    "..."
  ],
  "warnings": [
    "Paper trading: simulated money in an Alpaca Paper account.",
    "Market order: the execution price is not known in advance and is not guaranteed.",
    "These checks do not reserve funds or shares; Alpaca may still reject the order.",
    "ATLAS analysis uses a synthetic demo dataset. It is not market data and is not linked to paper orders, balances or prices."
  ]
}
```

Confirmed (`brokerStatus` reflects what the broker returned; `accepted` is not an execution):

```json
{
  "id": "36b31cc077484a99a5bb96a7f62859d7",
  "status": "confirmed",
  "submissionStatus": "submitted",
  "brokerOrderId": "a35f9c9b-f6bb-484b-9acf-24f4d4df5d7d",
  "brokerStatus": "accepted",
  "filledQty": "0",
  "filledAvgPrice": null,
  "lastErrorCode": null
}
```

Cancel requested (the order is `pending_cancel`, not `canceled`):

```json
{
  "cancelRequested": true,
  "order": {
    "id": "a35f9c9b-f6bb-484b-9acf-24f4d4df5d7d",
    "clientOrderId": "atlas-36b31cc077484a99a5bb96a7f62859d7",
    "symbol": "NVDA",
    "side": "buy",
    "type": "market",
    "timeInForce": "day",
    "qty": null,
    "notional": "100.00",
    "filledQty": "0",
    "filledAvgPrice": null,
    "status": "pending_cancel",
    "brokerStatusRaw": "pending_cancel",
    "submittedAt": "2026-10-05T15:00:01Z",
    "filledAt": null,
    "canceledAt": null,
    "proposalId": "36b31cc077484a99a5bb96a7f62859d7",
    "environment": "paper"
  }
}
```

Uncertain submission (409):

```json
{
  "error": "Paper trading state conflict",
  "message": "The submission result is uncertain. Reconcile the proposal; it will not be resent.",
  "code": "SUBMISSION_UNCERTAIN",
  "correlationId": "7ef87c7a04414ae0a6f30abc39b3e42a",
  "proposalId": "69f6a67b64bf482ba8ba2a6b4c8f63e5"
}
```

Sell larger than the available position (422):

```json
{
  "error": "Paper trading validation error",
  "message": "The quantity exceeds the shares available after open and pending orders.",
  "code": "INSUFFICIENT_POSITION",
  "correlationId": "c8dfd4f3b23b4b2b8c8b326ed6da8525",
  "proposalId": null
}
```

## Guidance for the frontend (Codex)

- A permanent label on every paper screen: **"Paper Trading — dinero ficticio"**.
- Show account balance, buying power and positions from `/api/paper/account` and `/positions`.
- Keep the synthetic analysis visibly separate: show `status.analysisDataNotice`. Never put
  synthetic prices next to paper orders, and never show estimated shares or prices.
- Form: buy by USD amount or reduce an existing position by quantity. The user chooses the
  side and amount; do not prefill from the recommendation.
- Review screen: show symbol, side, amount, market/day, `checks`, `warnings` and the expiry
  countdown (`expiresAt`).
- One explicit **Confirm paper order** button that sends
  `{"confirmation": "CONFIRM_PAPER_ORDER"}`. Disable every control while the request is in
  flight.
- `SUBMISSION_UNCERTAIN` or `submissionStatus: "submission_unknown"`: show a clear uncertain
  state with a **Check status** action (`/reconcile`). Never show a resend button.
- After submission, poll `GET /api/paper/proposals/{id}` or `/orders/{orderId}` (for example
  every 2–5 s while not terminal) to show `brokerStatus`, `filledQty` and `filledAvgPrice`.
- Cancel: an explicit button sending `{"confirmation": "CANCEL_PAPER_ORDER"}`. Show the
  returned status (`pending_cancel` is not `canceled`).
- Send mutating requests from the configured origin. Show `message` and `correlationId` on
  errors.
- Generating the narrative report must never create or confirm an order.

## Tests

`cd backend && ./.venv/bin/python -m pytest -q` uses a fake broker and `httpx.MockTransport`.
No test calls Alpaca. Coverage includes the disabled server, live configuration rejection,
missing secrets, invalid amounts, assets, fractional rules, market closed, buying power,
positions and open orders, prepare-without-submit, confirm, expiry, immutability, duplicate and
concurrent confirmations, timeout after acceptance, reconciliation, restart recovery, broker
rejection, partial fills, cancellation races, persistence, sanitized errors, and no broker
calls from analysis or narrative.

### Manual check with a real paper account (not run yet)

```bash
cd backend   # with the variables above exported
./.venv/bin/python scripts/manual_alpaca_paper_check.py NVDA            # read-only
./.venv/bin/python scripts/manual_alpaca_paper_check.py NVDA --submit-buy 5.00
```

The second form submits one paper order only after you type
`PAPER BUY NVDA 5.00 USD`, then reads the broker status back. It is never run by CI.

**Status:** the real Alpaca Paper check has **not** been executed. No paper credentials were
available in the development environment.

## Known limitations and operational risks

- No authentication: local use only.
- No reference quote: no price or share estimates, and no USD cap on sells.
- Market orders execute at the prevailing price, and paper fills are simulated (Alpaca does not
  model slippage, market impact or queue position; 10% of fillable paper orders get random
  partial fills).
- Checks race with the broker: balances and positions can change between confirm and fill.
- An uncertain submission whose order never appears stays uncertain until the user checks Alpaca.
- Polling only, no WebSocket updates. `done_for_day` and similar statuses need polling the next day.
- SQLite is single-machine; delete `backend/var/` to reset local proposals (paper orders at
  Alpaca are not affected).

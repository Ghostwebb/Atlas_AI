# Paper Trading logic (Phase 6, technical part)

Based on frontend `fbf3ae3`; API contract checked against backend `cd951e7`
(`docs/phase-6-integration-handoff.md`). No dashboard, navigation, styles, shared
configuration, agent components or backend changes. **This is not a UI and not a finished
integration**: the visual wiring is a later coordinated PR.

| File | Purpose |
|---|---|
| `types.ts` | Backend shapes; amounts and quantities stay decimal strings |
| `client.ts` | API client: injected `fetch`, no credentials, no retries |
| `policy.ts` | Pure eligibility rules and the follow-up endpoint for a proposal |
| `validate.ts` | Runtime validation of every response used to authorize an action |
| `controller.ts` | Operation controller: state, locks, polling, reconciliation |
| `usePaperTradingController.ts` | Optional React hook around the controller |
| `contract.test.mjs`, `controller.test.mjs`, `identity-cancel.test.mjs` | Fixture-only tests (Node test runner) |
| `test-fixtures.mjs` | Shared simulated HTTP fixtures, manual clock and scheduler |
| `run-tests.sh` | Compiles the folder to a temp dir and runs all test files |

## Public API

```ts
const ctl = createPaperTradingController({
  client: createPaperClient(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"),
  source: "backend",            // "fixture" for fixture-driven demos/tests
  pollIntervalMs: 3000,         // clamped to 2000–5000
  maxBackoffMs: 30000,
  // now, scheduler: injectable for tests
});
ctl.getState();                 // immutable ControllerState snapshot
ctl.subscribe(listener);        // returns unsubscribe
await ctl.prepare({ symbol, side: "buy", notional: "100.00" }); // or side "sell", qty
await ctl.confirm();            // ONLY from an explicit human click
await ctl.cancel();             // ONLY from an explicit human click
await ctl.checkStatus();        // "Consultar estado" (read-only)
await ctl.resume(proposalId);   // follow an existing proposal (read-only)
ctl.dispose();                  // abort requests, clear timers, ignore late responses
```

Actions return `{ ok: true }` or `{ ok: false, reason: "busy" | "not_allowed" | "disposed" | "error" }`.
Errors are in `state.lastError` (`code`, `message`, `status`, `correlationId`, `proposalId`).

`ControllerState` keeps the backend lifecycles separate: `proposal.status`,
`proposal.submissionStatus`, `proposal.brokerStatus` / `order.status` and
`proposal.reservation.state`. On top of them:

- `phase`: a derived summary for the UI.
- Local flags: `busy`, `reading`, `confirmUncertain`, `cancelUncertain`, `verifying` and `suspect`. `suspect` means the last read was malformed or contradicted the operation; mutations stay blocked until a consistent read, while status checks remain available.
- Polling: `nextReadInMs`.
- Permissions: `canPrepare`, `canConfirm`, `canCancel` and `canCheckStatus`.
- Labels: `notice` ("Paper Trading — dinero ficticio") and `source`.

## States and transitions

| Phase | Meaning | Allowed |
|---|---|---|
| `idle` | No operation | prepare |
| `preparing` | `POST /proposals` in flight | — |
| `review` | `open` + `not_submitted`/`failed_before_submit`, before `expiresAt` | confirm (human), prepare again |
| `confirming` | `POST /confirm` in flight | — |
| `uncertain` | Lost/aborted/invalid confirm response, or `submitting` / `submission_unknown` | check status only |
| `tracking` | `submitted`, broker status not final (incl. `pending_cancel`, `done_for_day`, `replaced`, `unrecognized`, missing) | check status; cancel (human) only for the statuses in "Cancellation policy" |
| `final` | Broker `filled`/`canceled`/`expired`/`rejected`, or `rejected_by_broker` | prepare a new one |
| `expired` | Unsent proposal past its TTL (local clock or backend) | prepare a new one |

Transitions:

- **`idle` → `preparing` → `review`.**
- **`review` → `confirming`**, only through `confirm()`. From there:
  - success → `tracking` or `final`;
  - definite ATLAS error (documented `code`) → `verifying`; the proposal is re-read before confirm is offered again;
  - network error, abort, malformed or contradictory response, or unknown code → `uncertain` (`confirmUncertain`).
- **Leaving `uncertain` (`confirmUncertain`)**, read `GET /proposals/{id}`, then:
  - `submitted` → `tracking`;
  - `submitting` or `submission_unknown` → `POST /reconcile`;
  - `open + failed_before_submit` → `review`, but only a new human click confirms;
  - `open + not_submitted` → stays `uncertain` (the lost request may still be processed), with backoff, until the backend proves otherwise or the proposal expires.
- **`uncertain` from `submitting`:** `POST /reconcile` answers `SUBMISSION_IN_PROGRESS` while the 120 s lease is live, then does a read-only lookup.
- **`uncertain` from `submission_unknown`:** `POST /reconcile` (lookup by `clientOrderId`, never a resend).
- **`tracking` → `cancel()`.** Any outcome sets `cancelUncertain` until the order is read again, so no second cancel happens on a lost response.
- **Follow-up reads in `tracking`:** `GET /orders/{brokerOrderId}` (updates ATLAS from Alpaca), then `GET /proposals/{id}` (local state, reservation).
- **TTL:** only an unsent proposal expires. A submitted operation keeps being followed after `expiresAt`.

## Operation identity

When an operation is adopted (by `prepare` or `resume`), its identity is fixed: `id`,
`clientOrderId`, `symbol`, `side`, `notional`, `qty` and `analysisReference`.

- **Prepare.** The response must be exactly the requested operation:
  - the symbol must equal the request symbol after the backend's normalization (`strip()` + `upper()`, as in `backend/app/symbols.py`);
  - the side must be the same;
  - a buy needs an equal `notional` and `qty: null`; a sell needs an equal `qty` and `notional: null`;
  - `analysisReference` must be identical, including its absence.
- **Exact decimals.** Amounts are compared as canonical decimal strings: leading zeros of the integer part and trailing zeros of the fraction are removed, so `"100.00"` equals `"100"`. There is no `Number`/`parseFloat`, so values that round to the same double stay different.
- **Later responses.** Every later proposal (confirm, read, reconcile) must keep the same identity. A broker order must match `clientOrderId`, `symbol` and `side`, and its `proposalId` if present.
- **On a mismatch:**
  - the error is `INVALID_RESPONSE`;
  - the response is not adopted;
  - no mutation is started, and confirm and cancel stay disabled (`suspect`) until a consistent read;
  - a mismatched confirm response leaves the operation `uncertain` (read and reconcile, never resend).

## Cancellation policy

The button (`canCancel`) is shown only when **all** of these hold:

- `submissionStatus` is `submitted`, a `brokerOrderId` exists, no mutation is in flight, and no cancel or read is uncertain or suspect;
- the broker status is in the explicit allow-list `CANCELABLE_STATUSES`: `new`, `accepted`, `pending_new`, `accepted_for_bidding`, `partially_filled`.

"Not final" does not mean "cancelable":

| Broker status | Button | Tracking |
|---|---|---|
| `new`, `accepted`, `pending_new`, `accepted_for_bidding`, `partially_filled` | shown | yes |
| unknown (`unrecognized`) or missing | hidden | yes, "Consultar estado" available |
| `pending_cancel` | hidden | yes (not a final cancel) |
| `pending_replace` | hidden (Alpaca rejects cancels while replacing) | yes |
| `done_for_day`, `replaced`, `stopped`, `suspended`, `calculated` | hidden (not a plain live ATLAS order) | yes |
| `filled`, `canceled`, `expired`, `rejected` | hidden | stops (final) |

Even with the button shown, the backend can answer:

- `409 ORDER_NOT_CANCELABLE` (filled or closed meanwhile);
- `200` with `order.status: "filled"` (the cancel lost the race);
- `200` with `pending_cancel`;
- `404 ORDER_NOT_FOUND`;
- `503 BROKER_UNAVAILABLE` / `PAPER_DISABLED` / `PAPER_NOT_CONFIGURED`;
- `403 ORIGIN_NOT_ALLOWED`;
- `400 INVALID_CONFIRMATION`.

After any outcome the controller reads the order again before offering another cancel.

## Invariants

1. Preparing never confirms. Input is rebuilt from documented fields only. Analysis objects, recommendations or committee decisions are rejected, and numbers are rejected (decimal strings only).
2. `busy` is set synchronously before any `await`: two `confirm()` calls before React renders produce one request. All mutations share this lock.
3. `confirm()` is never called by the controller itself: not by polling, recovery, mount, resume or analysis. There is no automatic resend.
4. At most one follow-up read in flight per operation:
   - `checkStatus()` joins it or replaces the pending timer;
   - interval of 3 s by default, ×2 per failure or repeated uncertainty, capped at 30 s;
   - it stops in `final` and `expired` and on `dispose()`.
5. Responses are validated at runtime (`validate.ts`):
   - malformed or contradictory data fails closed and never enables confirm or cancel;
   - unknown broker statuses become `unrecognized` (not final);
   - responses for another proposal or order are rejected.
6. Late responses of a previous operation (`resume`/`prepare` of another proposal) or after `dispose()` are ignored. Requests are aborted with `AbortController`.
7. Only `/api/paper/*` is called. The frontend never holds credentials. A fixture-driven controller reports `source: "fixture"` and must never be shown as "Conectado a Alpaca".

## Wiring it to visual components (without changing their design)

- Create the controller in a Client Component (`"use client"`) with `usePaperTradingController(options)`, or call `createPaperTradingController` yourself and `dispose()` on unmount.
- Map state to existing props only:
  - `canConfirm` / `canCancel` → the button's `disabled`;
  - `phase` → which panel or text is shown;
  - `proposal.checks`, `proposal.warnings`, `proposal.expiresAt` → review and countdown;
  - `lastError.message` plus `correlationId` → error text;
  - `nextReadInMs` / `reading` → "actualizando…".
- The confirm button calls `controller.confirm()` in its `onClick`, never in an effect. The same applies to cancel.
- In `uncertain`, show only "Consultar estado" (`checkStatus()`), never a resend button.
- Show `notice` permanently on every paper screen. Never place synthetic analysis prices next to paper data, and never turn a committee or report result into `prepare()` arguments.
- **Persistence (optional, not implemented):** to survive a reload, a component may store only `proposal.id` (for example in `sessionStorage`) and call `resume(id)`. That is a convenience, not a broker guarantee: an order can still exist at Alpaca if the id is lost.

## Tests

Node 22+, run from anywhere:

```bash
frontend/features/paper-trading/run-tests.sh
```

The tests use HTTP fixtures and a manual clock and scheduler; they need no network, Alpaca,
LM Studio or credentials. They cover:

- preparing without confirming;
- a double confirm sending one request;
- local and backend expiry;
- a lost or invalid confirm reconciled without resending;
- `open + not_submitted` staying uncertain;
- `submitting` with a live lease;
- an uncertain order appearing later;
- partial and final fills;
- `pending_cancel`, and a cancel losing the race to a fill;
- a lost cancel response;
- backoff and recovery;
- slow polling without overlap, and a manual check while a read is in flight;
- dispose during a request;
- switching proposals with late responses ignored;
- malformed or contradictory data;
- unknown broker statuses;
- separation between synthetic analysis and the paper account;
- operation identity: different symbol, side or amount, an incompatible amount field, the reference (different, missing or unexpected), normalized symbols, equivalent decimals without floats, and later reads or orders that change the operation;
- the cancellation allow-list: unknown or missing statuses, `pending_cancel`, the four final statuses, allowed statuses, and an unknown status that becomes a recognized one.

Mutation checks run by hand (each one makes at least one test fail):

- removing the synchronous lock;
- retrying an uncertain confirm;
- treating `pending_cancel` as final;
- allowing overlapping reads;
- dropping the stale-response check;
- removing the comparison with the request;
- removing the identity check on later reads;
- re-enabling cancel for `unrecognized`;
- comparing amounts with `Number`;
- not blocking mutations after an invalid read.

Project checks: `./node_modules/.bin/tsc --noEmit -p .`, `npm run lint`, `npm run build`.

## Limitations and pending items

- No visual integration yet. A coordinated PR with the friend's components is next.
- Not run against a real backend with real Alpaca Paper keys. That needs the user's explicit authorization.
- After a lost confirm, if ATLAS still shows `open + not_submitted`, the operation stays uncertain until the backend proves otherwise or the proposal expires (TTL, 300 s by default).
- One controller per operation. Several concurrent orders need several controllers.
- Codex reported five dev-dependency alerts, left for a separate task. No dependency was changed.

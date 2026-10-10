# Paper Trading (Phase 6): logic and standalone screen

Based on frontend `fbf3ae3` and the reviewed logic `781ecfc` (PR #5); API contract checked against
backend `cd951e7` (`docs/phase-6-integration-handoff.md`). The screen lives on its own route
`/paper-trading`. The dashboard, navigation, global styles, shared configuration and the agent
components are **not** modified.

| File | Purpose |
|---|---|
| `types.ts` | Backend shapes; amounts and quantities stay decimal strings |
| `client.ts` | API client: injected `fetch`, no credentials, no retries |
| `policy.ts` | Pure eligibility rules and the follow-up endpoint for a proposal |
| `validate.ts` | Runtime validation of every response used to authorize an action |
| `controller.ts` | Operation controller: state, locks, polling, reconciliation |
| `journal.ts` | Versioned operation journal (sessionStorage adapter) for recovery after reload |
| `usePaperTradingController.ts` | Optional React hook around the controller |
| `contract.test.mjs`, `controller.test.mjs`, `identity-cancel.test.mjs`, `recovery.test.mjs` | Fixture-only tests (Node test runner) |
| `test-fixtures.mjs` | Shared simulated HTTP fixtures, manual clock and scheduler |
| `run-tests.sh` | Compiles the folder to a temp dir and runs all test files |
| `ui/PaperTradingScreen.tsx` | Client screen for `/paper-trading` (route file: `app/paper-trading/page.tsx`) |
| `ui/OrderForm.tsx`, `ui/OperationPanel.tsx`, `ui/AccountPanel.tsx`, `ui/ErrorNotice.tsx` | Form, review/tracking, account, errors |
| `ui/account.ts` | Read-only status, account and positions loading with runtime validation |
| `ui/labels.ts` | Spanish labels for states and error codes |
| `ui/paper-trading.css` | Local styles (`.pt-` prefix) reusing the approved design tokens |
| `e2e/paper-trading.e2e.mjs`, `e2e/run-e2e.sh` | Browser tests (Chromium) with intercepted HTTP fixtures |

## Public API

```ts
const ctl = createPaperTradingController({
  client: createPaperClient(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"),
  journal: createStorageJournal(), // REQUIRED: a journal, or null to accept losing protection on reload
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
await ctl.resume(proposalId);   // follow an existing proposal (read-only; refused while an intent is pending)
ctl.dispose();                  // abort requests, clear timers, ignore late responses
```

Actions return `{ ok: true }` or `{ ok: false, reason: "busy" | "not_allowed" | "disposed" | "error" }`.
Errors are in `state.lastError` (`code`, `message`, `status`, `correlationId`, `proposalId`).
`state.actionError` keeps the error of the last human action (prepare, confirm or cancel). A later
successful read does not clear it, so a message like `RESOURCE_RESERVED` stays visible after the
controller re-reads the proposal. It is cleared by the next action, by a new operation, or when an
uncertain confirmation is resolved.

`ControllerState` keeps the backend lifecycles separate: `proposal.status`,
`proposal.submissionStatus`, `proposal.brokerStatus` / `order.status` and
`proposal.reservation.state`. On top of them:

- `phase`: a derived summary for the UI.
- Local flags: `busy`, `reading`, `confirmUncertain`, `cancelUncertain`, `verifying` and `suspect`. `suspect` means the last read was malformed or contradicted the operation; mutations stay blocked until a consistent read, while status checks remain available.
- Polling: `nextReadInMs`.
- Permissions: `canPrepare`, `canConfirm`, `canCancel` and `canCheckStatus`.
- Labels: `notice` ("Paper Trading — dinero ficticio") and `source`.

## Recovery after reload (operation journal)

**Problem fixed (review of `f2a6010`).** The screen stored only the proposal id and called
`resume(id)` after a reload. Suppose a confirm response was lost and ATLAS still showed
`open + not_submitted`:

- the new controller came back in `review` with confirm enabled;
- another click sent a second `POST /confirm`.

The confirm intent lived only in memory.

**Fix.** The intent is part of the controller and is stored durably before anything is sent.

- **Format** (`journal.ts`, sessionStorage key `atlas.paperTrading.operation`):
  `{ "v": 1, "proposalId": "…", "pendingConfirm": bool, "pendingCancel": bool }`.
  It holds no amounts and no credentials.
- **Write order:**
  1. `confirm()` sets `pendingConfirm: true` and writes it synchronously;
  2. then it takes the lock;
  3. only then does it call the transport.

  If the write fails, nothing is sent: `actionError.code = "JOURNAL_UNAVAILABLE"` and `journal: "unavailable"`. `cancel()` does the same with `pendingCancel`. No React effect is involved.
- **Recovery:** the journal is read synchronously when the controller is created.
  - With `pendingConfirm`, the very first state is `uncertain` (`canConfirm` and `canPrepare` false). It is never confirmable first and blocked later.
  - Without it, the first state is `recovering`.
  - A read-only `GET /proposals/{id}` then starts immediately, followed by the normal reads and reconciliation.
- **When `pendingConfirm` is cleared** (only on a conclusive backend answer):
  - a valid confirm response;
  - a documented ATLAS error code (the request was processed, so no copy of it is pending);
  - a read that shows anything other than `open + not_submitted`: `submitted`, `submitting`, `submission_unknown`, `rejected_by_broker` or `failed_before_submit`;
  - backend `expired`, which is conclusive because the claim requires an unexpired proposal in the same transaction.

  `open + not_submitted` is **not** proof, and a local timer never ends the uncertainty. `failed_before_submit` returns to `review`, and only a new human click confirms.
- **`pendingCancel`** keeps cancel blocked after a reload until the order is read again.
- **Unknown proposal:** a `404 PROPOSAL_NOT_FOUND` during recovery ends recovery (ATLAS cannot process a confirm for an unknown proposal) and clears the record. Other errors keep reading with backoff.
- **Records are not deleted when an operation ends.** Flags are cleared, and the id stays so a reload keeps showing the operation. A new explicitly prepared operation replaces the record.
- **`resume()` and `prepare()` are refused** while an intent is pending or recovery has not read the proposal.

| Storage situation | Behaviour |
|---|---|
| Not available (access throws) | `journal: "unavailable"`; nothing is recovered; confirm and cancel are blocked; the screen says so |
| Write fails (quota, privacy mode) | That confirm or cancel is not sent; `JOURNAL_UNAVAILABLE`; buttons stay disabled |
| Corrupt JSON or no usable id | `journal: "invalid"`: the operation is unknown, so nothing is recovered and nothing becomes confirmable. A new operation must be prepared explicitly, and its record replaces the unreadable one |
| Unknown version, or missing or malformed flags, but a usable id | Recovered with `pendingConfirm` and `pendingCancel` set (conservative) |
| Legacy record from `f2a6010` (plain id under `atlas.paperTrading.proposalId`) | Recovered with `pendingConfirm: true`, because the old format never recorded intent. The legacy key is removed on the next write |

**Scope.** sessionStorage covers one browser tab and its reloads. It is not a guarantee across
tabs, windows or devices. The backend guarantees still hold independently: an atomic claim, at
most one submission, and reconciliation without resending.

## States and transitions

| Phase | Meaning | Allowed |
|---|---|---|
| `idle` | No operation | prepare |
| `recovering` | Journal record without pending intent, proposal not read yet | check status |
| `preparing` | `POST /proposals` in flight | — |
| `review` | `open` + `not_submitted`/`failed_before_submit`, before `expiresAt` | confirm (human), prepare again |
| `confirming` | `POST /confirm` in flight | — |
| `uncertain` | Lost/aborted/invalid confirm response (also after a reload, from the journal), or `submitting` / `submission_unknown` | check status only |
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
- **Persistence:** pass `journal: createStorageJournal()` (sessionStorage) to the controller. Do not store ids yourself or call `resume()` on mount: the controller recovers by itself and keeps pending intents uncertain (see "Recovery after reload").

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

## The `/paper-trading` screen

**Open it.**

1. Start the backend with paper trading configured (below).
2. Start the frontend: `cd frontend && npm run dev`.
3. Open http://localhost:3000/paper-trading.

The dashboard has no link to it yet, because adding one means editing `app/page.tsx`, a shared
file (see "Coordination").

**Backend configuration (local only).** Export these variables in the shell that runs uvicorn;
the backend does not read `.env` by itself:

- `ATLAS_PAPER_TRADING_ENABLED=true`
- `ATLAS_ALPACA_PAPER_API_KEY` and `ATLAS_ALPACA_PAPER_SECRET_KEY` (paper keys)
- `ATLAS_CORS_ORIGINS=http://localhost:3000`

Then run `./.venv/bin/uvicorn app.main:app --port 8000`. Details are in
`docs/phase-6-integration-handoff.md` § 2.

- The frontend only needs `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) and never holds credentials.
- The backend has no authentication: do not expose it or this app on the internet.

**What the screen does.**

- **Permanent banner:** "Paper Trading — dinero ficticio".
- **Availability:** feature status (Disponible, Deshabilitada, Sin configurar, Inaccesible, Alpaca Paper inaccesible), market state and next open.
- **Account and positions:** read from the backend. Missing values show "No disponible", never 0.
- **No automatic polling of `/status`:** it calls Alpaca every time, so it is read on mount, with "Actualizar", and after an operation ends.
- **Form:** buy by USD amount, or reduce a position by shares. Values stay decimal strings, and preparing never confirms.
- **Review:**
  - symbol, side and amount;
  - order type;
  - expiry countdown (display only);
  - checks, warnings, and the notice that preparing neither sends nor reserves.
- **Confirmation:** one explicit button calls `controller.confirm()` from its `onClick`. It is enabled only by `canConfirm`. Nothing confirms from effects, mount, polling, reports or recommendations.
- **Tracking:**
  - separate rows for proposal, submission, broker status, executed quantity with average price, and reservation;
  - "Consultar estado" (`canCheckStatus`);
  - "Cancelar orden" (`canCancel`, explicit allow-list);
  - why cancel is unavailable (`pending_cancel`, unknown status);
  - an uncertain banner with no resend button.
- **Errors:** a readable message plus "Detalle técnico" (`code`, `message`, `correlationId`). No force-release or bypass controls exist.
- **Reload:** the controller's journal (sessionStorage, this tab only) recovers the operation. A confirm or cancel sent before the reload stays uncertain until the backend answers conclusively, and a journal that cannot be written blocks confirm and cancel. See "Recovery after reload".
- **Accessibility:**
  - visible labels and keyboard-reachable controls;
  - focus moves to the review, then to the status heading, only when the phase changes;
  - one polite live region announces phase changes, not polling ticks;
  - `aria-busy` while loading.
- **Data separation:** a card states that ATLAS analysis is synthetic and never used here, that account data comes from the backend, and that fixtures exist only in tests.

**Browser tests** (real React mount, Next.js dev server with StrictMode, Chromium). Every call to
the backend URL is intercepted with simulated fixtures, so there is no backend, Alpaca or
credentials. Playwright is used from outside the project, and no dependency is added:

```bash
cd frontend
features/paper-trading/e2e/run-e2e.sh          # PLAYWRIGHT_MODULE defaults to $(npm root -g)/playwright
E2E_SCREENSHOTS=/tmp/shots features/paper-trading/e2e/run-e2e.sh   # also saves desktop/mobile screenshots
```

They cover:

1. prepare, review and explicit confirm;
2. a double click sending one confirm;
3. expiry;
4. a lost confirm, the uncertain state and a status check without resend;
5. a partial then final fill;
6. `pending_cancel` then `canceled`;
7. a cancel losing the race to a fill;
8. `RESOURCE_RESERVED` and `RECONCILIATION_REQUIRED`;
9. an unknown status (check allowed, cancel blocked);
10. a wrong-identity response blocking actions;
11. unmount and remount, with no duplicate polling and late responses ignored;
12. the dashboard report and analysis making zero paper calls;
13. no horizontal scroll at 1440 px and 390 px, plus keyboard focus.

Test 12b checks the committee view of `codex/agents-workspace` when `E2E_COMMITTEE_URL` points to a server running that branch.

## Coordination and PR dependencies

- **This PR depends on:**
  - #4 (approved frontend, `fbf3ae3`);
  - #5 (logic, `781ecfc`): it targets that branch, so its diff contains only the integration;
  - #3 (backend, `cd951e7`): needed at runtime.
- **Files that need coordination with the frontend owner before any change:**
  - `app/page.tsx` (a navigation link to `/paper-trading`);
  - `app/layout.tsx`, `app/globals.css`, `next.config.ts`;
  - `components/*` (including the friend's `components/agents/` and the `components/paper/` area assigned to them);
  - `lib/*`.
- **CSS Modules:** in the base, `next.config.ts` runs every `*.css` through the Tailwind loader, which breaks CSS Modules (the friend's branch changes this). This screen therefore uses a plain stylesheet with `.pt-` prefixed selectors and does not depend on that change.

## Limitations and pending items

- Not validated against a real backend with real Alpaca Paper keys; all tests use fixtures. That run needs the user's paper keys in the backend and explicit authorization.
- No dashboard link to `/paper-trading` yet (needs coordination on `app/page.tsx`).
- Visual checks were made on Chromium only (desktop 1440 px, mobile 390 px), with the Google font blocked, so the system font fallback was used.
- Not run against a real backend with real Alpaca Paper keys. That needs the user's explicit authorization.
- After a lost confirm, if ATLAS still shows `open + not_submitted`, the operation stays uncertain until the backend proves otherwise or the proposal expires (TTL, 300 s by default).
- One controller per operation. Several concurrent orders need several controllers.
- Codex reported five dev-dependency alerts, left for a separate task. No dependency was changed.

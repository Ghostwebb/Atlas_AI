# Phase 5: Paper Trading Lab (Alpaca Paper)

ATLAS can prepare, confirm and track **simulated** orders in an Alpaca **Paper** account.
There is no live trading code path.

```text
analysis (synthetic) ──(user decides; nothing automatic)──┐
                                                         v
POST /api/paper/proposals   validate, persist, never submit
POST /api/paper/proposals/{id}/confirm   re-validate, atomic claim + persisted intent, one submit
GET  /api/paper/orders/{id}   read the broker status (fills, cancels); updates the proposal
POST /api/paper/proposals/{id}/reconcile   read-only lookup for uncertain submissions
GET  /api/paper/proposals/{id}   local state only (SQLite); never calls the broker
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
| `GET /api/paper/proposals/{id}` | Local proposal state from SQLite (marks it `expired` when due). Never calls the broker |
| `POST /api/paper/proposals/{id}/confirm` | Body `{"confirmation": "CONFIRM_PAPER_ORDER"}`. Validates again and submits once |
| `POST /api/paper/proposals/{id}/reconcile` | Read-only lookup by `client_order_id` for uncertain submissions |
| `GET /api/paper/orders?status=open|closed|all&limit=1..100` | Broker orders (default `all`, 50), linked to proposals when created by ATLAS |
| `GET /api/paper/orders/{orderId}` | Reads the broker status; updates the linked proposal and reservation |
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

**Restart:** on startup, `recover_pending()` turns every `submitting` proposal whose
submission lease has expired into `submission_unknown` (event `recovered_after_restart`) and
reconciles it read-only. Its reservation is kept throughout. A `submitting` proposal with a live
lease belongs to another process and is left alone (see Phase 5.5).

Alpaca's docs do not state what a duplicate `client_order_id` or a missing one on lookup
returns, so ATLAS does not rely on resubmitting with the same id.

## Business checks (prepare and again at confirm)

Account `ACTIVE` and not blocked · market open · asset tradable US equity · `fractionable` for
notional buys and fractional sells · buy ≤ `ATLAS_PAPER_MAX_ORDER_NOTIONAL_USD` · capacity
(cash or shares) as defined in **Phase 5.5** below · long position required (no shorts).
Missing broker data needed for a check fails the check (`BROKER_UNAVAILABLE`). Preparing does
not reserve anything; confirmation reserves atomically. Alpaca remains the final authority. The
sell side has no USD cap because no reference quote is used; it is bounded by the position.

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
| 409 (state conflict) | `MARKET_CLOSED`, `PROPOSAL_EXPIRED`, `SUBMISSION_IN_PROGRESS`, `SUBMISSION_UNCERTAIN`, `ORDER_NOT_CANCELABLE`, `RESOURCE_RESERVED`, `RECONCILIATION_REQUIRED` |
| 422 (business rule) | `ACCOUNT_NOT_TRADABLE`, `ASSET_NOT_SUPPORTED`, `FRACTIONAL_NOT_SUPPORTED`, `ORDER_LIMIT_EXCEEDED`, `INSUFFICIENT_BUYING_POWER`, `INSUFFICIENT_POSITION`, `BROKER_REJECTED` |
| 503 (unavailable) | `PAPER_DISABLED`, `PAPER_NOT_CONFIGURED`, `BROKER_UNAVAILABLE` |

## Phase 5.5: atomic reservations

### Defects fixed

A review reproduced two defects at `a78bcac` with the fake broker. Both reproductions are now
regression tests.

| Defect | Before | After |
|---|---|---|
| A. Two sell proposals of 1 share, position 1, both validated before either claimed | Both sent: `['1', '1']` | One sent, the other `RESOURCE_RESERVED` |
| B. A $100 buy left `submission_unknown`, budget $100, a second $100 buy | Second sent | `RECONCILIATION_REQUIRED`, nothing sent |

The Phase 5 claim was atomic per proposal but not across proposals. Uncertain buys had no
local protection.

### Reservations table

`reservations(proposal_id, resource_type cash|shares, symbol, amount, consumed, state,
release_reason, broker_order_id, created_at, updated_at)`. Amounts are decimal strings summed
with Python `Decimal` (never SQLite `REAL`). A partial unique index allows **one active
reservation per proposal**. `CHECK` constraints require a symbol for shares and a release
reason exactly when released.

| State | Meaning | Counted against new orders |
|---|---|---|
| `held` | Claimed locally; Alpaca acknowledgement not observed (in flight or uncertain) | Full amount, unless its order appears in the fresh open-order list |
| `acknowledged` | Alpaca order observed and not final | `amount - consumed`, unless its order appears in the fresh open-order list |
| `released` | `not_sent`, `broker_rejected` or `order_terminal` | No |

### Lifecycle

| Event | Reservation |
|---|---|
| Prepare | None (nothing is reserved) |
| Confirm | `held`, created in the **same transaction** as `open→confirmed/submitting` and the intent event |
| Connection never established | `released (not_sent)`; the proposal can be confirmed again |
| Timeout or other uncertain result | Stays `held`; read-only reconciliation; never resent |
| Accepted | `acknowledged` (accepted is not executed) |
| Partial fill | `acknowledged`, `consumed` updated; the pending part stays protected |
| Fill / cancel / expiry / rejection reported by Alpaca | `released (order_terminal)`, with final `consumed` |
| Explicit 4xx on submit | `released (broker_rejected)` |
| Cancel requested (`pending_cancel`) | Stays `acknowledged` |
| Restart | Rows persist; interrupted submissions become uncertain and keep `held` |

Final statuses are the ones Alpaca documents as "no further updates": `filled`, `canceled`,
`expired`, `rejected`. `replaced`, `done_for_day`, `calculated`, `pending_*`, `stopped`,
`suspended` and unknown statuses keep the reservation. Nothing is released by a timeout, by a
missing broker answer or by proposal expiry after the send started. A lookup that does not find
the order does not release anything.

All updates from order reads, reconciliation, recovery and cancellation go through one function
that updates the proposal and its reservation in the same transaction.

### Confirmation flow

```text
read broker: account, clock, asset, position (buys and sells since 5.6), open orders (status=open, limit 500)
static checks; refresh known commitments from the fresh open-order list / per-order reads
BEGIN IMMEDIATE
  proposal open, not expired, not yet submitted         (conditional UPDATE)
  re-check capacity against ALL active reservations      (other proposals included)
  INSERT reservation 'held'; write submission_intent      (same transaction)
COMMIT
submit once (no transaction is open during HTTP)
record the outcome and reservation state atomically
```

`BEGIN IMMEDIATE` takes SQLite's write lock, so claims from threads, repository instances and
processes sharing the same file are serialized. The guarantee does not depend on an in-memory lock.

### Snapshot policy and double counting

Alpaca documents that open buy orders reduce buying power, that sells do not replenish it until
executed, and that `qty_available` subtracts open orders. It does not document the freshness of
the account and position snapshots, or their consistency with the order list. So capacity uses
two independent views and takes the smaller:

```text
cash   = min(non_marginable_buying_power, cash - Σ open buy notional still held (open-order list))
shares = min(qty_available, qty - Σ open sell remaining qty for the symbol (open-order list))
free   = broker capacity - Σ active ATLAS reservations whose order is NOT in that open-order list
```

- An order already reflected by the snapshot is not subtracted twice (the first term), and an order
  the snapshot does not reflect yet is still subtracted (the second term, or the local reservation).
- A partially filled sell is counted only for its remaining quantity. The filled part already reduced
  `qty`.
- A full page of 500 open orders cannot prove completeness → `RECONCILIATION_REQUIRED`.
- Open orders whose hold cannot be computed (qty-based buys or notional sells placed outside ATLAS)
  are left to the broker's own figure (the first term).

Decision: amount > broker capacity → `INSUFFICIENT_BUYING_POWER` / `INSUFFICIENT_POSITION`
(definitive). Amount > `free` because of local commitments → `RECONCILIATION_REQUIRED` if any
blocking reservation is uncertain, otherwise `RESOURCE_RESERVED` (temporary).

### Multiple processes

The process that claims a proposal stores `submit_owner` and a `submit_lease_until` (120 s; the
HTTP timeout is 10 s). Recovery and `/reconcile` treat a `submitting` proposal as interrupted only
after its lease has expired. Until then it returns `SUBMISSION_IN_PROGRESS` and counts as a held
(not uncertain) reservation.

### Migration

On startup the repository upgrades Phase 5 databases in one transaction (`PRAGMA user_version`
0 → 2). It adds the lease columns and the reservations table, and backfills **conservatively**:
- `submitting` and `submission_unknown` → `held`;
- `submitted` whose last known broker status is not final → `acknowledged`, with `consumed` taken
  from the stored fills;
- final or never-sent proposals → no reservation.

Nothing is deleted or recreated, and the migration runs once.

### New errors

| Code | HTTP | Frontend message |
|---|---|---|
| `RESOURCE_RESERVED` | 409 | "Hay acciones comprometidas por otra orden" / "Hay presupuesto reservado por una operación pendiente" |
| `RECONCILIATION_REQUIRED` | 409 | "Debes consultar el estado antes de intentar otra operación" |

`proposal.reservation` (additive) shows `resourceType`, `symbol`, `amount`, `consumed`, `state`
and `releaseReason`, plus `filledQty` and `filledNotional` since Phase 5.6. There is no endpoint that forces the release of a reservation.

Real backend output with the fake broker:

```json
{json.dumps(ex["reconciliation_required"], indent=2)}
```

```json
{{
  "error": "Paper trading state conflict",
  "message": "Shares are committed by another order. Wait for it to finish or cancel it.",
  "code": "RESOURCE_RESERVED",
  "correlationId": "41843f3348b946bc878ed11ada6d7daa",
  "proposalId": "d2602e0a1118428c9bb7d28099ca101d"
}}
```

Reservation of an uncertain buy:

```json
{json.dumps(ex["uncertain_proposal_reservation"], indent=2)}
```

### Scope of the guarantees

They cover ATLAS proposals that share this SQLite file. Orders placed from the Alpaca dashboard or
other clients only count once Alpaca's snapshots or open-order list show them. Alpaca remains the
final authority and may still reject an order.

The Phase 5.5 residual risk (a snapshot older than a fill that ATLAS already recorded) is closed
by Phase 5.6 below. SQLite on one machine is assumed; a network file system is not supported.

## Phase 5.6: executed consumption and stale snapshots

### Defects fixed

An independent review of `8aa3d4b` showed that fills more recent than the account or position
snapshot could be reused. Both reproductions are now regression tests
(`tests/test_paper_consumption.py`).

| Reproduction (frozen snapshot) | Before (`8aa3d4b`) | After |
|---|---|---|
| A. Budget $100, buy $100 partially filled ($50 executed, $50 open), then a $50 buy | Sent `['100.00', '50.00']` | `RECONCILIATION_REQUIRED`, sent `['100.00']` |
| B. Position 1, sell 1 fully filled, then sell 1 | Sent `['1', '1']` | `RECONCILIATION_REQUIRED`, sent `['1']` |

In 5.5, the open-order list only covered the unfilled remainder, and a reservation was released as
soon as Alpaca reported `filled`. The executed part was then protected by nothing when the snapshot
had not caught up.

### What Alpaca can and cannot prove

The Alpaca docs show no timestamp, version or sequence number on the account object or on positions
(`GET /v2/positions` returns only values). Fill activities carry `transaction_time`, but nothing
links them to a balance or position snapshot. ATLAS therefore never assumes that:
- a later request returns newer data;
- two equal answers prove freshness;
- waiting a fixed time synchronizes endpoints;
- `filled` updates the account or position at the same time;
- an order missing from the open list frees anything.

### Policy: local fill ledger + checkpoint

ATLAS records every fill it observes, cumulatively and per reservation (`filled_qty`,
`filled_notional`, monotonic). Each fill changes two **measures**:

| ATLAS order | `cash` | `qty:<SYMBOL>` |
|---|---|---|
| buy | − filled notional | + filled qty |
| sell | + filled notional | − filled qty |

`ledger_checkpoints(measure, value, base_effect)` stores a trusted value per measure. It is created
inside the claim transaction the first time ATLAS uses the measure, from the snapshot at that
moment, when ATLAS has never touched it. Whether it can later move to a new snapshot is defined in
**Phase 5.7** below: only while ATLAS has never observed a fill on that measure and has nothing
active on it.

```text
expected(measure) = checkpoint.value + (sum of ATLAS effects now − checkpoint.base_effect)

cash available   = min(non_marginable_buying_power, cash − open buy holds, expected cash − open buy holds)
shares available = min(qty_available, qty − open sell remaining, expected qty − open sell remaining)
```

Then the 5.5 rules apply: local reservations not visible in the open-order list are subtracted, and
uncertain submissions block.

### Why nothing is counted twice

If only ATLAS trades the account, a snapshot that includes every observed fill equals the expected
value, and the minimum is just the snapshot. A snapshot that lacks a fill is higher than expected, so
the ledger bound applies and the fill is protected. The pending remainder of an open order is
counted once, through the open-order list or the local reservation. The executed part is counted
once, through the ledger.

### Decisions

| Situation | Result |
|---|---|
| Fits the proven availability (snapshot and ledger) | Allowed |
| Fits the snapshot but not the ledger (executions not reflected yet) | `RECONCILIATION_REQUIRED`: "Recent executions are not yet reflected in the broker balance or position. Check the order status and try again." |
| More than the snapshot shows | `INSUFFICIENT_BUYING_POWER` / `INSUFFICIENT_POSITION` |
| Measure touched by pre-5.6 data (no trusted checkpoint) | `RECONCILIATION_REQUIRED`: "Earlier executions recorded by a previous version cannot be verified. Check the account in Alpaca before another operation." |

### Release conditions

- **Pending part** (`amount − executed`): released only on not-sent, explicit rejection, or a final
  Alpaca status. `pending_cancel` keeps it. A cancel that ends with fills frees only the unfilled
  remainder.
- **Executed part**: never released. It stays in the ledger, also for `expired`, `rejected` or
  `canceled` orders with fills. It stops limiting operations only when broker snapshots catch up
  with it (the snapshot value is then at or below the expected value). There is no timeout and no
  endpoint to override it.

### Monotonic observation

All order reads (refresh, `/orders/{id}`, reconcile, recovery, cancel) go through one function that
updates the proposal, the reservation fills and the audit event in one transaction. Inside that
transaction it refuses (`stale_order_ignored`) any response with fewer filled shares than already
recorded, or a non-final status after a final one. Repeating the same observation changes nothing.
Before each decision ATLAS refreshes **all** active orders, because a buy also changes the share
ledger and a sell also changes the cash ledger.

### Recovery

- **Executions not reflected yet:** retry later. As soon as Alpaca's account or position shows the
  fills, the snapshot equals the ledger and operations are allowed again. `/reconcile` refreshes
  the order status.
- **Restart:** the ledger and checkpoints are in SQLite; nothing is lost and protection continues.
- **Migration** (`user_version` 2 → 3, one transaction): copies stored fills onto each reservation,
  creates `ledger_checkpoints`, and marks every measure touched by pre-5.6 rows as **unverifiable**
  (`value NULL`). Those measures return `RECONCILIATION_REQUIRED`, because no trusted baseline exists
  for fills recorded before the ledger. This only concerns local databases written by the
  unreleased 5.5 code. To recover, check in the Alpaca dashboard that no orders are open, then start
  with a new local database (`backend/var/paper_trading.sqlite3`). Alpaca's data is not affected.

### Operational limits

- The ledger assumes ATLAS is the only client trading this paper account. Trades from the
  dashboard or other clients are not in the ledger. If they lower a balance or position, the
  snapshot shows it and is used. If they raise one (for example a dashboard sale adding cash),
  ATLAS keeps using its lower ledger value until it can move the checkpoint (no ATLAS activity on
  that measure). That is conservative, not unsafe.
- Fill values are recomputed from Alpaca's `filled_qty × filled_avg_price`. A cent-level difference
  with Alpaca's booking can only lower the usable amount by that difference.
- An order whose fills Alpaca already applies to a snapshot but does not yet report on the order
  itself cannot be detected. ATLAS assumes that an order's fill record is never behind its effect
  on the account or position.

## Phase 5.7: a zero net effect is not proof of no fills

### Defect fixed

At `5fa3b84` a checkpoint moved to the current snapshot when nothing was active and the **net**
ATLAS effect since the checkpoint was zero. A buy and a sell that cancel out leave a net effect of
zero, yet both happened. A snapshot frozen between them carries an intermediate, higher value,
and adopting it raised availability.

| Reproduction (fake broker) | Before (`5fa3b84`) | After |
|---|---|---|
| Shares: position 1, buy 1 filled, freeze at 2, sell 1 filled (real 1), then two sales of 1 | Checkpoint 1 → 2, both sent: `['1', '1', '1']` | Checkpoint stays 1; first sent, second `RECONCILIATION_REQUIRED`: `['1', '1']` |
| Cash: cash 100, sell filled (+100), freeze at 200, buy 100 filled (real 100), then two $100 buys | Checkpoint 100 → 200, both sent | Checkpoint stays 100; first sent, second `RECONCILIATION_REQUIRED` |

### Invariant

The snapshot may govern a measure (and its checkpoint may move to the snapshot) **only if ATLAS has
never observed a fill on that measure and has no active reservation on it**. This uses the fill
history (cumulative `filled_qty` / `filled_notional`, monotonic and persisted), not the net effect.
Both paths use the same rule:
- the pre-claim availability check (`_expected`);
- the in-transaction checkpoint update (`_prepare_checkpoints`).

All checkpoint writes were reviewed:
- **Creation:** only when no reservation touches the measure; otherwise it is created unverifiable.
- **Move:** only under the invariant.
- **Migrations:** only ever set `NULL`.

The local history proves that ATLAS fills happened, but it never proves that Alpaca reflects them.
So after a fill, availability stays bounded by the ledger (`min(snapshot, ledger)`). It never
relies on waits, repeated equal reads or an empty open-order list.

### Permanent restriction

After ATLAS observes the first fill on a measure, that measure's checkpoint **never moves again**.
Consequences:
- availability on it stays bounded by `checkpoint + ATLAS fills`;
- decreases made outside ATLAS are still visible through the snapshot;
- increases made outside ATLAS (for example a dashboard sale adding cash, or shares bought in the
  dashboard) are not used by ATLAS.

This is conservative, not unsafe, and there is deliberately no override. Before any ATLAS fill on a
measure, the checkpoint keeps following the snapshot.

### Migration (`user_version` 3 → 4, data only) — superseded by Phase 5.8

It distrusted 5.6 checkpoints by comparing `updated_at` with `created_at`. That was insufficient
(see Phase 5.8) and has been replaced.

## Phase 5.8: repair of v3 and v4 databases

### Defect fixed

Dates cannot prove that a checkpoint kept its initial value. With a fixed clock, a 5.6 checkpoint
inflated from 1 to 2 shares kept `created_at == updated_at`, so the 5.7 migration left it trusted.
After a restart ATLAS allowed selling 2 shares when only 1 existed.

| Reproduction (fake broker, fixed clock) | Before (`2718311`) | After |
|---|---|---|
| v3 database: real position 1, checkpoint `qty:NVDA` = 2, equal dates, frozen snapshot 2; migrate, restart, sell 2 | Checkpoint kept at 2, sale of 2 **sent** | `qty:NVDA` and `cash` unverifiable, `RECONCILIATION_REQUIRED`, **0** new submissions |
| Same database already at v4 | Same over-commitment | Repaired by v5, same result |

### Repair policy (`user_version` → 5, data only, atomic and idempotent)

For any database written at v3 or v4, **every** checkpoint of a measure with recorded ATLAS fills
becomes unverifiable (`value NULL`), whatever its dates or value:
- A fill on any symbol touches both `cash` and `qty:<SYMBOL>`. In practice, after any ATLAS fill,
  `cash` and the share measure of each traded symbol are blocked.
- The persisted fill history (`filled_qty` / `filled_notional` ≠ 0) is used, never the net effect.
- Measures without recorded fills keep their checkpoints. They are safe under the existing rule:
  no ATLAS fill can be missing from their snapshot.
- Checkpoints that were already unverifiable stay so.
- One `checkpoint_distrusted` audit event per measure records the previous value.
- Proposals, reservations, fills and earlier events are never deleted.
- The migration runs in one transaction (a failure leaves the file at its previous version) and
  runs once (`PRAGMA user_version`).

There is no persisted information that could separate a safe v4 checkpoint (created by 5.7 code)
from one contaminated under 5.6. So v4 databases with fills are blocked too. **Additional
restriction:** operations on those measures return `RECONCILIATION_REQUIRED` until manual
recovery: check in the Alpaca dashboard that no orders are open, then start a new local database
(`backend/var/paper_trading.sqlite3`). There is no endpoint or button to override it. Databases
created at v5 are not affected.

## Audit trail

The SQLite `events` table records `proposal_created`, `validation_failed`, `submission_intent`,
`broker_accepted`, `broker_rejected`, `submission_not_sent`, `submission_unknown`,
`reconciled`, `reconcile_not_found`, `recovered_after_restart`, `order_status`,
`proposal_expired`, `cancel_requested`, `cancel_rejected`, `cancel_result`, `order_observed`,
`submission_lease_expired`, `reservation_backfilled`, `stale_order_ignored` and `checkpoint_distrusted`, with ids,
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
    "Preparing does not reserve funds or shares; confirmation re-checks them and Alpaca may still reject the order.",
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
- After submission, poll `GET /api/paper/orders/{brokerOrderId}` (for example every 2–5 s
  while not terminal) to show `brokerStatus`, `filledQty` and `filledAvgPrice`.
  `GET /api/paper/proposals/{id}` only returns what is stored locally and never discovers fills.
  Full policy: `docs/phase-6-integration-handoff.md` → "Polling policy".
- Cancel: an explicit button sending `{"confirmation": "CANCEL_PAPER_ORDER"}`. Show the
  returned status (`pending_cancel` is not `canceled`).
- Send mutating requests from the configured origin. Show `message` and `correlationId` on
  errors.
- `RESOURCE_RESERVED`: show "Hay acciones comprometidas por otra orden" (sell) or "Hay
  presupuesto reservado por una operación pendiente" (buy), with a link to the pending order.
  `RECONCILIATION_REQUIRED`: show "Debes consultar el estado antes de intentar otra operación"
  and offer **Check status** on the uncertain proposal. Since Phase 5.6 it also means "recent
  executions are not yet reflected by the broker": show the message and let the user retry later. Never offer a button that releases a
  reservation. You may show `proposal.reservation` (state, amount, consumed).
- Generating the narrative report must never create or confirm an order.

## Tests

`cd backend && ./.venv/bin/python -m pytest -q` uses a fake broker and `httpx.MockTransport`.
No test calls Alpaca. Coverage includes the disabled server, live configuration rejection,
missing secrets, invalid amounts, assets, fractional rules, market closed, buying power,
positions and open orders, prepare-without-submit, confirm, expiry, immutability, duplicate and
concurrent confirmations, timeout after acceptance, reconciliation, restart recovery, broker
rejection, partial fills, cancellation races, persistence, sanitized errors, and no broker
calls from analysis or narrative. Phase 5.5 adds `tests/test_paper_reservations.py`: concurrent sells
and buys across proposals, uncertain submissions, stale snapshots, double-count prevention,
partial and full fills, cancellation, rejection, not-sent release, repeated confirmation, two
repository instances, rollback, Phase 5 migration, recovery and process leases.

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
  ATLAS reservations protect only ATLAS orders (see Phase 5.5, scope and residual risk).
- An uncertain submission whose order never appears stays uncertain until the user checks Alpaca.
- Polling only, no WebSocket updates. `done_for_day` and similar statuses need polling the next day.
- SQLite is single-machine; delete `backend/var/` to reset local proposals (paper orders at
  Alpaca are not affected).

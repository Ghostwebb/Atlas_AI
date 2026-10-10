# Phase 6 — isolated technical foundation

Based on frontend `fbf3ae3`; API contract checked against backend `cd951e7`.
No dashboard, shared configuration, agent components, styles or backend changes.
This is NOT a complete UI or a deployed integration.

- `types.ts`: backend shapes; monetary values and quantities stay decimal strings.
- `client.ts`: injected fetch transport, no secrets or automatic retries. Browser sets Origin.
- `policy.ts`: pure action eligibility and next status-read selection.
- `contract.test.mjs`: fixture-only tests with Node's built-in runner; no network.

Create the client with the frontend's `NEXT_PUBLIC_API_URL` (default
`http://localhost:8000`). Every confirm/cancel invocation must come from explicit
human authorization. The client alone does NOT prevent duplicate clicks: the future
controller must lock controls and prevent overlapping mutations.

On NETWORK_ERROR, abort, invalid or lost confirmation responses, preserve the
proposal id and enter an uncertain UI state. Read the local proposal and reconcile;
NEVER assume the order was not sent or automatically confirm again.

`nextStatusRead` selects the endpoint, not a polling scheduler. The next stage must
implement one request in flight, backoff, abort on unmount, duplicate-click guards,
and error recovery before wiring the friend's UI. No visual integration yet.

Tests (Node 22+ and the project's TypeScript installed):

```bash
cd frontend
paper_test_build=$(mktemp -d)
./node_modules/.bin/tsc features/paper-trading/types.ts features/paper-trading/client.ts features/paper-trading/policy.ts --target ES2020 --module commonjs --strict --skipLibCheck --outDir "$paper_test_build"
PAPER_TEST_BUILD="$paper_test_build" node --test features/paper-trading/contract.test.mjs
```

Fixture results are not proof of a connection to Alpaca. Keep the permanent label
“Paper Trading — dinero ficticio” when a UI is added. Never mix synthetic analysis
prices with order/account data or turn a committee decision into an order.

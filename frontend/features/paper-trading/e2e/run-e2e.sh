#!/usr/bin/env sh
# Browser integration tests for /paper-trading with intercepted HTTP fixtures (no backend, no Alpaca).
# Needs Playwright with Chromium available outside the project (no dependency is added to package.json):
#   PLAYWRIGHT_MODULE=/path/to/node_modules/playwright  (default: global npm root)
# Starts `next dev` (React StrictMode) on port 3100 unless E2E_APP_URL points to a running server.
set -e
cd "$(dirname "$0")/../../.."
PLAYWRIGHT_MODULE="${PLAYWRIGHT_MODULE:-$(npm root -g)/playwright}"
export PLAYWRIGHT_MODULE
if [ -z "$E2E_APP_URL" ]; then
  export E2E_APP_URL=http://localhost:3100
  NEXT_PUBLIC_API_URL=http://localhost:8000 ./node_modules/.bin/next dev --port 3100 > /tmp/atlas-paper-e2e-next.log 2>&1 &
  SERVER=$!
  trap 'kill $SERVER 2>/dev/null || true' EXIT
  for i in $(seq 1 60); do curl -sf -o /dev/null "$E2E_APP_URL/paper-trading" && break; sleep 2; done
fi
node --test --test-concurrency=1 features/paper-trading/e2e/paper-trading.e2e.mjs

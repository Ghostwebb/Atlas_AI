#!/usr/bin/env sh
# Compiles this folder to a temporary directory and runs the fixture tests (no network).
set -e
cd "$(dirname "$0")/../.."
out=$(mktemp -d)
./node_modules/.bin/tsc features/paper-trading/types.ts features/paper-trading/client.ts \
  features/paper-trading/policy.ts features/paper-trading/validate.ts features/paper-trading/controller.ts \
  --target ES2020 --module commonjs --strict --skipLibCheck --outDir "$out"
PAPER_TEST_BUILD="$out" node --test features/paper-trading/contract.test.mjs features/paper-trading/controller.test.mjs

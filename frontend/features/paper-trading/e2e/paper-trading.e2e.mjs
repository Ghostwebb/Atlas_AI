/* Browser integration tests for /paper-trading (real React mount in Chromium).
   Every backend call is intercepted with HTTP fixtures: no backend, no Alpaca, no credentials.
   Run with run-e2e.sh (it starts the Next.js dev server, which uses React StrictMode). */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const { chromium } = await import(pathToFileURL(path.join(process.env.PLAYWRIGHT_MODULE, 'index.mjs')).href);
const APP = process.env.E2E_APP_URL ?? 'http://localhost:3100';
const API = 'http://localhost:8000';
const SHOTS = process.env.E2E_SCREENSHOTS ?? '';
const BASE = Date.parse('2026-10-05T15:00:00Z');
const P = '0123456789abcdef0123456789abcdef';
const O = '5f1c7e2a-0000-4000-8000-000000000001';

// --- simulated fixtures (shapes from docs/phase-6-integration-handoff.md) -------------------
const STATUS = { environment: 'paper', enabled: true, configured: true, brokerReachable: true, marketOpen: true,
  maxOrderNotionalUsd: '1000', proposalTtlSeconds: 300, message: 'Connected to Alpaca Paper.',
  analysisDataNotice: 'ATLAS analysis uses a synthetic demo dataset.' };
const ACCOUNT = { environment: 'paper', status: 'ACTIVE', currency: 'USD', cash: '1000', buyingPower: '1000',
  nonMarginableBuyingPower: '1000', equity: null, tradingBlocked: false, accountBlocked: false };
const POSITIONS = [{ environment: 'paper', symbol: 'NVDA', side: 'long', qty: '2', qtyAvailable: '2',
  avgEntryPrice: '100', marketValue: '500', assetClass: 'us_equity' }];
const iso = ms => new Date(BASE + ms).toISOString();
const proposal = (patch = {}) => ({
  id: P, environment: 'paper', symbol: 'NVDA', side: 'buy', notional: '100.00', qty: null, orderType: 'market',
  timeInForce: 'day', clientOrderId: `atlas-${P}`, analysisReference: null, createdAt: iso(0), expiresAt: iso(300_000),
  status: 'open', submissionStatus: 'not_submitted', brokerOrderId: null, brokerStatus: null, filledQty: null,
  filledAvgPrice: null, lastErrorCode: null, updatedAt: iso(0), reservation: null,
  checks: [{ name: 'market_open', passed: true, detail: 'regular session open' },
    { name: 'buying_power', passed: true, detail: 'available 1000' }],
  warnings: ['Paper trading: simulated money in an Alpaca Paper account.',
    'Market order: the execution price is not known in advance and is not guaranteed.'],
  ...patch,
});
const reservation = (patch = {}) => ({ resourceType: 'cash', symbol: null, amount: '100.00', consumed: '0',
  state: 'acknowledged', releaseReason: null, filledQty: '0', filledNotional: '0', ...patch });
const submitted = (patch = {}) => proposal({ status: 'confirmed', submissionStatus: 'submitted', brokerOrderId: O,
  brokerStatus: 'accepted', filledQty: '0', reservation: reservation(), ...patch });
const order = (patch = {}) => ({ id: O, clientOrderId: `atlas-${P}`, symbol: 'NVDA', side: 'buy', type: 'market',
  timeInForce: 'day', qty: null, notional: '100.00', filledQty: '0', filledAvgPrice: null, status: 'accepted',
  brokerStatusRaw: 'accepted', submittedAt: iso(1000), filledAt: null, canceledAt: null, proposalId: P,
  environment: 'paper', ...patch });
const ok = body => ({ status: 200, body });
const err = (status, code, message = `msg ${code}`) => ({ status, body: { error: 'x', message, code,
  correlationId: `corr-${code.toLowerCase()}`, proposalId: P } });
const NETWORK = 'network';
function held() { let release; const promise = new Promise(r => { release = r; }); return { held: promise, release }; }

// --- harness --------------------------------------------------------------------------------
let browser;
before(async () => { browser = await chromium.launch(); });
after(async () => { await browser?.close(); });

async function open({ viewport = { width: 1280, height: 900 }, path: route = '/paper-trading', defaults = true } = {}) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const calls = [];
  const queues = new Map();
  const sticky = new Map();
  const unexpected = [];
  const api = {
    calls, unexpected,
    on: (key, ...specs) => queues.set(key, [...(queues.get(key) ?? []), ...specs]),
    always: (key, spec) => sticky.set(key, spec),
    count: key => calls.filter(c => c === key).length,
    paperMutations: () => calls.filter(c => c.startsWith('POST /api/paper')),
  };
  if (defaults) {
    api.always('GET /api/paper/status', ok(STATUS));
    api.always('GET /api/paper/account', ok(ACCOUNT));
    api.always('GET /api/paper/positions', ok(POSITIONS));
  }
  // Only the app itself is reachable; everything else (fonts, real backend) is blocked.
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === new URL(APP).origin) return route.continue();
    if (url.origin !== API) return route.abort();
    const key = `${route.request().method()} ${url.pathname}`;
    calls.push(key);
    const queue = queues.get(key);
    let spec = queue && queue.length ? queue.shift() : sticky.get(key);
    if (!spec) { unexpected.push(key); return route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }); }
    try {
      if (spec.held) spec = await spec.held;
      if (spec === NETWORK) return await route.abort('connectionreset');
      await route.fulfill({ status: spec.status, contentType: 'application/json', body: JSON.stringify(spec.body),
        headers: { 'access-control-allow-origin': '*' } });
    } catch { /* the page aborted the request (unmount / dispose) */ }
  });
  await page.clock.install({ time: BASE });
  await page.goto(`${APP}${route}`);
  return { page, api, context };
}

const settle = async page => { await page.clock.runFor(50); await page.waitForTimeout(80); };
const tick = async (page, ms) => { await page.clock.runFor(ms); await page.waitForTimeout(120); };
const button = (page, name) => page.getByRole('button', { name, exact: true });
const text = (page, value) => page.getByText(value, { exact: false }).first();

async function prepare(page, api, response = ok(proposal())) {
  api.on('POST /api/paper/proposals', response);
  await page.getByLabel('Símbolo').fill('NVDA');
  await page.getByLabel('Importe en USD').fill('100.00');
  await button(page, 'Preparar propuesta').click();
}
async function toTracking(page, api) {
  await prepare(page, api);
  await page.getByRole('heading', { name: 'Revisa la propuesta antes de confirmar' }).waitFor();
  api.on(`POST /api/paper/proposals/${P}/confirm`, ok(submitted()));
  await button(page, 'Confirmar orden paper').click();
  await page.getByRole('heading', { name: 'Siguiendo la orden' }).waitFor();
}
async function noResend(page) {
  assert.equal(await page.getByRole('button', { name: /reenviar|reintentar|volver a enviar/i }).count(), 0);
}
async function shot(page, name) { if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true }); }

// --- tests ----------------------------------------------------------------------------------

test('1. prepare → review → explicit confirmation', async () => {
  const { page, api, context } = await open();
  await page.getByText('Paper Trading — dinero ficticio').first().waitFor();
  await text(page, 'Disponible').waitFor();
  assert.equal(await page.getByText('No disponible').count() > 0, true); // equity is null in the fixture
  await prepare(page, api);
  const heading = page.getByRole('heading', { name: 'Revisa la propuesta antes de confirmar' });
  await heading.waitFor();
  assert.equal(await heading.evaluate(h => document.activeElement === h), true, 'focus moves to the review');
  await text(page, 'Preparar no ha enviado la orden ni reservado recursos').waitFor();
  await text(page, 'market_open').waitFor();
  await text(page, 'Market order: the execution price').waitFor();
  await page.getByText(/quedan [45]:[0-5]\d/).first().waitFor();
  await tick(page, 10_000);
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 0, 'preparing never confirms');
  await shot(page, 'desktop-review');
  api.on(`POST /api/paper/proposals/${P}/confirm`, ok(submitted()));
  await button(page, 'Confirmar orden paper').click();
  await page.getByRole('heading', { name: 'Siguiendo la orden' }).waitFor();
  await text(page, 'Enviada a Alpaca Paper').waitFor();
  await text(page, 'Aceptada').waitFor();
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 1);
  assert.deepEqual(api.unexpected, []);
  await context.close();
});

test('2. double click sends a single confirmation', async () => {
  const { page, api, context } = await open();
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  const gate = held();
  api.on(`POST /api/paper/proposals/${P}/confirm`, gate);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('Confirmar orden paper'));
    b.click(); b.click(); b.click();
  });
  await text(page, 'Confirmando…').waitFor();
  gate.release(ok(submitted()));
  await page.getByRole('heading', { name: 'Siguiendo la orden' }).waitFor();
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 1);
  await context.close();
});

test('3. expired proposal cannot be confirmed', async () => {
  const { page, api, context } = await open();
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  await tick(page, 301_000);
  await text(page, 'La propuesta venció sin enviarse').waitFor();
  assert.equal(await button(page, 'Confirmar orden paper').isDisabled(), true);
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 0);
  await context.close();
});

test('4. lost confirmation → uncertain → status check without resending', async () => {
  const { page, api, context } = await open();
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  api.on(`POST /api/paper/proposals/${P}/confirm`, NETWORK);
  const read = held();
  api.on(`GET /api/paper/proposals/${P}`, read);
  await button(page, 'Confirmar orden paper').click();
  await text(page, 'Se perdió la respuesta de la confirmación').waitFor();
  await page.getByRole('heading', { name: 'Resultado incierto' }).waitFor();
  await noResend(page);
  assert.equal(await page.getByText('Abierta (sin enviar)').count(), 0, 'never claims it was not sent');
  assert.equal(await page.getByRole('button', { name: 'Confirmar orden paper' }).count(), 0);
  await text(page, 'NETWORK_ERROR').waitFor({ state: 'attached' });
  await shot(page, 'desktop-uncertain');
  read.release(ok(submitted()));
  await page.getByRole('heading', { name: 'Siguiendo la orden' }).waitFor();
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 1, 'never resent');
  await context.close();
});

test('5. partial fill → final fill stops tracking', async () => {
  const { page, api, context } = await open();
  await toTracking(page, api);
  api.on(`GET /api/paper/orders/${O}`, ok(order({ status: 'partially_filled', filledQty: '0.5', filledAvgPrice: '100' })),
    ok(order({ status: 'filled', filledQty: '0.99', filledAvgPrice: '101.01' })));
  api.on(`GET /api/paper/proposals/${P}`, ok(submitted({ brokerStatus: 'partially_filled', filledQty: '0.5',
    reservation: reservation({ consumed: '50.0', filledQty: '0.5', filledNotional: '50.0' }) })),
  ok(submitted({ brokerStatus: 'filled', filledQty: '0.99', reservation: reservation({ state: 'released',
    releaseReason: 'order_terminal', consumed: '100.00', filledQty: '0.99', filledNotional: '100.00' }) })));
  await tick(page, 3000);
  await text(page, 'Ejecutada parcialmente').waitFor();
  await text(page, '0.5 acciones').waitFor();
  await shot(page, 'desktop-tracking');
  await tick(page, 3000);
  await page.getByRole('heading', { name: 'Operación finalizada' }).waitFor();
  await text(page, '0.99 acciones').waitFor();
  await text(page, 'Seguimiento detenido').waitFor();
  const reads = api.count(`GET /api/paper/orders/${O}`);
  await tick(page, 60_000);
  assert.equal(api.count(`GET /api/paper/orders/${O}`), reads, 'no polling after a final state');
  await context.close();
});

test('6. pending cancel → canceled', async () => {
  const { page, api, context } = await open();
  await toTracking(page, api);
  api.on(`POST /api/paper/orders/${O}/cancel`, ok({ cancelRequested: true, order: order({ status: 'pending_cancel' }) }));
  api.on(`GET /api/paper/orders/${O}`, ok(order({ status: 'pending_cancel' })), ok(order({ status: 'canceled' })));
  api.on(`GET /api/paper/proposals/${P}`, ok(submitted({ brokerStatus: 'pending_cancel' })),
    ok(submitted({ brokerStatus: 'canceled', reservation: reservation({ state: 'released', releaseReason: 'order_terminal' }) })));
  await button(page, 'Cancelar orden').click();
  await text(page, 'Cancelación pendiente: Alpaca aún no la ha confirmado').waitFor();
  assert.equal(await button(page, 'Cancelar orden').isDisabled(), true);
  await tick(page, 3000);
  await page.getByRole('heading', { name: 'Operación finalizada' }).waitFor();
  await text(page, 'Cancelada').waitFor();
  assert.equal(api.count(`POST /api/paper/orders/${O}/cancel`), 1);
  await context.close();
});

test('7. cancel that loses the race against a fill', async () => {
  const { page, api, context } = await open();
  await toTracking(page, api);
  api.on(`POST /api/paper/orders/${O}/cancel`, ok({ cancelRequested: true, order: order({ status: 'filled', filledQty: '1' }) }));
  api.on(`GET /api/paper/orders/${O}`, ok(order({ status: 'filled', filledQty: '1', filledAvgPrice: '100' })));
  api.on(`GET /api/paper/proposals/${P}`, ok(submitted({ brokerStatus: 'filled', filledQty: '1' })));
  await button(page, 'Cancelar orden').click();
  await page.getByRole('heading', { name: 'Operación finalizada' }).waitFor();
  await text(page, 'Ejecutada').waitFor();
  await text(page, '1 acciones').waitFor();
  await context.close();
});

test('8. reserved resources and reconciliation required', async () => {
  const { page, api, context } = await open();
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  api.on(`POST /api/paper/proposals/${P}/confirm`, err(409, 'RESOURCE_RESERVED'), err(409, 'RECONCILIATION_REQUIRED'));
  api.on(`GET /api/paper/proposals/${P}`, ok(proposal()), ok(proposal()));
  await button(page, 'Confirmar orden paper').click();
  await text(page, 'Hay presupuesto reservado por una operación pendiente').waitFor();
  await page.getByText('Detalle técnico').first().click();
  await text(page, 'corr-resource_reserved').waitFor();
  await page.waitForFunction(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('Confirmar orden paper'));
    return b && !b.disabled;
  });
  await button(page, 'Confirmar orden paper').click();
  await text(page, 'Debes consultar el estado antes de intentar otra operación').waitFor();
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 2, 'each confirmation is a separate human click');
  assert.equal(await page.getByRole('button', { name: /liberar|forzar/i }).count(), 0);
  await context.close();
});

test('9. unknown broker status: status checks allowed, cancel blocked', async () => {
  const { page, api, context } = await open();
  await toTracking(page, api);
  api.on(`GET /api/paper/orders/${O}`, ok(order({ status: 'held_somewhere', brokerStatusRaw: 'held_somewhere' })),
    ok(order({ status: 'held_somewhere', brokerStatusRaw: 'held_somewhere' })));
  api.on(`GET /api/paper/proposals/${P}`, ok(submitted({ brokerStatus: 'held_somewhere' })),
    ok(submitted({ brokerStatus: 'held_somewhere' })));
  await tick(page, 3000);
  await text(page, 'Desconocido').waitFor();
  await text(page, 'puedes consultar, pero no cancelar').waitFor();
  assert.equal(await button(page, 'Cancelar orden').isDisabled(), true);
  assert.equal(await button(page, 'Consultar estado').isDisabled(), false);
  await button(page, 'Consultar estado').click();
  await settle(page);
  assert.equal(api.count(`GET /api/paper/orders/${O}`), 2);
  assert.equal(api.count(`POST /api/paper/orders/${O}/cancel`), 0);
  await context.close();
});

test('10. wrong-identity responses block actions', async () => {
  const { page, api, context } = await open();
  await prepare(page, api, ok(proposal({ symbol: 'TSLA', side: 'sell', notional: null, qty: '2' })));
  await text(page, 'devolvió datos inválidos o de otra operación').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Confirmar orden paper' }).count(), 0);
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 0);
  // Later read with the same id but another operation.
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  api.on(`POST /api/paper/proposals/${P}/confirm`, ok(submitted()));
  await button(page, 'Confirmar orden paper').click();
  await page.getByRole('heading', { name: 'Siguiendo la orden' }).waitFor();
  api.on(`GET /api/paper/orders/${O}`, ok(order()));
  api.on(`GET /api/paper/proposals/${P}`, ok(submitted({ symbol: 'TSLA' })));
  await tick(page, 3000);
  await text(page, 'no era coherente con esta operación').waitFor();
  assert.equal(await button(page, 'Cancelar orden').isDisabled(), true);
  await text(page, 'OPERACIÓN NVDA').waitFor(); // identity unchanged on screen
  assert.equal(api.count(`POST /api/paper/orders/${O}/cancel`), 0);
  await context.close();
});

test('11. unmount and remount: no duplicate polling and no late responses', async () => {
  const { page, api, context } = await open();
  await toTracking(page, api);
  const late = held();
  api.on(`GET /api/paper/orders/${O}`, late);
  await tick(page, 3000); // the read is now held in flight
  await page.getByRole('link', { name: '← Volver al dashboard' }).click();
  await page.waitForURL(`${APP}/`);
  const before = api.count(`GET /api/paper/orders/${O}`);
  await tick(page, 30_000);
  assert.equal(api.count(`GET /api/paper/orders/${O}`), before, 'no polling while unmounted');
  api.always(`GET /api/paper/proposals/${P}`, ok(submitted()));
  api.always(`GET /api/paper/orders/${O}`, ok(order()));
  await page.goBack();
  await page.waitForURL(`${APP}/paper-trading`);
  await page.getByRole('heading', { name: 'Siguiendo la orden' }).waitFor(); // resumed read-only from this tab
  late.release(ok(order({ status: 'filled', filledQty: '1' }))); // late answer for the disposed controller
  const start = api.count(`GET /api/paper/orders/${O}`);
  await tick(page, 3000); await tick(page, 3000); await tick(page, 3000);
  assert.equal(api.count(`GET /api/paper/orders/${O}`) - start, 3, 'one polling loop, not two');
  assert.equal(await page.getByText('Ejecutada', { exact: true }).count(), 0, 'the late "filled" answer was ignored');
  await text(page, 'Aceptada').waitFor();
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 1, 'resume never confirms');
  await context.close();
});

test('12. dashboard report and analysis make no paper preparation, confirmation or cancel calls', async () => {
  const { page, api, context } = await open({ path: '/', defaults: false });
  api.always('POST /api/report', err(503, 'MODEL_UNAVAILABLE', 'Informe no disponible (fixture).'));
  api.always('POST /api/analyze', err(503, 'UNAVAILABLE', 'Análisis no disponible (fixture).'));
  await page.getByLabel('Símbolo del informe').fill('NVDA');
  await button(page, 'Generar informe').click();
  await text(page, 'Informe no disponible (fixture).').waitFor();
  await page.getByLabel('Analyze ticker').fill('NVDA');
  await page.getByLabel('Analyze ticker').press('Enter');
  await settle(page);
  assert.ok(api.count('POST /api/report') >= 1);
  assert.deepEqual(api.calls.filter(c => c.includes('/api/paper')), []);
  await context.close();
});

test('12b. committee view (friend branch, optional) makes no paper calls', { skip: !process.env.E2E_COMMITTEE_URL }, async () => {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const paper = [];
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/')) { paper.push(`${route.request().method()} ${url.pathname}`); return route.abort(); }
    return url.origin === new URL(process.env.E2E_COMMITTEE_URL).origin ? route.continue() : route.abort();
  });
  await page.goto(`${process.env.E2E_COMMITTEE_URL}/agents-preview`);
  await page.waitForLoadState('networkidle');
  const buttons = page.getByRole('button');
  for (let i = 0; i < Math.min(await buttons.count(), 25); i++) {
    const b = buttons.nth(i);
    if (await b.isVisible() && await b.isEnabled()) await b.click({ timeout: 2000 }).catch(() => {});
  }
  await page.waitForTimeout(1500);
  assert.deepEqual(paper.filter(c => c.includes('/api/paper')), []);
  await context.close();
});

test('13. layout: no horizontal scroll on desktop and mobile', async () => {
  for (const [name, viewport] of [['desktop', { width: 1440, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
    const { page, api, context } = await open({ viewport });
    await toTracking(page, api);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, `${name}: horizontal overflow ${overflow}px`);
    await shot(page, `${name}-tracking-full`);
    if (name === 'mobile') {
      await page.getByRole('heading', { name: 'Siguiendo la orden' }).focus();
      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => document.activeElement?.textContent);
      assert.match(focused ?? '', /Consultar estado|Cancelar orden/);
    }
    await context.close();
  }
});

// --- recovery after reload (review of f2a6010) ---------------------------------------------

test('R1. lost confirmation + reload stays uncertain; backend evolution recovers without confirming again', async () => {
  const { page, api, context } = await open();
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  api.on(`POST /api/paper/proposals/${P}/confirm`, NETWORK);
  api.always(`GET /api/paper/proposals/${P}`, ok(proposal())); // backend still shows open + not_submitted
  await button(page, 'Confirmar orden paper').click();
  await page.getByRole('heading', { name: 'Resultado incierto' }).waitFor();
  await page.reload();
  await page.getByRole('heading', { name: 'Resultado incierto' }).waitFor();
  await settle(page);
  assert.equal(await page.getByRole('button', { name: 'Confirmar orden paper' }).count(), 0, 'no confirm after reload');
  await noResend(page);
  await button(page, 'Consultar estado').click(); await settle(page);
  await page.getByRole('heading', { name: 'Resultado incierto' }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Confirmar orden paper' }).count(), 0);
  // The backend evolves: submitting → (reconcile) in progress → uncertain → submitted.
  api.always(`GET /api/paper/proposals/${P}`, ok(proposal({ status: 'confirmed', submissionStatus: 'submitting' })));
  api.on(`POST /api/paper/proposals/${P}/reconcile`, err(409, 'SUBMISSION_IN_PROGRESS'), err(409, 'SUBMISSION_UNCERTAIN'),
    ok(submitted()));
  await button(page, 'Consultar estado').click(); await settle(page);
  await text(page, 'Enviándose (lease activa)').waitFor();
  for (let i = 0; i < 3; i++) { await button(page, 'Consultar estado').click(); await settle(page); }
  await page.getByRole('heading', { name: 'Siguiendo la orden' }).waitFor();
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 1, 'POST /confirm stays at one');
  await context.close();
});

const KEY = 'atlas.paperTrading.operation';
const storedRecord = page => page.evaluate(k => JSON.parse(sessionStorage.getItem(k) ?? 'null'), KEY);
async function seedAndReload(page, entries) {
  await page.evaluate(e => { sessionStorage.clear(); for (const [k, v] of e) sessionStorage.setItem(k, v); }, entries);
  await page.reload();
}

test('R2. reload while the confirm request is still in flight', async () => {
  const { page, api, context } = await open();
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  api.on(`POST /api/paper/proposals/${P}/confirm`, held()); // never answered
  api.always(`GET /api/paper/proposals/${P}`, ok(proposal()));
  await button(page, 'Confirmar orden paper').click();
  await text(page, 'Confirmando…').waitFor();
  assert.equal((await storedRecord(page)).pendingConfirm, true, 'intent stored before the response');
  await page.reload();
  await page.getByRole('heading', { name: 'Resultado incierto' }).waitFor();
  await settle(page);
  assert.equal(await page.getByRole('button', { name: 'Confirmar orden paper' }).count(), 0);
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 1);
  await context.close();
});

test('R3. failed_before_submit after reload: review again, no automatic confirm', async () => {
  const { page, api, context } = await open();
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  api.on(`POST /api/paper/proposals/${P}/confirm`, NETWORK);
  api.always(`GET /api/paper/proposals/${P}`, ok(proposal()));
  await button(page, 'Confirmar orden paper').click();
  await page.getByRole('heading', { name: 'Resultado incierto' }).waitFor();
  api.always(`GET /api/paper/proposals/${P}`, ok(proposal({ submissionStatus: 'failed_before_submit' })));
  await page.reload();
  await page.getByRole('heading', { name: 'Revisa la propuesta antes de confirmar' }).waitFor();
  await tick(page, 10_000);
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 1, 'a new human click is required');
  assert.equal(await button(page, 'Confirmar orden paper').isDisabled(), false);
  assert.equal((await storedRecord(page)).pendingConfirm, false);
  await context.close();
});

test('R4. confirmed operation + reload keeps tracking with one polling loop', async () => {
  const { page, api, context } = await open();
  await toTracking(page, api);
  api.always(`GET /api/paper/proposals/${P}`, ok(submitted()));
  api.always(`GET /api/paper/orders/${O}`, ok(order()));
  await page.reload();
  await page.getByRole('heading', { name: 'Siguiendo la orden' }).waitFor();
  await settle(page);
  const start = api.count(`GET /api/paper/orders/${O}`);
  await tick(page, 3000); await tick(page, 3000); await tick(page, 3000);
  assert.equal(api.count(`GET /api/paper/orders/${O}`) - start, 3, 'no duplicate polling after reload (StrictMode)');
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 1);
  await context.close();
});

test('R5. backend expiry after reload ends the uncertainty', async () => {
  const { page, api, context } = await open();
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  api.on(`POST /api/paper/proposals/${P}/confirm`, NETWORK);
  api.always(`GET /api/paper/proposals/${P}`, ok(proposal()));
  await button(page, 'Confirmar orden paper').click();
  await page.getByRole('heading', { name: 'Resultado incierto' }).waitFor();
  api.always(`GET /api/paper/proposals/${P}`, ok(proposal({ status: 'expired' })));
  await page.reload();
  await text(page, 'La propuesta venció sin enviarse').waitFor();
  assert.equal(await button(page, 'Confirmar orden paper').isDisabled(), true);
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 1);
  await context.close();
});

test('R6. storage write failure: no confirmation is sent', async () => {
  const { page, api, context } = await open();
  await prepare(page, api);
  await button(page, 'Confirmar orden paper').waitFor();
  await page.evaluate(() => { Storage.prototype.setItem = () => { throw new Error('QuotaExceededError'); }; });
  await button(page, 'Confirmar orden paper').click();
  await text(page, 'No se pudo guardar el registro de seguridad').waitFor();
  await settle(page);
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 0);
  assert.equal(await button(page, 'Confirmar orden paper').isDisabled(), true);
  await context.close();
});

test('R7. corrupt record: nothing recovered; legacy id-only record: recovered as uncertain', async () => {
  const { page, api, context } = await open();
  await seedAndReload(page, [[KEY, '{"v":1,"proposalId":']]);
  await text(page, 'no se pudo leer').waitFor();
  await settle(page);
  assert.equal(api.calls.filter(c => c.startsWith(`GET /api/paper/proposals`)).length, 0);
  api.always(`GET /api/paper/proposals/${P}`, ok(proposal()));
  await seedAndReload(page, [['atlas.paperTrading.proposalId', P]]);
  await page.getByRole('heading', { name: 'Resultado incierto' }).waitFor();
  await text(page, 'de formato anterior').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Confirmar orden paper' }).count(), 0);
  assert.equal(api.count(`POST /api/paper/proposals/${P}/confirm`), 0);
  await context.close();
});

test('R8. lost cancel + reload: cancel blocked until the order is read', async () => {
  const { page, api, context } = await open();
  await toTracking(page, api);
  api.on(`POST /api/paper/orders/${O}/cancel`, NETWORK);
  api.on(`GET /api/paper/orders/${O}`, held());
  await button(page, 'Cancelar orden').click();
  await text(page, 'No se confirmó el resultado de la cancelación').waitFor();
  assert.equal((await storedRecord(page)).pendingCancel, true);
  api.always(`GET /api/paper/proposals/${P}`, ok(submitted()));
  await page.reload();
  await page.getByRole('heading', { name: 'Siguiendo la orden' }).waitFor();
  assert.equal(await button(page, 'Cancelar orden').isDisabled(), true);
  api.always(`GET /api/paper/orders/${O}`, ok(order()));
  await button(page, 'Consultar estado').click(); await settle(page);
  await page.waitForFunction(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('Cancelar orden'));
    return b && !b.disabled;
  });
  assert.equal(api.count(`POST /api/paper/orders/${O}/cancel`), 1);
  await context.close();
});

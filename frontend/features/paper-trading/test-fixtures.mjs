/* Shared HTTP fixtures, manual clock/scheduler and controller setup for the tests.
   Fixture data is simulated (shapes from docs/phase-6-integration-handoff.md); it is not Alpaca. */
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
export const load = name => import(pathToFileURL(path.join(process.env.PAPER_TEST_BUILD, name)).href);
const { createPaperClient } = await load('client.js');
const { createPaperTradingController } = await load('controller.js');

export const BASE = Date.parse('2026-10-05T15:00:00Z');
export const flush = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); };

// --- fixtures (simulated; shapes from docs/phase-6-integration-handoff.md) -------------
export const proposalFx = (patch = {}) => ({
  id: 'p1', environment: 'paper', symbol: 'NVDA', side: 'buy', notional: '100.00', qty: null,
  orderType: 'market', timeInForce: 'day', clientOrderId: 'atlas-p1', analysisReference: null,
  createdAt: '2026-10-05T15:00:00Z', expiresAt: '2026-10-05T15:05:00Z', status: 'open',
  submissionStatus: 'not_submitted', brokerOrderId: null, brokerStatus: null, filledQty: null,
  filledAvgPrice: null, lastErrorCode: null, checks: [{ name: 'market_open', passed: true, detail: 'open' }],
  warnings: ['Paper trading: simulated money in an Alpaca Paper account.'], updatedAt: '2026-10-05T15:00:00Z',
  reservation: null, ...patch,
});
export const reservationFx = (patch = {}) => ({ resourceType: 'cash', symbol: null, amount: '100.00', consumed: '0',
  state: 'acknowledged', releaseReason: null, filledQty: '0', filledNotional: '0', ...patch });
export const submittedFx = (patch = {}) => proposalFx({ status: 'confirmed', submissionStatus: 'submitted',
  brokerOrderId: 'o1', brokerStatus: 'accepted', filledQty: '0', reservation: reservationFx(), ...patch });
export const orderFx = (patch = {}) => ({ id: 'o1', clientOrderId: 'atlas-p1', symbol: 'NVDA', side: 'buy', type: 'market',
  timeInForce: 'day', qty: null, notional: '100.00', filledQty: '0', filledAvgPrice: null, status: 'accepted',
  brokerStatusRaw: 'accepted', submittedAt: '2026-10-05T15:00:01Z', filledAt: null, canceledAt: null,
  proposalId: 'p1', environment: 'paper', ...patch });

export const ok = body => ({ status: 200, body });
export const err = (status, code) => ({ status, body: { error: 'x', message: `msg ${code}`, code, correlationId: `c-${code}`, proposalId: 'p1' } });
export const lost = () => new TypeError('connection lost');
export function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { deferred: promise, resolve };
}

export function fixtureServer({ ignoreAbort = false } = {}) {
  const calls = [];
  const urls = [];
  const queues = new Map();
  const unexpected = [];
  const on = (key, ...responses) => queues.set(key, [...(queues.get(key) ?? []), ...responses]);
  const transport = (url, init) => {
    const u = new URL(url);
    const key = `${init.method} ${u.pathname.replace('/api/paper', '')}`;
    calls.push(key); urls.push(url);
    const queue = queues.get(key);
    if (!queue || queue.length === 0) { unexpected.push(key); return Promise.reject(new TypeError('no fixture')); }
    const spec = queue.shift();
    return new Promise((resolve, reject) => {
      const abort = () => reject(new DOMException('aborted', 'AbortError'));
      if (!ignoreAbort) {
        if (init.signal?.aborted) return abort();
        init.signal?.addEventListener('abort', abort);
      }
      const deliver = s => {
        if (s instanceof Error) return reject(s);
        if (typeof s === 'string') return resolve(new Response(s, { status: 200 }));
        resolve(Response.json(s.body, { status: s.status }));
      };
      if (spec.deferred) spec.deferred.then(deliver); else deliver(spec);
    });
  };
  const count = key => calls.filter(c => c === key).length;
  const clear = key => queues.delete(key);
  return { on, clear, transport, calls, urls, unexpected, count };
}

export function manualScheduler() {
  let t = 0; let next = 0;
  const timers = new Map();
  return {
    now: () => BASE + t,
    setTimeout(fn, ms) { const id = ++next; timers.set(id, { at: t + ms, fn }); return id; },
    clearTimeout(id) { timers.delete(id); },
    async advance(ms) {
      const end = t + ms;
      for (;;) {
        const due = [...timers.entries()].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        t = due[1].at; timers.delete(due[0]); due[1].fn(); await flush();
      }
      t = end; await flush();
    },
    get size() { return timers.size; },
  };
}

/** journal: null (default, no persistence) or an OperationJournal. Reuse server/clock to simulate a reload. */
export function setup(serverOptions, { journal = null, server: reuseServer, clock: reuseClock } = {}) {
  const server = reuseServer ?? fixtureServer(serverOptions);
  const clock = reuseClock ?? manualScheduler();
  const client = createPaperClient('http://fixture', server.transport);
  const ctl = createPaperTradingController({ client, journal, source: 'fixture', now: clock.now, scheduler: clock,
    pollIntervalMs: 3000 });
  return { server, clock, ctl, s: () => ctl.getState() };
}

/** In-memory Storage double (sessionStorage shape) with failure switches. */
export function memoryStorage() {
  const data = new Map();
  return {
    failWrites: false, failReads: false,
    getItem(k) { if (this.failReads) throw new Error('blocked'); return data.has(k) ? data.get(k) : null; },
    setItem(k, v) { if (this.failWrites) throw new Error('QuotaExceededError'); data.set(k, String(v)); },
    removeItem(k) { data.delete(k); },
    raw: data,
  };
}
export const BUY = { symbol: 'NVDA', side: 'buy', notional: '100.00' };

export async function toReview(t) {
  t.server.on('POST /proposals', ok(proposalFx()));
  assert.deepEqual(await t.ctl.prepare(BUY), { ok: true });
}
export async function toTracking(t) {
  await toReview(t);
  t.server.on('POST /proposals/p1/confirm', ok(submittedFx()));
  assert.deepEqual(await t.ctl.confirm(), { ok: true });
  assert.equal(t.s().phase, 'tracking');
}


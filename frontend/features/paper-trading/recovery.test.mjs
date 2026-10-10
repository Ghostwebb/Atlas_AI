/* Recovery after reload (review of f2a6010): a recorded confirm/cancel intent survives the reload and
   keeps the operation uncertain until the backend answers conclusively. Fixtures only. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { flush, proposalFx, submittedFx, orderFx, ok, err, lost, deferred, setup, BUY, load, memoryStorage } from './test-fixtures.mjs';
const { createStorageJournal, JOURNAL_KEY, LEGACY_KEY, parseJournal } = await load('journal.js');

const CONFIRM = 'POST /proposals/p1/confirm';
const record = storage => JSON.parse(storage.raw.get(JOURNAL_KEY));

function tab(storage = memoryStorage(), shared = {}) {
  const journal = createStorageJournal(() => storage);
  const t = setup(undefined, { journal, ...shared });
  return { ...t, storage, journal };
}
/** Simulates a reload: the old controller is gone; a new one reads the same tab storage. */
function reload(t) {
  t.ctl.dispose();
  return tab(t.storage, { server: t.server, clock: t.clock });
}
async function reviewed(t) {
  t.server.on('POST /proposals', ok(proposalFx()));
  assert.deepEqual(await t.ctl.prepare(BUY), { ok: true });
}

test('regression: lost confirm + reload with open+not_submitted stays uncertain from the first state', async () => {
  const t = tab();
  await reviewed(t);
  t.server.on(CONFIRM, lost());
  t.server.on('GET /proposals/p1', ok(proposalFx()));
  await t.ctl.confirm(); await flush();
  assert.equal(t.s().phase, 'uncertain');
  assert.equal(record(t.storage).pendingConfirm, true);

  const r = reload(t);
  // Before any read: already uncertain, never confirmable.
  assert.equal(r.s().phase, 'uncertain'); assert.equal(r.s().canConfirm, false); assert.equal(r.s().canPrepare, false);
  assert.deepEqual(await r.ctl.confirm(), { ok: false, reason: 'not_allowed' });
  r.server.on('GET /proposals/p1', ok(proposalFx()), ok(proposalFx()),
    ok(proposalFx({ status: 'confirmed', submissionStatus: 'submitting' })));
  await r.clock.advance(0);
  assert.equal(r.s().phase, 'uncertain'); assert.equal(r.s().proposal.submissionStatus, 'not_submitted');
  assert.equal(r.s().canConfirm, false, 'open + not_submitted is not proof');
  await r.clock.advance(r.s().nextReadInMs);
  assert.equal(r.s().phase, 'uncertain'); assert.equal(r.s().canConfirm, false);
  // The backend evolves: submitting → reconcile in progress → uncertain → submitted.
  await r.clock.advance(r.s().nextReadInMs);
  assert.equal(r.s().proposal.submissionStatus, 'submitting'); assert.equal(record(r.storage).pendingConfirm, false);
  r.server.on('POST /proposals/p1/reconcile', err(409, 'SUBMISSION_IN_PROGRESS'), err(409, 'SUBMISSION_UNCERTAIN'),
    ok(submittedFx()));
  for (let i = 0; i < 3; i++) await r.clock.advance(r.s().nextReadInMs);
  assert.equal(r.s().phase, 'tracking');
  assert.equal(r.server.count(CONFIRM), 1, 'POST /confirm stays at one');
});

test('the intent is stored before the transport receives the confirm request', async () => {
  const t = tab();
  await reviewed(t);
  let seen = null;
  const original = t.server.transport;
  t.server.on(CONFIRM, ok({ ...proposalFx(), status: 'confirmed', submissionStatus: 'submitted', brokerOrderId: 'o1',
    brokerStatus: 'accepted', filledQty: '0' }));
  // Inspect storage at the moment the confirm request reaches the transport.
  const peek = () => { seen = record(t.storage); };
  t.server.calls.push = new Proxy(t.server.calls.push, { apply(target, self, args) {
    if (args[0] === CONFIRM) peek();
    return Reflect.apply(target, self, args);
  } });
  await t.ctl.confirm();
  assert.equal(original, t.server.transport);
  assert.deepEqual(seen, { v: 1, proposalId: 'p1', pendingConfirm: true, pendingCancel: false });
  assert.equal(record(t.storage).pendingConfirm, false, 'cleared after a conclusive answer');
});

test('reload right after the intent was stored, before any response', async () => {
  const t = tab();
  await reviewed(t);
  t.server.on(CONFIRM, deferred()); // never answered
  void t.ctl.confirm();
  assert.equal(record(t.storage).pendingConfirm, true);
  const r = reload(t);
  assert.equal(r.s().phase, 'uncertain'); assert.equal(r.s().canConfirm, false);
  r.server.on('GET /proposals/p1', ok(submittedFx()));
  await r.clock.advance(0);
  assert.equal(r.s().phase, 'tracking'); assert.equal(r.server.count(CONFIRM), 1);
});

test('failed_before_submit after reload re-enables review but never confirms by itself', async () => {
  const t = tab();
  await reviewed(t);
  t.server.on(CONFIRM, lost());
  t.server.on('GET /proposals/p1', ok(proposalFx()));
  await t.ctl.confirm(); await flush();
  const r = reload(t);
  r.server.on('GET /proposals/p1', ok(proposalFx({ submissionStatus: 'failed_before_submit' })));
  await r.clock.advance(0);
  assert.equal(r.s().phase, 'review'); assert.equal(r.s().canConfirm, true);
  assert.equal(record(r.storage).pendingConfirm, false);
  await r.clock.advance(60_000);
  assert.equal(r.server.count(CONFIRM), 1);
});

test('a confirmed operation keeps being followed after reload (single polling loop)', async () => {
  const t = tab();
  await reviewed(t);
  t.server.on(CONFIRM, ok(submittedFx()));
  await t.ctl.confirm();
  assert.deepEqual(record(t.storage), { v: 1, proposalId: 'p1', pendingConfirm: false, pendingCancel: false });
  const r = reload(t);
  assert.equal(r.s().phase, 'recovering'); assert.equal(r.s().canConfirm, false); assert.equal(r.s().canCancel, false);
  r.server.on('GET /proposals/p1', ok(submittedFx()), ok(submittedFx()), ok(submittedFx()));
  r.server.on('GET /orders/o1', ok(orderFx()), ok(orderFx()));
  await r.clock.advance(0);
  assert.equal(r.s().phase, 'tracking');
  await r.clock.advance(3000); await r.clock.advance(3000);
  assert.equal(r.server.count('GET /orders/o1'), 2);
  assert.equal(t.clock.size, 1, 'only the new controller has a timer');
});

test('backend expiry is conclusive; the local clock never releases an uncertain confirm', async () => {
  const t = tab();
  await reviewed(t);
  t.server.on(CONFIRM, lost());
  t.server.on('GET /proposals/p1', ...Array(40).fill(ok(proposalFx())));
  await t.ctl.confirm(); await flush();
  await t.clock.advance(400_000); // far past expiresAt locally, backend still says open
  assert.equal(t.s().phase, 'uncertain'); assert.equal(t.s().canConfirm, false);
  assert.ok(t.server.count('GET /proposals/p1') > 5, 'kept reading with backoff');
  t.server.clear('GET /proposals/p1');
  t.server.on('GET /proposals/p1', ok(proposalFx({ status: 'expired' })));
  await t.ctl.checkStatus();
  assert.equal(t.s().phase, 'expired'); assert.equal(record(t.storage).pendingConfirm, false);
  assert.equal(t.server.count(CONFIRM), 1);
});

test('storage write failure: zero confirm or cancel requests and a clear error', async () => {
  const storage = memoryStorage();
  const t = tab(storage);
  await reviewed(t);
  storage.failWrites = true;
  assert.deepEqual(await t.ctl.confirm(), { ok: false, reason: 'error' });
  assert.equal(t.s().actionError.code, 'JOURNAL_UNAVAILABLE'); assert.equal(t.s().journal, 'unavailable');
  assert.equal(t.s().canConfirm, false);
  assert.equal(t.server.count(CONFIRM), 0);

  const c = tab();
  await reviewed(c);
  c.server.on(CONFIRM, ok(submittedFx()));
  await c.ctl.confirm();
  c.storage.failWrites = true;
  assert.equal((await c.ctl.cancel()).ok, false);
  assert.equal(c.server.count('POST /orders/o1/cancel'), 0);
});

test('storage unavailable at load: confirm is blocked from the start', async () => {
  const storage = memoryStorage();
  storage.failReads = true;
  const t = tab(storage);
  assert.equal(t.s().journal, 'unavailable');
  storage.failReads = false; storage.failWrites = true;
  await reviewed(t);
  assert.equal(t.s().canConfirm, false);
  assert.deepEqual(await t.ctl.confirm(), { ok: false, reason: 'not_allowed' });
  assert.equal(t.server.count(CONFIRM), 0);
});

test('journal parsing: corrupt, incomplete, unknown version and legacy records', () => {
  assert.deepEqual(parseJournal(null, null), { kind: 'empty' });
  assert.deepEqual(parseJournal('{not json', null), { kind: 'invalid' });
  assert.deepEqual(parseJournal('[1,2]', null), { kind: 'invalid' });
  assert.deepEqual(parseJournal('{"v":1,"pendingConfirm":false}', null), { kind: 'invalid' });
  assert.deepEqual(parseJournal('{"v":1,"proposalId":"../x","pendingConfirm":false,"pendingCancel":false}', null), { kind: 'invalid' });
  const conservative = { v: 1, proposalId: 'p1', pendingConfirm: true, pendingCancel: true };
  assert.deepEqual(parseJournal('{"v":1,"proposalId":"p1"}', null), { kind: 'record', note: 'incomplete', record: conservative });
  assert.deepEqual(parseJournal('{"v":1,"proposalId":"p1","pendingConfirm":"no","pendingCancel":false}', null),
    { kind: 'record', note: 'incomplete', record: conservative });
  assert.deepEqual(parseJournal('{"v":2,"proposalId":"p1","pendingConfirm":false,"pendingCancel":false}', null),
    { kind: 'record', note: 'unknown_version', record: conservative });
  assert.deepEqual(parseJournal(null, 'p1'), { kind: 'record', note: 'legacy',
    record: { v: 1, proposalId: 'p1', pendingConfirm: true, pendingCancel: false } });
  assert.deepEqual(parseJournal(null, '<script>'), { kind: 'invalid' });
});

test('corrupt record: nothing is recovered and nothing becomes confirmable without a new proposal', async () => {
  const storage = memoryStorage();
  storage.raw.set(JOURNAL_KEY, '{"v":1,"proposalId":');
  const t = tab(storage);
  assert.equal(t.s().journal, 'invalid'); assert.equal(t.s().phase, 'idle'); assert.equal(t.s().canConfirm, false);
  await t.clock.advance(10_000);
  assert.deepEqual(t.server.calls, []);
  await reviewed(t); // a new, explicitly prepared operation replaces the unreadable record
  assert.equal(t.s().journal, 'ok'); assert.equal(record(storage).proposalId, 'p1');
});

test('incomplete, unknown-version and legacy records recover as uncertain', async () => {
  for (const [key, value] of [[JOURNAL_KEY, '{"v":1,"proposalId":"p1"}'],
    [JOURNAL_KEY, '{"v":9,"proposalId":"p1","pendingConfirm":false,"pendingCancel":false}'], [LEGACY_KEY, 'p1']]) {
    const storage = memoryStorage();
    storage.raw.set(key, value);
    const t = tab(storage);
    assert.equal(t.s().phase, 'uncertain', value); assert.equal(t.s().canConfirm, false);
    t.server.on('GET /proposals/p1', ok(proposalFx()));
    await t.clock.advance(0);
    assert.equal(t.s().phase, 'uncertain', value); assert.equal(t.s().canConfirm, false);
    assert.equal(t.server.count(CONFIRM), 0);
  }
});

test('lost cancel + reload: cancel stays blocked until the order is read', async () => {
  const t = tab();
  await reviewed(t);
  t.server.on(CONFIRM, ok(submittedFx()));
  await t.ctl.confirm();
  t.server.on('POST /orders/o1/cancel', lost());
  t.server.on('GET /orders/o1', deferred());
  await t.ctl.cancel();
  assert.equal(record(t.storage).pendingCancel, true);
  const r = reload(t);
  r.server.on('GET /proposals/p1', ok(submittedFx()), ok(submittedFx()));
  await r.clock.advance(0);
  assert.equal(r.s().phase, 'tracking'); assert.equal(r.s().canCancel, false); assert.equal(r.s().cancelUncertain, true);
  r.server.on('GET /orders/o1', ok(orderFx()));
  await r.clock.advance(r.s().nextReadInMs);
  assert.equal(r.s().canCancel, true); assert.equal(record(r.storage).pendingCancel, false);
  assert.equal(r.server.count('POST /orders/o1/cancel'), 1);
});

test('unknown proposal at recovery (404) ends recovery; other errors keep it uncertain', async () => {
  const storage = memoryStorage();
  storage.raw.set(JOURNAL_KEY, '{"v":1,"proposalId":"p1","pendingConfirm":true,"pendingCancel":false}');
  const t = tab(storage);
  t.server.on('GET /proposals/p1', err(503, 'BROKER_UNAVAILABLE'), err(404, 'PROPOSAL_NOT_FOUND'));
  await t.clock.advance(0);
  assert.equal(t.s().phase, 'uncertain');
  await t.clock.advance(t.s().nextReadInMs);
  assert.equal(t.s().phase, 'idle'); assert.equal(t.s().lastError.code, 'PROPOSAL_NOT_FOUND');
  assert.equal(storage.raw.has(JOURNAL_KEY), false);
});

test('resume() cannot drop a pending intent; prepare is blocked while recovering', async () => {
  const storage = memoryStorage();
  storage.raw.set(JOURNAL_KEY, '{"v":1,"proposalId":"p1","pendingConfirm":true,"pendingCancel":false}');
  const t = tab(storage);
  assert.deepEqual(await t.ctl.resume('p2'), { ok: false, reason: 'not_allowed' });
  assert.deepEqual(await t.ctl.prepare(BUY), { ok: false, reason: 'not_allowed' });
  assert.equal(record(storage).proposalId, 'p1'); assert.equal(record(storage).pendingConfirm, true);
});

test('identity, unknown status and double-click guarantees hold with a journal', async () => {
  const t = tab();
  t.server.on('POST /proposals', ok(proposalFx({ symbol: 'TSLA' })));
  await t.ctl.prepare(BUY);
  assert.equal(t.s().lastError.code, 'INVALID_RESPONSE'); assert.equal(t.storage.raw.has(JOURNAL_KEY), false);
  await reviewed(t);
  const d = deferred();
  t.server.on(CONFIRM, d);
  const first = t.ctl.confirm();
  assert.deepEqual(await t.ctl.confirm(), { ok: false, reason: 'busy' });
  d.resolve(ok(submittedFx({ brokerStatus: 'held_somewhere' })));
  await first;
  assert.equal(t.s().proposal.brokerStatus, 'unrecognized'); assert.equal(t.s().canCancel, false);
  assert.equal(t.server.count(CONFIRM), 1);
});

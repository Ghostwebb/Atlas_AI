/* Controller tests: HTTP fixtures + manual clock/scheduler. No network, Alpaca, LM Studio or credentials.
   Compile the folder to PAPER_TEST_BUILD first (see README.md). */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { flush, proposalFx, reservationFx, submittedFx, orderFx, ok, err, lost, deferred, setup, BUY, toReview, toTracking } from './test-fixtures.mjs';

// --- tests -----------------------------------------------------------------------------

test('prepare never confirms, keeps decimal strings and rejects non-request input', async () => {
  const t = setup();
  await toReview(t);
  assert.deepEqual(t.server.calls, ['POST /proposals']);
  const st = t.s();
  assert.equal(st.phase, 'review'); assert.equal(st.canConfirm, true); assert.equal(st.proposal.notional, '100.00');
  for (const bad of [{ ...BUY, recommendation: 'BUY' }, { ...BUY, notional: 100 }, { symbol: 'NVDA', side: 'hold' }]) {
    const before = t.server.calls.length;
    assert.equal((await t.ctl.prepare(bad)).ok, false);
    assert.equal(t.server.calls.length, before);
    assert.equal(t.s().lastError.code, 'INVALID_INPUT');
  }
  assert.equal(t.server.count('POST /proposals/p1/confirm'), 0);
});

test('two confirmations before any render send exactly one request', async () => {
  const t = setup();
  await toReview(t);
  const d = deferred();
  t.server.on('POST /proposals/p1/confirm', d);
  const first = t.ctl.confirm();
  const second = await t.ctl.confirm();
  assert.deepEqual(second, { ok: false, reason: 'busy' });
  assert.equal(t.s().canConfirm, false); assert.equal(t.s().phase, 'confirming');
  d.resolve(ok(submittedFx()));
  assert.deepEqual(await first, { ok: true });
  assert.equal(t.server.count('POST /proposals/p1/confirm'), 1);
  assert.equal(t.s().phase, 'tracking');
});

test('expired proposal: local expiry blocks confirm; backend PROPOSAL_EXPIRED is verified by a read', async () => {
  const t = setup();
  await toReview(t);
  await t.clock.advance(300_000);
  assert.equal(t.s().phase, 'expired'); assert.equal(t.s().canConfirm, false);
  assert.deepEqual(await t.ctl.confirm(), { ok: false, reason: 'not_allowed' });
  assert.equal(t.server.count('POST /proposals/p1/confirm'), 0);

  const u = setup();
  await toReview(u);
  u.server.on('POST /proposals/p1/confirm', err(409, 'PROPOSAL_EXPIRED'));
  u.server.on('GET /proposals/p1', ok(proposalFx({ status: 'expired' })));
  await u.ctl.confirm(); await flush();
  assert.equal(u.s().phase, 'expired'); assert.equal(u.s().canConfirm, false);
  assert.equal(u.s().lastError, null);
  assert.equal(u.server.count('POST /proposals/p1/confirm'), 1);
});

test('lost confirmation after the server accepted it: reads, never resends', async () => {
  for (const failure of [lost(), 'not json', ok(proposalFx({ status: 'open', submissionStatus: 'submitted' }))]) {
    const t = setup();
    await toReview(t);
    t.server.on('POST /proposals/p1/confirm', failure);
    t.server.on('GET /proposals/p1', ok(submittedFx()));
    const result = t.ctl.confirm();
    await result;
    // Right after the failure: uncertain, proposal kept, confirm disabled.
    assert.equal((await result).ok, false);
    await flush();
    assert.equal(t.s().proposal.id, 'p1');
    assert.equal(t.s().phase, 'tracking');
    assert.equal(t.server.count('POST /proposals/p1/confirm'), 1);
    assert.deepEqual(t.server.unexpected, []);
  }
});

test('lost confirmation: open+not_submitted stays uncertain; only failed_before_submit re-enables, never automatically', async () => {
  const t = setup();
  await toReview(t);
  t.server.on('POST /proposals/p1/confirm', lost());
  t.server.on('GET /proposals/p1', ok(proposalFx()), ok(proposalFx()), ok(proposalFx({ submissionStatus: 'failed_before_submit' })));
  await t.ctl.confirm(); await flush();
  assert.equal(t.s().phase, 'uncertain'); assert.equal(t.s().canConfirm, false); assert.equal(t.s().canCheckStatus, true);
  assert.equal(t.s().nextReadInMs, 6000); // repeated uncertainty backs off
  await t.clock.advance(6000);
  assert.equal(t.s().phase, 'uncertain'); assert.equal(t.s().nextReadInMs, 12000);
  await t.clock.advance(12000);
  assert.equal(t.s().phase, 'review'); assert.equal(t.s().canConfirm, true);
  await t.clock.advance(60_000);
  assert.equal(t.server.count('POST /proposals/p1/confirm'), 1); // a new human action is required
});

test('submitting with a live lease: SUBMISSION_IN_PROGRESS, then reconcile finds the order', async () => {
  const t = setup();
  await toReview(t);
  t.server.on('POST /proposals/p1/confirm', err(409, 'SUBMISSION_IN_PROGRESS'));
  t.server.on('GET /proposals/p1', ok(proposalFx({ status: 'confirmed', submissionStatus: 'submitting' })));
  t.server.on('POST /proposals/p1/reconcile', err(409, 'SUBMISSION_IN_PROGRESS'), err(409, 'SUBMISSION_IN_PROGRESS'),
    ok(submittedFx()));
  await t.ctl.confirm(); await flush();
  assert.equal(t.s().phase, 'uncertain'); assert.equal(t.s().canConfirm, false); assert.equal(t.s().nextReadInMs, 3000);
  await t.clock.advance(3000);
  assert.equal(t.s().lastError.code, 'SUBMISSION_IN_PROGRESS'); assert.equal(t.s().nextReadInMs, 6000);
  await t.clock.advance(6000);
  assert.equal(t.s().nextReadInMs, 12000);
  await t.clock.advance(12000);
  assert.equal(t.s().phase, 'tracking'); assert.equal(t.s().nextReadInMs, 3000);
  assert.equal(t.server.count('POST /proposals/p1/confirm'), 1);
});

test('uncertain order that appears later is found by reconcile without resending', async () => {
  const t = setup();
  await toReview(t);
  t.server.on('POST /proposals/p1/confirm', err(409, 'SUBMISSION_UNCERTAIN'));
  t.server.on('GET /proposals/p1', ok(proposalFx({ status: 'confirmed', submissionStatus: 'submission_unknown' })));
  t.server.on('POST /proposals/p1/reconcile', err(409, 'SUBMISSION_UNCERTAIN'), ok(submittedFx()));
  await t.ctl.confirm(); await flush();
  assert.equal(t.s().phase, 'uncertain');
  assert.equal(t.s().lastError, null); // the read succeeded; the confirm error was replaced
  await t.clock.advance(3000);
  assert.equal(t.s().lastError.code, 'SUBMISSION_UNCERTAIN'); assert.equal(t.s().lastError.correlationId, 'c-SUBMISSION_UNCERTAIN');
  assert.equal(t.s().lastError.proposalId, 'p1');
  await t.clock.advance(6000);
  assert.equal(t.s().phase, 'tracking'); assert.equal(t.s().proposal.brokerOrderId, 'o1');
  assert.equal(t.server.count('POST /proposals/p1/confirm'), 1);
});

test('partial then final fill: tracking continues, then stops with no timers left', async () => {
  const t = setup();
  await toTracking(t);
  t.server.on('GET /orders/o1', ok(orderFx({ status: 'partially_filled', filledQty: '0.5', filledAvgPrice: '100' })),
    ok(orderFx({ status: 'filled', filledQty: '1', filledAvgPrice: '100.25' })));
  t.server.on('GET /proposals/p1', ok(submittedFx({ brokerStatus: 'partially_filled', filledQty: '0.5',
    reservation: reservationFx({ consumed: '50.0', filledQty: '0.5', filledNotional: '50.0' }) })),
  ok(submittedFx({ brokerStatus: 'filled', filledQty: '1', reservation: reservationFx({ state: 'released',
    releaseReason: 'order_terminal', consumed: '100.25', filledQty: '1', filledNotional: '100.25' }) })));
  await t.clock.advance(3000);
  assert.equal(t.s().phase, 'tracking'); assert.equal(t.s().order.filledQty, '0.5');
  assert.equal(t.s().proposal.reservation.state, 'acknowledged');
  await t.clock.advance(3000);
  assert.equal(t.s().phase, 'final'); assert.equal(t.s().proposal.reservation.state, 'released');
  assert.equal(t.s().order.filledAvgPrice, '100.25'); assert.equal(t.s().nextReadInMs, null);
  assert.equal(t.clock.size, 0);
  await t.clock.advance(60_000);
  assert.equal(t.server.count('GET /orders/o1'), 2);
});

test('pending_cancel is not final; a cancel that loses the race reports the fill', async () => {
  const t = setup();
  await toTracking(t);
  t.server.on('POST /orders/o1/cancel', ok({ cancelRequested: true, order: orderFx({ status: 'pending_cancel' }) }));
  t.server.on('GET /orders/o1', ok(orderFx({ status: 'pending_cancel' })), ok(orderFx({ status: 'canceled' })));
  t.server.on('GET /proposals/p1', ok(submittedFx({ brokerStatus: 'pending_cancel' })),
    ok(submittedFx({ brokerStatus: 'canceled', reservation: reservationFx({ state: 'released', releaseReason: 'order_terminal' }) })));
  assert.deepEqual(await t.ctl.cancel(), { ok: true }); await flush();
  assert.equal(t.s().phase, 'tracking'); assert.equal(t.s().proposal.brokerStatus, 'pending_cancel');
  assert.equal(t.s().canCancel, false); assert.equal(t.s().nextReadInMs, 3000);
  await t.clock.advance(3000);
  assert.equal(t.s().phase, 'final');

  const r = setup();
  await toTracking(r);
  r.server.on('POST /orders/o1/cancel', ok({ cancelRequested: true, order: orderFx({ status: 'filled', filledQty: '1' }) }));
  r.server.on('GET /orders/o1', ok(orderFx({ status: 'filled', filledQty: '1' })));
  r.server.on('GET /proposals/p1', ok(submittedFx({ brokerStatus: 'filled', filledQty: '1' })));
  await r.ctl.cancel(); await flush();
  assert.equal(r.s().phase, 'final'); assert.equal(r.s().order.status, 'filled');
});

test('lost cancel response: no second cancel until the order is read', async () => {
  const t = setup();
  await toTracking(t);
  const d = deferred();
  t.server.on('POST /orders/o1/cancel', lost());
  t.server.on('GET /orders/o1', d);
  t.server.on('GET /proposals/p1', ok(submittedFx()));
  assert.equal((await t.ctl.cancel()).ok, false);
  assert.equal(t.s().cancelUncertain, true); assert.equal(t.s().canCancel, false);
  assert.deepEqual(await t.ctl.cancel(), { ok: false, reason: 'not_allowed' });
  d.resolve(ok(orderFx())); await flush();
  assert.equal(t.s().cancelUncertain, false); assert.equal(t.s().canCancel, true);
  assert.equal(t.server.count('POST /orders/o1/cancel'), 1);
});

test('backoff is bounded at 30 s and resets after a successful read', async () => {
  const t = setup();
  await toTracking(t);
  t.server.on('GET /orders/o1', ...Array(5).fill(err(503, 'BROKER_UNAVAILABLE')), ok(orderFx()));
  t.server.on('GET /proposals/p1', ok(submittedFx()));
  const delays = [];
  for (let i = 0; i < 6; i++) { delays.push(t.s().nextReadInMs); await t.clock.advance(t.s().nextReadInMs); }
  assert.deepEqual(delays, [3000, 6000, 12000, 24000, 30000, 30000]);
  assert.equal(t.s().lastError, null); assert.equal(t.s().nextReadInMs, 3000);
});

test('slow polling never overlaps and manual checks join the in-flight read', async () => {
  const t = setup();
  await toTracking(t);
  const d = deferred();
  t.server.on('GET /orders/o1', d, ok(orderFx()));
  t.server.on('GET /proposals/p1', ok(submittedFx()), ok(submittedFx()));
  await t.clock.advance(3000);
  assert.equal(t.s().reading, true);
  await t.clock.advance(120_000);
  const manualA = t.ctl.checkStatus(); const manualB = t.ctl.checkStatus();
  assert.equal(manualA, manualB);
  assert.equal(t.server.count('GET /orders/o1'), 1);
  d.resolve(ok(orderFx())); await manualA; await flush();
  assert.equal(t.s().reading, false); assert.equal(t.s().nextReadInMs, 3000);
  // A manual check while a timer is pending runs now and replaces that timer (still one read).
  await t.ctl.checkStatus(); await flush();
  assert.equal(t.server.count('GET /orders/o1'), 2); assert.equal(t.clock.size, 1);
});

test('dispose during a request: no late updates and no timers', async () => {
  const t = setup();
  await toTracking(t);
  const d = deferred();
  t.server.on('GET /orders/o1', d);
  await t.clock.advance(3000);
  let notified = 0;
  t.ctl.subscribe(() => notified++);
  const before = t.s();
  t.ctl.dispose();
  d.resolve(ok(orderFx({ status: 'filled' }))); await flush();
  await t.clock.advance(120_000);
  assert.equal(notified, 0); assert.equal(t.s(), before); assert.equal(t.clock.size, 0);
  assert.equal(t.server.count('GET /orders/o1'), 1);
  assert.deepEqual(await t.ctl.confirm(), { ok: false, reason: 'disposed' });
});

test('switching proposal ignores late responses of the previous one', async () => {
  const t = setup({ ignoreAbort: true });
  await toTracking(t);
  const late = deferred();
  t.server.on('GET /orders/o1', late);
  await t.clock.advance(3000);
  t.server.on('GET /proposals/p2', ok(proposalFx({ id: 'p2', clientOrderId: 'atlas-p2' })));
  assert.deepEqual(await t.ctl.resume('p2'), { ok: true });
  late.resolve(ok(orderFx({ status: 'filled' }))); await flush();
  assert.equal(t.s().proposal.id, 'p2'); assert.equal(t.s().order, null); assert.equal(t.s().phase, 'review');
  assert.equal(t.server.count('GET /proposals/p1'), 0);
});

test('malformed or contradictory responses never enable confirm or cancel', async () => {
  const t = setup();
  t.server.on('POST /proposals', ok(proposalFx({ submissionStatus: 'submitted' })), ok({ ...proposalFx(), expiresAt: 'soon' }),
    ok(proposalFx({ environment: 'live' })));
  for (let i = 0; i < 3; i++) {
    await t.ctl.prepare(BUY);
    assert.equal(t.s().lastError.code, 'INVALID_RESPONSE');
    assert.equal(t.s().canConfirm, false); assert.equal(t.s().proposal, null);
  }
  const u = setup();
  await toReview(u);
  u.server.on('POST /proposals/p1/confirm', ok(submittedFx({ brokerOrderId: null })));
  u.server.on('GET /proposals/p1', ok({ broken: true }));
  await u.ctl.confirm(); await flush();
  assert.equal(u.s().phase, 'uncertain'); assert.equal(u.s().canConfirm, false); assert.equal(u.s().canCancel, false);
  assert.equal(u.s().lastError.code, 'INVALID_RESPONSE');
  const v = setup();
  await toTracking(v);
  v.server.on('GET /orders/o1', ok(orderFx({ proposalId: 'other' })));
  await v.clock.advance(3000);
  assert.equal(v.s().lastError.code, 'INVALID_RESPONSE'); assert.equal(v.s().order, null);
  assert.equal(v.s().nextReadInMs, 6000);
});

test('unknown broker statuses are kept as unrecognized and never treated as final', async () => {
  const t = setup();
  await toTracking(t);
  t.server.on('GET /orders/o1', ok(orderFx({ status: 'held_somewhere', brokerStatusRaw: 'held_somewhere' })),
    ok(orderFx({ status: 'done_for_day' })), ok(orderFx({ status: 'replaced' })));
  t.server.on('GET /proposals/p1', ok(submittedFx({ brokerStatus: 'unrecognized' })),
    ok(submittedFx({ brokerStatus: 'done_for_day' })), ok(submittedFx({ brokerStatus: 'replaced' })));
  for (const expected of ['unrecognized', 'done_for_day', 'replaced']) {
    await t.clock.advance(3000);
    assert.equal(t.s().order.status, expected);
    assert.equal(t.s().phase, 'tracking'); assert.equal(t.s().nextReadInMs, 3000);
  }
});

test('paper account data stays separate from synthetic analysis', async () => {
  const t = setup();
  await toTracking(t);
  assert.equal(t.s().source, 'fixture'); assert.equal(t.s().notice, 'Paper Trading — dinero ficticio');
  assert.ok(t.server.urls.every(u => u.startsWith('http://fixture/api/paper/')));
  const analysis = { symbol: 'NVDA', recommendation: 'BUY', confidence: 'medium', isSimulated: true };
  const fresh = setup();
  assert.equal((await fresh.ctl.prepare(analysis)).ok, false);
  assert.equal((await fresh.ctl.prepare({ ...BUY, committeeDecision: 'BUY' })).ok, false);
  assert.deepEqual(fresh.server.calls, []);
});

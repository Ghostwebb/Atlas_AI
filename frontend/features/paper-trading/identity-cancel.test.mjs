/* Regressions for the review of 637b40d:
   1. a prepared (or later read) proposal must match the requested operation;
   2. cancellation is offered only for explicitly cancelable broker statuses. Fixtures only. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { flush, proposalFx, submittedFx, orderFx, ok, setup, BUY, toReview, toTracking, load } from './test-fixtures.mjs';
const { canCancel } = await load('policy.js');

const SELL = { symbol: 'NVDA', side: 'sell', qty: '2' };
const sellFx = patch => proposalFx({ side: 'sell', notional: null, qty: '2', ...patch });

async function rejectedPrepare(request, response) {
  const t = setup();
  t.server.on('POST /proposals', ok(response));
  const result = await t.ctl.prepare(request);
  assert.deepEqual(result, { ok: false, reason: 'error' });
  const st = t.s();
  assert.equal(st.lastError.code, 'INVALID_RESPONSE');
  assert.equal(st.proposal, null); assert.equal(st.canConfirm, false); assert.equal(st.phase, 'idle');
  assert.deepEqual(await t.ctl.confirm(), { ok: false, reason: 'not_allowed' });
  assert.deepEqual(await t.ctl.cancel(), { ok: false, reason: 'not_allowed' });
  assert.deepEqual(t.server.calls, ['POST /proposals']); // no confirm, no cancel, no follow-up mutation
}

test('identity: the reviewed reproduction (buy NVDA $100 answered with sell 2 TSLA) is rejected', async () => {
  await rejectedPrepare(BUY, sellFx({ symbol: 'TSLA' }));
});

test('identity: different symbol, side or amount is rejected', async () => {
  await rejectedPrepare(BUY, proposalFx({ symbol: 'TSLA' }));
  await rejectedPrepare(BUY, sellFx({ notional: null }));
  await rejectedPrepare(BUY, proposalFx({ notional: '100.01' }));
  await rejectedPrepare(BUY, proposalFx({ notional: '1000.00' }));
  await rejectedPrepare(SELL, sellFx({ qty: '2.000000001' }));
  await rejectedPrepare(SELL, proposalFx({ side: 'buy', notional: '2', qty: null }));
});

test('identity: an amount field incompatible with the side is rejected', async () => {
  await rejectedPrepare(BUY, proposalFx({ qty: '1' }));
  await rejectedPrepare(SELL, sellFx({ notional: '100.00' }));
});

test('identity: analysisReference must match, including its absence', async () => {
  await rejectedPrepare(BUY, proposalFx({ analysisReference: 'NVDA@2026-09-30' }));
  await rejectedPrepare({ ...BUY, analysisReference: 'NVDA@2026-09-30' }, proposalFx({ analysisReference: null }));
  await rejectedPrepare({ ...BUY, analysisReference: 'NVDA@2026-09-30' }, proposalFx({ analysisReference: 'NVDA@2026-10-01' }));
  const t = setup();
  t.server.on('POST /proposals', ok(proposalFx({ analysisReference: 'NVDA@2026-09-30' })));
  assert.deepEqual(await t.ctl.prepare({ ...BUY, analysisReference: 'NVDA@2026-09-30' }), { ok: true });
});

test('identity: the backend symbol normalization (trim + uppercase) is accepted', async () => {
  const t = setup();
  t.server.on('POST /proposals', ok(proposalFx({ symbol: 'BRK.B' })));
  assert.deepEqual(await t.ctl.prepare({ ...BUY, symbol: ' brk.b ' }), { ok: true });
  assert.equal(t.s().proposal.symbol, 'BRK.B'); assert.equal(t.s().canConfirm, true);
});

test('identity: equivalent decimal strings are accepted without floating point', async () => {
  for (const [request, response] of [
    [BUY, proposalFx({ notional: '100' })],
    [{ ...BUY, notional: '100' }, proposalFx({ notional: '100.00' })],
    [{ ...BUY, notional: '0100.50' }, proposalFx({ notional: '100.5' })],
    [{ ...SELL, qty: '0.50' }, sellFx({ qty: '0.5' })],
    [{ ...SELL, qty: '0.000000001' }, sellFx({ qty: '0.000000001' })],
  ]) {
    const t = setup();
    t.server.on('POST /proposals', ok(response));
    assert.deepEqual(await t.ctl.prepare(request), { ok: true }, JSON.stringify(request));
    assert.equal(t.s().canConfirm, true);
  }
  // Values that Number() would round to the same double are still different.
  await rejectedPrepare({ ...SELL, qty: '0.100000001' }, sellFx({ qty: '0.1' }));
  assert.equal(Number('12345678901.000000000001'), Number('12345678901')); // same double, different decimals
  await rejectedPrepare({ ...SELL, qty: '12345678901.000000000001' }, sellFx({ qty: '12345678901' }));
});

test('identity: a later read with the same id but a changed operation is not adopted', async () => {
  for (const changed of [{ symbol: 'TSLA' }, { side: 'sell', notional: null, qty: '1' }, { notional: '500.00' },
    { analysisReference: 'other' }, { clientOrderId: 'atlas-other' }]) {
    const t = setup();
    await toTracking(t);
    t.server.on('GET /orders/o1', ok(orderFx()), ok(orderFx()));
    t.server.on('GET /proposals/p1', ok(submittedFx(changed)), ok(submittedFx()));
    await t.clock.advance(3000);
    const st = t.s();
    assert.equal(st.lastError.code, 'INVALID_RESPONSE', JSON.stringify(changed));
    assert.equal(st.proposal.symbol, 'NVDA'); assert.equal(st.proposal.notional, '100.00');
    assert.equal(st.proposal.side, 'buy'); assert.equal(st.proposal.clientOrderId, 'atlas-p1');
    assert.equal(st.canCancel, false); assert.equal(st.canCheckStatus, true);
    assert.deepEqual(await t.ctl.cancel(), { ok: false, reason: 'not_allowed' });
    assert.equal(t.server.count('POST /orders/o1/cancel'), 0);
    // A consistent read restores the actions.
    await t.clock.advance(st.nextReadInMs);
    assert.equal(t.s().lastError, null); assert.equal(t.s().canCancel, true);
  }
});

test('identity: an order that belongs to another operation is not adopted', async () => {
  for (const changed of [{ symbol: 'TSLA' }, { side: 'sell' }, { clientOrderId: 'atlas-other' }]) {
    const t = setup();
    await toTracking(t);
    t.server.on('GET /orders/o1', ok(orderFx(changed)));
    await t.clock.advance(3000);
    assert.equal(t.s().lastError.code, 'INVALID_RESPONSE', JSON.stringify(changed));
    assert.equal(t.s().order, null); assert.equal(t.s().canCancel, false);
  }
});

test('identity: a confirm response for a changed operation is uncertain and never confirmed again', async () => {
  const t = setup();
  await toReview(t);
  t.server.on('POST /proposals/p1/confirm', ok(submittedFx({ symbol: 'TSLA' })));
  t.server.on('GET /proposals/p1', ok(submittedFx()));
  await t.ctl.confirm();
  assert.equal(t.s().confirmUncertain, true); assert.equal(t.s().canConfirm, false);
  await flush();
  assert.equal(t.s().phase, 'tracking'); assert.equal(t.s().proposal.symbol, 'NVDA');
  assert.equal(t.server.count('POST /proposals/p1/confirm'), 1);
});

// --- cancellation policy --------------------------------------------------------------

const submitted = brokerStatus => ({ status: 'confirmed', submissionStatus: 'submitted', brokerOrderId: 'o1', brokerStatus });

test('cancel policy: only explicitly cancelable statuses show the button', () => {
  for (const s of ['new', 'accepted', 'pending_new', 'accepted_for_bidding', 'partially_filled']) {
    assert.equal(canCancel(submitted(s)), true, s);
  }
  for (const s of ['unrecognized', null, undefined, 'pending_cancel', 'filled', 'canceled', 'expired', 'rejected',
    'done_for_day', 'replaced', 'pending_replace', 'stopped', 'suspended', 'calculated', 'some_future_status']) {
    assert.equal(canCancel(submitted(s)), false, String(s));
  }
  assert.equal(canCancel({ ...submitted('new'), brokerOrderId: null }), false);
  assert.equal(canCancel({ ...submitted('new'), submissionStatus: 'submission_unknown' }), false);
});

test('cancel: an unknown status blocks cancel but keeps status checks and polling', async () => {
  const t = setup();
  await toTracking(t);
  t.server.on('GET /orders/o1', ok(orderFx({ status: 'held_somewhere', brokerStatusRaw: 'held_somewhere' })),
    ok(orderFx({ status: 'partially_filled', filledQty: '0.5', filledAvgPrice: '100' })));
  t.server.on('GET /proposals/p1', ok(submittedFx({ brokerStatus: 'held_somewhere' })),
    ok(submittedFx({ brokerStatus: 'partially_filled', filledQty: '0.5' })));
  await t.clock.advance(3000);
  let st = t.s();
  assert.equal(st.order.status, 'unrecognized'); assert.equal(st.proposal.brokerStatus, 'unrecognized');
  assert.equal(st.phase, 'tracking'); assert.equal(st.canCancel, false);
  assert.equal(st.canCheckStatus, true); assert.equal(st.nextReadInMs, 3000);
  assert.deepEqual(await t.ctl.cancel(), { ok: false, reason: 'not_allowed' });
  // Unknown → recognized cancelable: actions update.
  await t.clock.advance(3000);
  st = t.s();
  assert.equal(st.proposal.brokerStatus, 'partially_filled'); assert.equal(st.canCancel, true);
  assert.equal(t.server.count('POST /orders/o1/cancel'), 0);
});

test('cancel: a missing broker status blocks cancel and keeps following the order', async () => {
  const t = setup();
  await toReview(t);
  t.server.on('POST /proposals/p1/confirm', ok(submittedFx({ brokerStatus: null })));
  t.server.on('GET /orders/o1', ok(orderFx({ status: 'new' })));
  t.server.on('GET /proposals/p1', ok(submittedFx({ brokerStatus: 'new' })));
  await t.ctl.confirm();
  assert.equal(t.s().phase, 'tracking'); assert.equal(t.s().canCancel, false);
  assert.equal(t.s().canCheckStatus, true); assert.equal(t.s().nextReadInMs, 3000);
  await t.clock.advance(3000);
  assert.equal(t.s().canCancel, true);
});

test('cancel: pending_cancel and the four final statuses block the button', async () => {
  for (const status of ['pending_cancel', 'filled', 'canceled', 'expired', 'rejected']) {
    const t = setup();
    await toTracking(t);
    t.server.on('GET /orders/o1', ok(orderFx({ status })));
    t.server.on('GET /proposals/p1', ok(submittedFx({ brokerStatus: status })));
    await t.clock.advance(3000);
    assert.equal(t.s().canCancel, false, status);
    assert.equal(t.s().phase, status === 'pending_cancel' ? 'tracking' : 'final', status);
  }
});

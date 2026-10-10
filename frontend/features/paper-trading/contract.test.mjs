/* Compile this folder to a temporary directory, then set PAPER_TEST_BUILD to it. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const { createPaperClient, PaperApiError } = await import(pathToFileURL(path.join(process.env.PAPER_TEST_BUILD, 'client.js')).href);
const { canConfirm, canCancel, nextStatusRead, isFinalOrder } = await import(pathToFileURL(path.join(process.env.PAPER_TEST_BUILD, 'policy.js')).href);
const proposal = (patch = {}) => ({ id: 'p1', status: 'confirmed', submissionStatus: 'submitted', brokerOrderId: 'o1', brokerStatus: 'accepted', expiresAt: '2099-01-01T00:00:00Z', ...patch });

test('prepare preserves decimal strings and never sends a confirm', async () => {
  const calls = [];
  const client = createPaperClient('http://fixture/', async (url, init) => {
    calls.push({ url, init }); return Response.json(proposal());
  });
  await client.prepare({ symbol: 'NVDA', side: 'buy', notional: '100.00' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://fixture/api/paper/proposals');
  assert.deepEqual(JSON.parse(calls[0].init.body), { symbol: 'NVDA', side: 'buy', notional: '100.00' });
  assert.equal(calls[0].init.credentials, 'omit');
});

test('explicit mutations use exact confirmation tokens', async () => {
  const calls = [];
  const client = createPaperClient('http://fixture', async (url, init) => {
    calls.push({ url, init }); return Response.json(proposal());
  });
  await client.confirm('p/1'); await client.cancel('o1'); await client.reconcile('p1');
  assert.equal(calls[0].url, 'http://fixture/api/paper/proposals/p%2F1/confirm');
  assert.deepEqual(JSON.parse(calls[0].init.body), { confirmation: 'CONFIRM_PAPER_ORDER' });
  assert.deepEqual(JSON.parse(calls[1].init.body), { confirmation: 'CANCEL_PAPER_ORDER' });
  assert.equal(calls[2].init.body, undefined);
  assert.equal(calls[2].init.method, 'POST');
});

test('business errors preserve code, proposal and correlation ids', async () => {
  const client = createPaperClient('http://fixture', async () => Response.json({
    code: 'RESOURCE_RESERVED', message: 'Reserved', proposalId: 'p1', correlationId: 'c1',
  }, { status: 409 }));
  await assert.rejects(client.confirm('p1'), error => error instanceof PaperApiError &&
    error.code === 'RESOURCE_RESERVED' && error.status === 409 && error.proposalId === 'p1' && error.correlationId === 'c1');
});

test('lost confirmation response never retries', async () => {
  let calls = 0;
  const client = createPaperClient('http://fixture', async () => { calls++; throw new TypeError('offline'); });
  await assert.rejects(client.confirm('p1'), error => error.code === 'NETWORK_ERROR');
  assert.equal(calls, 1);
});

test('invalid response never retries a mutation', async () => {
  let calls = 0;
  const client = createPaperClient('http://fixture', async () => { calls++; return new Response('bad JSON'); });
  await assert.rejects(client.confirm('p1'), error => error.code === 'INVALID_RESPONSE');
  assert.equal(calls, 1);
});

test('reads use local proposal vs broker order endpoints', async () => {
  const urls = [];
  const client = createPaperClient('http://fixture', async url => { urls.push(url); return Response.json({}); });
  await client.proposal('p1'); await client.order('o1');
  assert.deepEqual(urls, ['http://fixture/api/paper/proposals/p1', 'http://fixture/api/paper/orders/o1']);
});

test('unknown and submitting states use reconciliation, never confirmation', () => {
  for (const submissionStatus of ['submission_unknown', 'submitting']) {
    const p = proposal({ submissionStatus, brokerOrderId: null, brokerStatus: null });
    assert.equal(canConfirm(p), false); assert.equal(canCancel(p), false);
    assert.deepEqual(nextStatusRead(p), { kind: 'reconcile', id: 'p1' });
  }
});

test('pending cancel keeps tracking but hides cancel', () => {
  const p = proposal({ brokerStatus: 'pending_cancel' });
  assert.equal(canCancel(p), false);
  assert.deepEqual(nextStatusRead(p), { kind: 'order', id: 'o1' });
});

test('only the four backend final statuses stop order tracking', () => {
  for (const brokerStatus of ['filled', 'canceled', 'expired', 'rejected']) {
    assert.equal(isFinalOrder(brokerStatus), true);
    assert.equal(nextStatusRead(proposal({ brokerStatus })), null);
    assert.equal(canCancel(proposal({ brokerStatus })), false);
  }
  for (const brokerStatus of ['unrecognized', 'replaced', 'done_for_day']) {
    assert.deepEqual(nextStatusRead(proposal({ brokerStatus })), { kind: 'order', id: 'o1' });
  }
});

test('confirmation requires an open unexpired proposal and known unsent state', () => {
  assert.equal(canConfirm(proposal({ status: 'open', submissionStatus: 'not_submitted' })), true);
  assert.equal(canConfirm(proposal({ status: 'open', submissionStatus: 'failed_before_submit' })), true);
  assert.equal(canConfirm(proposal({ status: 'open', submissionStatus: 'not_submitted', expiresAt: 'invalid' })), false);
  assert.equal(canConfirm(proposal({ status: 'open', submissionStatus: 'not_submitted', expiresAt: '2020-01-01' })), false);
  assert.equal(canConfirm(proposal()), false);
});

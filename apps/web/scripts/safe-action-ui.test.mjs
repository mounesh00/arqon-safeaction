// UI-state tests with fake same-origin responses. Not a live integration test.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { test } from 'node:test';
import ts from 'typescript';
const require = createRequire(import.meta.url);
const module = { exports: {} };
const code = ts.transpileModule(readFileSync(new URL('../lib/safe-action-client.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
vm.runInNewContext(code, { exports: module.exports, module, Request, Response, AbortSignal });
const { SafeActionClient } = module.exports;
test('default fetch wrapper preserves browser receiver semantics', async () => {
  let calls = 0;
  const contextModule = { exports: {} };
  const context = vm.createContext({ exports: contextModule.exports, module: contextModule,
    Request, Response, AbortSignal,
    fetch: function () {
      assert.ok(this === undefined || this === context,
        'Native browser fetch must not receive a SafeActionClient receiver');
      calls++;
      return Promise.resolve(Response.json({ authenticated: true, csrf_token: 'a'.repeat(43),
        expires_at: new Date(Date.now() + 300000).toISOString() }));
    },
  });
  vm.runInContext(code, context);
  const client = new contextModule.exports.SafeActionClient();
  await client.restore();
  assert.equal(calls, 1);
  assert.ok(client.snapshot().expires);
});
const id = '01234567-89ab-4def-8123-456789abcdef';
const fingerprint = 'ab'.repeat(32);
function setup() {
  let now = Date.now(); const calls = []; let fail = null; let block = null;
  const proposal = { proposal_id: id, title: 'Travel checklist', items: ['Pack charger', 'Check booking'],
    fingerprint, expires_at: new Date(now + 600000).toISOString(), status: 'pending' };
  const session = { authenticated: true, csrf_token: 'a'.repeat(43), expires_at: new Date(now + 300000).toISOString() };
  const client = new SafeActionClient(async (url, options) => {
    assert.ok(url.startsWith('/api/v1/operator/'));
    assert.equal(options.credentials, 'same-origin'); assert.equal(options.cache, 'no-store');
    assert.equal(options.headers.Authorization, undefined);
    calls.push({ url, options });
    if (block) await block;
    if (fail) return Response.json({ error: fail.code || 'sensitive upstream detail' }, { status: fail.status });
    if (url.endsWith('/login') || url.endsWith('/session')) return Response.json(session);
    if (url.endsWith('/logout')) return Response.json({ authenticated: false });
    return Response.json({ ...proposal, status: url.endsWith('/approve') ? 'approved' : url.endsWith('/reject') ? 'rejected' : proposal.status });
  }, () => now);
  return { client, calls, proposal, session, advance: ms => { now += ms; },
    fail: value => { fail = value; }, block: promise => { block = promise; } };
}
async function prepared(s) { await s.client.login('fake-local-password'); await s.client.retrieve(id); }

test('login/restore/logout controls have server-driven state; logout clears proposal and CSRF', async () => {
  const s = setup(); await s.client.restore();
  assert.ok(s.client.snapshot().expires);
  await s.client.retrieve(id); assert.equal(s.client.snapshot().proposal.fingerprint, fingerprint);
  await s.client.logout(); const state = s.client.snapshot();
  assert.equal(state.expires, null); assert.equal(state.proposal, null); assert.equal(state.reviewed, false);
  assert.equal(s.calls.at(-1).options.headers['X-CSRF-Token'], s.session.csrf_token);
  assert.equal(JSON.stringify(state).includes('fake-local-password'), false);
});

test('retrieval requires authentication and displays exact backend proposal', async () => {
  const s = setup(); await s.client.retrieve(id); assert.equal(s.calls.length, 0);
  await prepared(s); const p = s.client.snapshot().proposal;
  assert.equal(p.title, s.proposal.title); assert.deepEqual([...p.items], s.proposal.items);
  assert.equal(p.proposal_id, id); assert.equal(p.fingerprint, fingerprint);
  assert.equal(p.expires_at, s.proposal.expires_at);
});

for (const action of ['approve','reject']) test(action + ' requires review and a separate confirmation; forwards fingerprint and CSRF', async () => {
  const s = setup(); await prepared(s); const before = s.calls.length;
  s.client.beginDecision(action); await s.client.confirmDecision(); assert.equal(s.calls.length, before);
  s.client.review(true); s.client.beginDecision(action);
  assert.equal(s.client.snapshot().confirmation, action); assert.equal(s.calls.length, before);
  await s.client.confirmDecision();
  const call = s.calls.at(-1);
  assert.equal(call.url, '/api/v1/operator/proposals/' + id + '/' + action);
  assert.equal(call.options.body, JSON.stringify({ fingerprint }));
  assert.equal(call.options.headers['X-CSRF-Token'], s.session.csrf_token);
  assert.equal(s.client.snapshot().proposal.status, action === 'approve' ? 'approved' : 'rejected');
  assert.equal(s.client.canDecide(), false);
});

test('cancel confirmation does not submit', async () => {
  const s = setup(); await prepared(s); s.client.review(true); s.client.beginDecision('approve');
  s.client.cancelDecision(); const count = s.calls.length; await s.client.confirmDecision();
  assert.equal(s.calls.length, count);
});

test('session expiry clears reviewed state and blocks decisions', async () => {
  const s = setup(); await prepared(s); s.client.review(true); s.client.beginDecision('approve');
  const count = s.calls.length; s.advance(300001); await s.client.confirmDecision();
  assert.equal(s.calls.length, count); assert.equal(s.client.snapshot().proposal, null);
  assert.equal(s.client.snapshot().expires, null); assert.match(s.client.snapshot().message, /session expired/);
});

test('proposal expiry is visible and cannot be submitted', async () => {
  const s = setup(); s.proposal.expires_at = new Date(Date.now() + 1000).toISOString();
  await prepared(s); s.client.review(true); s.advance(2000); s.client.expire();
  assert.equal(s.client.snapshot().proposal.status, 'expired'); assert.equal(s.client.canDecide(), false);
});

for (const status of [401,403]) test('authorization failure ' + status + ' clears proposal and session', async () => {
  const s = setup(); await prepared(s); s.fail({ status }); await s.client.retrieve(id);
  assert.equal(s.client.snapshot().expires, null); assert.equal(s.client.snapshot().proposal, null);
  assert.equal(s.client.snapshot().error, true); assert.ok(!s.client.snapshot().message.includes('sensitive'));
});

test('failed login and missing configuration remain signed out', async () => {
  const s = setup(); s.fail({ status: 401 }); await s.client.login('wrong-password');
  assert.equal(s.client.snapshot().expires, null);
  s.fail({ status: 503, code: 'OPERATOR_UNCONFIGURED' }); await s.client.login('fake-password');
  assert.equal(s.client.snapshot().expires, null); assert.match(s.client.snapshot().message, /not configured/);
});

test('conflicts and unavailable backend require refetch; never simulate success', async () => {
  for (const status of [409,502,503]) {
    const s = setup(); await prepared(s); s.client.review(true); s.client.beginDecision('approve');
    s.fail({ status }); await s.client.confirmDecision();
    assert.equal(s.client.snapshot().proposal.status, 'pending');
    assert.equal(s.client.snapshot().needsRefresh, true); assert.equal(s.client.canDecide(), false);
    assert.equal(s.client.snapshot().error, true); assert.ok(!s.client.snapshot().message.includes('sensitive'));
  }
});

test('duplicate submissions blocked synchronously while the upstream is pending', async () => {
  const s = setup(); await prepared(s); s.client.review(true); s.client.beginDecision('approve');
  let release; s.block(new Promise(resolve => { release = resolve; }));
  const before = s.calls.length; const first = s.client.confirmDecision();
  assert.equal(s.client.snapshot().busy, true);
  await s.client.confirmDecision(); await s.client.retrieve(id); await s.client.logout();
  assert.equal(s.calls.length, before + 1); release(); await first;
  assert.equal(s.client.snapshot().busy, false);
});

test('invalid UUID never fetches and review is reset on retrieval', async () => {
  const s = setup(); await prepared(s); s.client.review(true); const count = s.calls.length;
  await s.client.retrieve('https://example.com');
  assert.equal(s.calls.length, count); assert.equal(s.client.snapshot().proposal, null);
  assert.equal(s.client.snapshot().reviewed, false);
});

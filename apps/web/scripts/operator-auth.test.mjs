import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { randomBytes, scryptSync } from 'node:crypto';
import vm from 'node:vm';
import { test } from 'node:test';
import ts from 'typescript';
const require = createRequire(import.meta.url);
const password = 'independent-local-test-password-2026';
const backend = 'backend-test-key-' + 'a'.repeat(40);
const salt = randomBytes(16);
const hash = 'scrypt:' + salt.toString('hex') + ':' + scryptSync(password, salt, 64, { N: 32768, r: 8, p: 3, maxmem: 64 * 1024 * 1024 }).toString('hex');
const id = '01234567-89ab-4def-8123-456789abcdef';
const fingerprint = 'ab'.repeat(32);
function setup(origin = 'http://127.0.0.1:3200') {
  let now = Date.now(); const calls = [];
  const env = { ARQON_OPERATOR_ORIGIN: origin, ARQON_OPERATOR_LOGIN_HASH: hash,
    ARQON_OPERATOR_KEY: backend, ARQON_BACKEND_URL: 'http://127.0.0.1:8000' };
  const code = ts.transpileModule(readFileSync(new URL('../lib/operator.ts', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  const sandbox = { module, exports: module.exports, process: { env }, Buffer, Request, Response, URL,
    TextDecoder, AbortSignal, Date: class extends Date { static now() { return now; } },
    require: name => name === 'server-only' ? {} : require(name),
    fetch: async (url, options) => {
      calls.push({ url: url.toString(), options });
      return Response.json({ proposal_id: id, title: 'Travel checklist', items: ['Pack a charger'],
        fingerprint, created_at: '2030-01-01T00:00:00+00:00', expires_at: '2030-01-01T00:10:00+00:00',
        status: options.method === 'POST' ? url.pathname.endsWith('/approve') ? 'approved' : 'rejected' : 'pending',
        secret_debug: backend });
    },
  };
  vm.runInNewContext(code, sandbox);
  function request(route, { method = 'GET', body, headers = {}, originHeader = origin } = {}) {
    return module.exports.operator(new Request(origin + '/api/v1/operator/' + route, {
      method, headers: { host: new URL(origin).host, ...(originHeader ? { Origin: originHeader } : {}),
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...headers },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    }), route.split('/'));
  }
  async function login() {
    const response = await request('login', { method: 'POST', body: { password } });
    assert.equal(response.status, 200);
    const cookie = response.headers.get('set-cookie'); const data = await response.json();
    return { cookie: cookie.split(';')[0], csrf: data.csrf_token, cookieHeader: cookie, data };
  }
  return { request, login, env, calls, advance: ms => { now += ms; }, sandbox };
}
const sessionHeaders = session => ({ Cookie: session.cookie, 'X-CSRF-Token': session.csrf });

test('login establishes opaque HttpOnly Strict cookie and session-bound CSRF', async () => {
  const s = setup(); const session = await s.login();
  assert.match(session.cookieHeader, /HttpOnly; SameSite=Strict; Max-Age=600/);
  assert.doesNotMatch(session.cookieHeader, /Secure/);
  assert.equal(session.csrf.length, 43);
  const response = await s.request('session', { headers: sessionHeaders(session) });
  assert.equal(response.status, 200); assert.equal((await response.json()).csrf_token, session.csrf);
  assert.ok(!JSON.stringify(session.data).includes(password));
  assert.ok(!JSON.stringify(session.data).includes(backend));
  assert.ok(!session.cookie.includes(password));
  assert.equal(s.calls.length, 0);
});

test('wrong credentials, missing configuration and backend credential reuse fail closed', async () => {
  const s = setup();
  assert.equal((await s.request('login', { method: 'POST', body: { password: 'wrong-test-password' } })).status, 401);
  delete s.env.ARQON_OPERATOR_LOGIN_HASH;
  assert.equal((await s.request('login', { method: 'POST', body: { password } })).status, 503);
  const same = setup(); same.env.ARQON_OPERATOR_KEY = password;
  assert.equal((await same.request('login', { method: 'POST', body: { password } })).status, 401);
});

test('session expires and logout revokes immediately', async () => {
  const s = setup(); const session = await s.login();
  const logout = await s.request('logout', { method: 'POST', headers: sessionHeaders(session) });
  assert.equal(logout.status, 200); assert.match(logout.headers.get('set-cookie'), /Max-Age=0/);
  assert.equal((await s.request('session', { headers: sessionHeaders(session) })).status, 401);
  const other = await s.login(); s.advance(600001);
  assert.equal((await s.request('session', { headers: sessionHeaders(other) })).status, 401);
});

test('CSRF is required for logout and decisions, cannot be reused across sessions', async () => {
  const s = setup(); const a = await s.login(); const b = await s.login();
  for (const route of ['logout', 'proposals/' + id + '/approve', 'proposals/' + id + '/reject']) {
    for (const token of [undefined, 'invalid', b.csrf]) {
      const response = await s.request(route, { method: 'POST', body: { fingerprint },
        headers: { Cookie: a.cookie, ...(token ? { 'X-CSRF-Token': token } : {}) } });
      assert.equal(response.status, 403);
    }
  }
  assert.equal(s.calls.length, 0);
});

test('cross-origin, missing mutation Origin, and untrusted Host rejected', async () => {
  const s = setup();
  for (const originHeader of ['https://attacker.example', null]) {
    assert.equal((await s.request('login', { method: 'POST', body: { password }, originHeader })).status, 403);
  }
  assert.equal((await s.request('login', { method: 'POST', body: { password },
    headers: { host: 'attacker.example', 'X-Forwarded-Host': '127.0.0.1:3200' } })).status, 403);
  assert.equal((await s.request('session', { headers: { Cookie: 'operator=true' } })).status, 401);
});

test('unsafe remote origin configuration rejected; HTTPS sets Secure', async () => {
  const remote = setup('http://example.com');
  assert.equal((await remote.request('login', { method: 'POST', body: { password } })).status, 503);
  const secure = await setup('https://localhost:3200').login();
  assert.match(secure.cookieHeader, /; Secure$/);
});

test('unauthenticated proposal access denied, forged headers do not authorize', async () => {
  const s = setup();
  assert.equal((await s.request('proposals/' + id, { headers: {
    Authorization: 'Bearer ' + backend, 'X-Forwarded-For': '127.0.0.1', 'X-Operator-Role': 'operator',
  } })).status, 401);
  assert.equal(s.calls.length, 0);
});

for (const action of ['approve', 'reject']) test(action + ' forwards exact reviewed fingerprint with server credential only', async () => {
  const s = setup(); const session = await s.login(); const headers = sessionHeaders(session);
  const route = 'proposals/' + id;
  assert.equal((await s.request(route + '/' + action, { method: 'POST', headers, body: { fingerprint } })).status, 409);
  const get = await s.request(route, { headers }); const data = await get.json();
  assert.equal(get.status, 200); assert.equal(data.fingerprint, fingerprint); assert.equal(data.secret_debug, undefined);
  assert.equal((await s.request(route + '/' + action, { method: 'POST', headers, body: { fingerprint: 'cd'.repeat(32) } })).status, 409);
  const result = await s.request(route + '/' + action, { method: 'POST', headers, body: { fingerprint } });
  assert.equal(result.status, 200);
  assert.equal((await result.json()).status, action === 'approve' ? 'approved' : 'rejected');
  const call = s.calls.at(-1);
  assert.equal(call.options.headers.Authorization, 'Bearer ' + backend);
  assert.equal(call.options.headers.Cookie, undefined); assert.equal(call.options.headers.Origin, undefined);
  assert.equal(call.options.body, JSON.stringify({ fingerprint }));
  assert.equal((await s.request(route + '/' + action, { method: 'POST', headers, body: { fingerprint } })).status, 409);
});

test('expired/replayed backend decisions propagate safe conflict and clear reviewed state', async () => {
  const s = setup(); const session = await s.login(); const headers = sessionHeaders(session);
  await s.request('proposals/' + id, { headers });
  s.sandbox.fetch = async () => Response.json({ error: 'PROPOSAL_EXPIRED', secret: backend }, { status: 409 });
  const response = await s.request('proposals/' + id + '/approve', { method: 'POST', headers, body: { fingerprint } });
  assert.equal(response.status, 409); assert.ok(!(await response.text()).includes(backend));
});

test('login attempts throttle and oversized body is rejected', async () => {
  const s = setup();
  assert.equal((await s.request('login', { method: 'POST', body: { password: 'x'.repeat(3000) } })).status, 413);
  for (let i = 0; i < 4; i++) await s.request('login', { method: 'POST', body: { password: 'wrong-test-password' } });
  assert.equal((await s.request('login', { method: 'POST', body: { password } })).status, 429);
  s.advance(60001); assert.equal((await s.request('login', { method: 'POST', body: { password } })).status, 200);
});

test('independent server memory has no restored sessions', async () => {
  const first = setup(); const session = await first.login(); const restarted = setup();
  assert.equal((await restarted.request('session', { headers: sessionHeaders(session) })).status, 401);
});


test('compiled browser presentation contains no server configuration or credentials', () => {
  const source = readFileSync(new URL('../app/safe-action-panel.tsx', import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX } }).outputText;
  assert.doesNotMatch(compiled, /ARQON_OPERATOR_KEY|ARQON_OPERATOR_LOGIN_HASH|NEXT_PUBLIC|lib\/operator|process\.env/);
  assert.ok(!compiled.includes(password) && !compiled.includes(backend));
  const server = readFileSync(new URL('../lib/operator.ts', import.meta.url), 'utf8');
  assert.match(server, /^import 'server-only';/);
});

test('configuration rotation revokes prior sessions', async () => {
  const s = setup(); const session = await s.login();
  s.env.ARQON_OPERATOR_KEY += 'rotated';
  assert.equal((await s.request('session', { headers: sessionHeaders(session) })).status, 401);
});

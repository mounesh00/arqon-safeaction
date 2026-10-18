// Built-in test runner + already installed TypeScript/React; no test dependencies.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
function load(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(code, {
    module, exports: module.exports,
    require: name => name === 'server-only' ? {} : name === './operator' ? load('../lib/operator.ts') : name === '../lib/safe-action-client' ? load('../lib/safe-action-client.ts') : require(name),
    Request, Response, URL, Buffer, TextDecoder, AbortSignal,
    process: { env: {} },
    fetch: () => { throw new Error('Forbidden backend access'); },
  });
  return module.exports;
}
const { default: Panel, SafeActionDetails: Details } = load('../app/safe-action-panel.tsx');
const { proxy } = load('../lib/proxy.ts');

test('default panel shows no operator data and cannot initiate decisions', () => {
  const html = renderToStaticMarkup(React.createElement(Panel));
  assert.match(html, /No operator data has been loaded/);
  assert.match(html, /No proposal loaded/);
  for (const label of ['Fetch proposal', 'Approve', 'Reject']) {
    assert.match(html, new RegExp('<button[^>]*disabled=""[^>]*>' + label + '</button>'));
  }
  assert.doesNotMatch(html, /ARQON_OPERATOR_KEY|Bearer |localStorage|NEXT_PUBLIC/);
});

test('presentation preserves every item, exact fingerprint and escapes HTML', () => {
  const proposal = { proposal_id: 'synthetic-test-id', title: '<script>test</script>',
    items: ['First item', 'Second item'], fingerprint: '0123456789abcdef'.repeat(4),
    expires_at: '2030-01-01T00:00:00+00:00', status: 'pending' };
  const html = renderToStaticMarkup(React.createElement(Details, { proposal }));
  for (const value of [...proposal.items, proposal.proposal_id, proposal.fingerprint, proposal.expires_at]) {
    assert.ok(html.includes(value));
  }
  assert.ok(html.includes('&lt;script&gt;test&lt;/script&gt;'));
  assert.doesNotMatch(html, /<script>/);
});

test('operator fetch/approve/reject stay inaccessible regardless of claimed credentials or origin', async () => {
  for (const action of ['', '/approve', '/reject']) {
    for (const origin of ['http://localhost:3100', 'https://attacker.example']) {
      const path = ['operator', 'proposals', 'test-id', ...action.split('/').filter(Boolean)];
      const response = await proxy(new Request('http://localhost:3100/api/v1/' + path.join('/'), {
        method: action ? 'POST' : 'GET', headers: {
          host: 'localhost:3100', origin, Authorization: 'Bearer fake',
          Cookie: 'operator=true', 'X-CSRF-Token': 'fake', 'X-Forwarded-For': '127.0.0.1',
        },
      }), path);
      assert.equal(response.status, 404);
      assert.deepEqual(await response.json(), { error: 'NOT_FOUND' });
    }
  }
});

test('existing mock agent rejects invalid origin and malformed tasks before fetching', async () => {
  const badOrigin = await proxy(new Request('http://localhost:3100/api/v1/agent/run', {
    method: 'POST', headers: { host: 'localhost:3100', origin: 'https://attacker.example' },
  }), ['agent', 'run']);
  assert.equal(badOrigin.status, 403);
  const invalid = await proxy(new Request('http://localhost:3100/api/v1/agent/run', {
    method: 'POST', headers: { host: 'localhost:3100', 'Content-Type': 'application/json' },
    body: JSON.stringify({ task: '' }),
  }), ['agent', 'run']);
  assert.equal(invalid.status, 400);
});

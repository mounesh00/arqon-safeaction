import 'server-only';
import { operator } from './operator';
export async function proxy(request: Request, path: string[]) {
  const route = path.join('/');
  if (path[0] === 'operator') return operator(request, path.slice(1));
  const allowed = request.method === 'GET' && (route === 'health' || /^agent\/runs\/[0-9a-f-]{36}$/i.test(route)) || request.method === 'POST' && route === 'agent/run';
  const error = (code: string, status: number) => Response.json({ error: code }, { status });
  if (!allowed) return error('NOT_FOUND', 404);
  const origin = request.headers.get('origin');
  const host = request.headers.get('host') || '';
  if (!/^(127\.0\.0\.1|localhost)(:\d+)?$/.test(host)) return error('HOST_NOT_ALLOWED', 403);
  if (origin && origin !== 'http://' + host) return error('ORIGIN_NOT_ALLOWED', 403);
  let body: string | undefined;
  if (request.method === 'POST') {
    if (!request.headers.get('content-type')?.startsWith('application/json')) return error('JSON_REQUIRED', 415);
    const reader = request.body?.getReader();
    if (!reader) return error('INVALID_REQUEST', 400);
    let size = 0; const chunks: Uint8Array[] = [];
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      size += value.length;
      if (size > 24576) { await reader.cancel(); return error('BODY_TOO_LARGE', 413); }
      chunks.push(value);
    }
    try {
      const input = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)));
      if (!input || Object.keys(input).length !== 1 || typeof input.task !== 'string' || !input.task.trim() || input.task.length > 4000) return error('INVALID_TASK', 400);
      body = JSON.stringify({ task: input.task });
    } catch { return error('INVALID_JSON', 400); }
  }
  try {
    const base = new URL(process.env.ARQON_BACKEND_URL || 'http://127.0.0.1:8000');
    if (base.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(base.hostname) || base.username || base.password || base.pathname !== '/' || base.search || base.hash) return error('BACKEND_CONFIGURATION_ERROR', 503);
    const response = await fetch(new URL('/api/v1/' + route, base), {
      method: request.method, body, headers: body ? { 'Content-Type': 'application/json' } : {},
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(35000),
    });
    const data = await response.json();
    if (!response.ok && !data.run_id) return error(response.status === 404 ? 'RUN_NOT_FOUND' : 'BACKEND_REQUEST_FAILED', response.status);
    return Response.json(data, { status: response.status, headers: { 'Cache-Control': 'no-store' } });
  } catch { return error('BACKEND_UNAVAILABLE', 503); }
}

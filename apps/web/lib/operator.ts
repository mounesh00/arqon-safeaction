import 'server-only';
import { createHash, randomBytes, scrypt, timingSafeEqual } from 'node:crypto';

const COOKIE = 'arqon_operator';
const TTL = 10 * 60 * 1000;
type Session = { expires: number; csrf: string; reviewed: Map<string, string> };
type State = { config: string; sessions: Map<string, Session>; attempts: number; window: number };
// A single Node process owns this state across route-module reloads. Nothing is
// serialized to cookies/disk. Workers/processes have independent stores.
const root = globalThis as typeof globalThis & { __arqonOperatorV1?: State };
const state = root.__arqonOperatorV1 ??= { config: '', sessions: new Map(), attempts: 0, window: 0 };
const digest = (value: string) => createHash('sha256').update(value).digest('hex');
const equal = (a: string, b: string) => timingSafeEqual(Buffer.from(digest(a), 'hex'), Buffer.from(digest(b), 'hex'));
const reply = (data: object, status = 200, cookie?: string) => Response.json(data, {
  status, headers: { 'Cache-Control': 'no-store', ...(cookie ? { 'Set-Cookie': cookie } : {}) },
});
class Denied extends Error { constructor(readonly code: string, readonly status: number) { super(code); } }
function fail(code: string, status: number): never { throw new Denied(code, status); }

function configuration() {
  const originText = process.env.ARQON_OPERATOR_ORIGIN;
  const hash = process.env.ARQON_OPERATOR_LOGIN_HASH;
  const backendKey = process.env.ARQON_OPERATOR_KEY;
  const backendText = process.env.ARQON_BACKEND_URL;
  if (!originText || !hash || !backendKey || !backendText) { state.sessions.clear(); fail('OPERATOR_UNCONFIGURED', 503); }
  const origin = new URL(originText!); const backend = new URL(backendText!);
  if (origin.origin !== originText || !['http:', 'https:'].includes(origin.protocol)
      || !['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname)
      || origin.username || origin.password || origin.search || origin.hash) fail('OPERATOR_UNCONFIGURED', 503);
  if (backend.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(backend.hostname)
      || backend.pathname !== '/' || backend.username || backend.password || backend.search || backend.hash
      || !/^[\x21-\x7e]{32,256}$/.test(backendKey!)) fail('OPERATOR_UNCONFIGURED', 503);
  const parts = /^scrypt:([a-f0-9]{32}):([a-f0-9]{128})$/.exec(hash!);
  if (!parts) fail('OPERATOR_UNCONFIGURED', 503);
  const configID = digest(originText! + hash! + backendKey! + backendText!);
  if (state.config !== configID) { state.sessions.clear(); state.config = configID; }
  for (const [key, session] of state.sessions) if (session.expires <= Date.now()) state.sessions.delete(key);
  return { id: configID, origin, backend, backendKey: backendKey!, parts: parts!, secure: origin.protocol === 'https:' };
}

function boundary(request: Request, config: ReturnType<typeof configuration>) {
  // Next.js may populate forwarding headers internally. They are never used as
  // identity, locality, scheme, Host or Origin evidence. Only explicit config and
  // the actual Host/Origin are used; bind the Node server directly to loopback.
  if (request.headers.get('host') !== config.origin.host) fail('HOST_NOT_ALLOWED', 403);
  const origin = request.headers.get('origin');
  if ((origin !== null && origin !== config.origin.origin)
      || (request.method !== 'GET' && origin !== config.origin.origin)
      || request.headers.get('sec-fetch-site') === 'cross-site') fail('ORIGIN_NOT_ALLOWED', 403);
}

function cookieToken(request: Request) {
  const values = (request.headers.get('cookie') || '').split(';').map(s => s.trim())
    .filter(s => s.startsWith(COOKIE + '='));
  if (values.length !== 1) return '';
  const value = values[0].slice(COOKIE.length + 1);
  return /^[A-Za-z0-9_-]{43}$/.test(value) ? value : '';
}
function sessionFor(request: Request) {
  const token = cookieToken(request);
  const session = token ? state.sessions.get(digest(token)) : undefined;
  if (!session || session.expires <= Date.now()) fail('OPERATOR_SESSION_REQUIRED', 401);
  return session!;
}
function csrf(request: Request, session: Session) {
  const value = request.headers.get('x-csrf-token');
  if (!value || !equal(value, session.csrf)) fail('CSRF_REQUIRED', 403);
}
function cookie(value: string, secure: boolean, seconds: number) {
  return `${COOKIE}=${value}; Path=/api/v1/operator; HttpOnly; SameSite=Strict; Max-Age=${seconds}${secure ? '; Secure' : ''}`;
}
async function body(request: Request, limit: number): Promise<Record<string, unknown>> {
  if (request.headers.get('content-type')?.split(';')[0] !== 'application/json'
      || !['identity', null].includes(request.headers.get('content-encoding'))) fail('INVALID_REQUEST', 400);
  const reader = request.body?.getReader(); if (!reader) fail('INVALID_REQUEST', 400);
  const chunks: Uint8Array[] = []; let size = 0;
  while (true) {
    const part = await reader!.read(); if (part.done) break;
    size += part.value.length;
    if (size > limit) { await reader!.cancel(); fail('BODY_TOO_LARGE', 413); }
    chunks.push(part.value);
  }
  let data;
  try { data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))); }
  catch { fail('INVALID_REQUEST', 400); }
  if (!data || typeof data !== 'object' || Array.isArray(data)) fail('INVALID_REQUEST', 400);
  return data;
}

export async function operator(request: Request, path: string[]) {
  const route = path.join('/');
  const match = /^proposals\/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})(?:\/(approve|reject))?$/.exec(route);
  if (!(['login', 'session', 'logout'].includes(route) || match)) return reply({ error: 'NOT_FOUND' }, 404);
  try {
    const config = configuration(); boundary(request, config);
    if (route === 'login' && request.method === 'POST') {
      // Global local-operator throttle cannot be evaded with spoofed client IPs.
      if (Date.now() - state.window >= 60000) { state.window = Date.now(); state.attempts = 0; }
      if (++state.attempts > 5) fail('LOGIN_THROTTLED', 429);
      const data = await body(request, 2048);
      if (Object.keys(data).length !== 1 || typeof data.password !== 'string'
          || Buffer.byteLength(data.password) < 16 || Buffer.byteLength(data.password) > 1024) fail('LOGIN_FAILED', 401);
      const key = await new Promise<Buffer>((resolve, reject) => scrypt(data.password as string,
        Buffer.from(config.parts[1], 'hex'), 64, { N: 32768, r: 8, p: 3, maxmem: 64 * 1024 * 1024 },
        (error, value) => error ? reject(error) : resolve(value)));
      if (!timingSafeEqual(key, Buffer.from(config.parts[2], 'hex')) || equal(data.password, config.backendKey)) fail('LOGIN_FAILED', 401);
      if (state.config !== config.id) fail('OPERATOR_UNCONFIGURED', 503);
      const previous = cookieToken(request); if (previous) state.sessions.delete(digest(previous));
      if (state.sessions.size >= 8) fail('SESSION_LIMIT', 429);
      const token = randomBytes(32).toString('base64url');
      const session = { expires: Date.now() + TTL, csrf: randomBytes(32).toString('base64url'), reviewed: new Map<string, string>() };
      state.sessions.set(digest(token), session);
      return reply({ authenticated: true, csrf_token: session.csrf, expires_at: new Date(session.expires).toISOString() },
        200, cookie(token, config.secure, TTL / 1000));
    }
    const session = sessionFor(request);
    if (route === 'session' && request.method === 'GET') return reply({ authenticated: true,
      csrf_token: session.csrf, expires_at: new Date(session.expires).toISOString() });
    if (route === 'logout' && request.method === 'POST') {
      csrf(request, session); state.sessions.delete(digest(cookieToken(request)));
      return reply({ authenticated: false }, 200, cookie('', config.secure, 0));
    }
    if (!match || (match[2] ? request.method !== 'POST' : request.method !== 'GET')) fail('METHOD_NOT_ALLOWED', 405);
    let payload: string | undefined;
    if (match[2]) {
      csrf(request, session);
      const data = await body(request, 256);
      if (Object.keys(data).length !== 1 || typeof data.fingerprint !== 'string'
          || !/^[a-f0-9]{64}$/.test(data.fingerprint)) fail('INVALID_REQUEST', 400);
      const reviewed = session.reviewed.get(match[1]);
      if (!reviewed || !equal(data.fingerprint, reviewed)) fail('REVIEW_REQUIRED', 409);
      payload = JSON.stringify({ fingerprint: data.fingerprint });
    }
    if (sessionFor(request) !== session || state.config !== config.id) fail('OPERATOR_SESSION_REQUIRED', 401);
    const response = await fetch(new URL('/api/v1/operator/' + route, config.backend), {
      method: request.method, body: payload, headers: {
        Authorization: 'Bearer ' + config.backendKey, ...(payload ? { 'Content-Type': 'application/json' } : {}),
      }, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) {
      if (response.status === 409) session.reviewed.delete(match[1]);
      return reply({ error: response.status === 409 ? 'PROPOSAL_NOT_ACTIONABLE' : 'OPERATOR_BACKEND_FAILED' },
        [401,403,404,409].includes(response.status) ? response.status : 502);
    }
    const data = await response.json();
    if (data.proposal_id !== match[1] || typeof data.fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(data.fingerprint)
        || typeof data.title !== 'string' || !Array.isArray(data.items) || !data.items.every((item: unknown) => typeof item === 'string')
        || !['pending','approved','rejected','expired'].includes(data.status)
        || typeof data.created_at !== 'string' || typeof data.expires_at !== 'string') fail('INVALID_BACKEND_RESPONSE', 502);
    if (!match[2] && data.status === 'pending') {
      if (session.reviewed.size >= 32) session.reviewed.clear();
      session.reviewed.set(match[1], data.fingerprint);
    } else session.reviewed.delete(match[1]);
    const result = { proposal_id: data.proposal_id, title: data.title, items: data.items, fingerprint: data.fingerprint,
      created_at: data.created_at, expires_at: data.expires_at, status: data.status };
    if (JSON.stringify(result).includes(config.backendKey)) fail('INVALID_BACKEND_RESPONSE', 502);
    return reply(result);
  } catch (error) {
    if (error instanceof Denied) return reply({ error: error.code }, error.status);
    return reply({ error: 'OPERATOR_UNAVAILABLE' }, 503);
  }
}

# Security model and review

This is a reviewed local prototype, not a claim of certification or production safety.
Only direct loopback listeners, one trusted local operator and synthetic data are
supported. See docs/RELEASE_READINESS.md for measured checks and limitations.

## Authentication and sessions

The human password is independent of the backend bearer. Node verifies a salted
scrypt hash (N=32768, r=8, p=3, 64-byte verifier) with constant-time comparison.
The existing global throttle allows five attempts/minute. An unpredictable opaque
256-bit cookie is HttpOnly, host-only, SameSite=Strict, scoped to operator routes,
and has ten-minute absolute expiry. Only its hash is stored server-side. Logout,
expiry, configuration change or process exit revoke sessions. Secure is set for
HTTPS; this demo uses explicit loopback HTTP, not public transport security.

## CSRF and review boundary

Every post-login mutation requires exact configured Origin and session CSRF.
Host and cross-site Fetch Metadata are checked; forwarded headers do not establish
identity. Login requires strict Origin/content type plus the independent password.
No CORS permission or backend credential is exposed to the browser. Operator
retrieval records the exact reviewed fingerprint in the session. The UI displays
all content and needs a separate explicit human confirmation. Server policy checks
are authoritative; hiding or disabling buttons is not authorization.

## Integrity, expiry and replay

SHA-256 fingerprints are deterministic integrity comparisons, not signatures or
proof of identity. Database decisions validate canonical content, fingerprint,
pending status and expiry. Approved saves and durable decisions commit atomically;
rejected/expired/tampered/replayed proposals cannot save. ApprovalManager requires
configured human decisions, bound context, expiry and atomic single-use consumption.
No model or MCP client can grant itself permissions or become an operator through
an exposed tool. Arbitrary Python callers with local process access remain trusted.

## Transport and credential handling

FastAPI and Next.js bind to 127.0.0.1. FastAPI rejects forwarded identity assertions,
nonlocal operator peers and browser Origin. Node uses a fixed loopback backend URL,
server-only bearer, no redirects, and bounded proxy timeouts. MCP uses stdio and
receives no operator secrets. ModelGateway uses only MockModelProvider in this
package; no live inference adapter or legacy scanners are shipped.
The launcher copies source to temporary private storage without .env files,
generates a backend key in memory, and never prints passwords, cookies or CSRF.
Keep screenshots free of DevTools and credential files. Do not log request bodies
or authorization headers. Synthetic negative-test strings are not usable secrets.

## Supported boundary and residual risks

No authentication for the nonprivileged local mock-agent endpoints; any local user
may invoke them. Loopback is not user isolation. No multi-user authentication,
distributed sessions, general rate limiting, public HTTPS, reverse-proxy trust,
DoS/resource quotas, remote MCP hosting, comprehensive XSS defense or network
sandbox is claimed. Same-user process/environment inspection and direct database
writes are outside the threat model. SQLite fingerprints do not defeat an attacker
who can rewrite both data and hashes. Expiry is checked on access/decision rather
than by a background worker. The legacy process-local SafeActionWorkflow is retained
for tested compatibility; only PersistentSafeActionWorkflow is the durable API path.

## Privacy and release handling

Only synthetic generic travel items appear in demo data. No customer records,
security targets/evidence, private database, environment, credential, virtualenv,
node_modules or cache belongs in an archive. .gitignore is defense-in-depth;
release packaging uses an explicit file allowlist and SHA-256 manifest.
No third-party dependency advisory service was contacted: this is a local code and
packaging review, not an online vulnerability audit or penetration test.

## Reporting issues

No public security contact has been designated. Contact the owner privately via
an existing trusted channel; never post credentials or vulnerability details in
public. Owner must select a reporting channel and confirm redistribution rights
before public release.

## Public candidate licensing and reporting

The placeholder MIT LICENSE is not owner approval or legal clearance. See
[licensing review](docs/LICENSING_REVIEW.md) and the
[public packaging review](docs/PUBLIC_RELEASE_SECURITY_REVIEW.md). A public private-
reporting contact is **OWNER ACTION REQUIRED**; no address is invented.

# Release preflight and verification record

Source: `<OWNER_LOCAL_SOURCE_ROOT>`.
Submission: `/path/to/arqon-safeaction`.
Prepared locally on 2026-10-18; no commits, publication or external calls.

Preflight: source exists, no Git metadata, no LICENSE file. Source pyproject metadata
says MIT but copyright ownership/standalone grant is unconfirmed. An explicit
allowlist selected only SafeAction dependencies, dashboard, tests and local demos.
Internal AST import closure has no Architect-VAPT dependency. No architecture
rewrite is needed. CLI, security adapters, live model providers, scanners, customer
data, evidence and original databases are excluded.

Release-local adjustments: standalone packaging metadata and dependency profiles;
portable configurable launcher interpreter paths and production rehearsal mode;
cross-environment test interpreter selection; clean generated Next type declarations.
Original source application modules and UI policy are copied without changes.

Two environments are deliberate. Backend uses FastAPI 0.115.6 / Starlette 0.41.3 /
Pydantic 2.10.4; official MCP uses MCP 1.30.0 / newer Starlette/Pydantic. The inherited
MCP environment also has an old FastAPI installed that is incompatible with its
Starlette; backend tests must not run there. Pinned profiles and separate verification
commands prevent that known mismatch. Node lockfile pins actual frontend versions.

## Evidence

- PASS: 333 backend/runtime/core/permission/SafeAction/API tests.
- PASS: 27 official MCP/protocol/stdio/durable-bridge/demo tests.
- PASS: 32 frontend operator-auth/UI/proxy tests. **392 total automated tests.**
- PASS: TypeScript `tsc --noEmit --incremental false`.
- PASS: Next.js 16.4.0 `next build --webpack`, exit 0. Static `/` and `/_not-found`,
  dynamic `/api/v1/[...path]` generated successfully.
- PASS: official MCP initialization and all three tools against packaged modules.
- PASS: one actual standalone production (`next start`) browser rehearsal: local
  login, full review, fingerprint confirmation, A approve/save, B reject/no save,
  disabled decided controls and logout.
- PASS: 25 additional real-local checks including missing session, CSRF,
  Host/Origin, wrong fingerprint, expiry, database tampering, replay, MCP privilege
  denial, independent session logout and exactly one saved checklist.
- PASS: session expiry/revocation and cross-session CSRF in clock-controlled
  frontend tests; no claim of waiting ten real minutes in the browser.
- PASS: imported application paths resolve to the standalone directory, no
  Architect-VAPT/scanner/live-provider import dependencies.
- PASS: HTTP listeners observed only at 127.0.0.1:8100 and 127.0.0.1:3210.
- PASS: no operator credential configuration markers in client JavaScript chunks.
- PASS: local explicit-file and credential-pattern/privacy review; original
  selected source hashes unchanged. No online dependency advisory audit performed.
- PASS: human/browser and HTTP test sessions logged out; owned services closed;
  temporary databases, credentials, logs and build environments removed before ZIP.

Commands use existing installed Python/Node dependencies; **no dependency was
installed and no external request or real inference was made**. Fresh installation
from package registries is documented but was not executed under this offline task.
For verification only, installed node_modules was linked temporarily, never shipped.
External existing Python environments were selected through ARQON_BACKEND_PYTHON and
ARQON_MCP_PYTHON. No original source modifications or architecture changes were made.

The release-local launcher changes are packaging adaptations, not security-policy
changes. All application runtime/security modules and frontend UI/policy match
source provenance; the prior native fetch receiver fix is already in that source.
No release-blocking application defect was found during this standalone verification.

Production build, test bytecode/cache, dependency links and temporary credentials
are intentionally absent from the archive. Rebuild after `npm ci` for a fresh local
installation. Requirements pin tested transitive dependency closures for this
Python 3.13/macOS profile; cross-platform deployment is not certified.

## Owner gates

License/redistribution confirmation, actual video recording, authorized repository
creation/upload, final hackathon rule review and final submission are owner actions.
The package will remain blocked for publication until those gates are resolved.

## Subsequent public-candidate preparation

The independent audit baseline and runtime measurements above are historical.
DOC-01 is corrected without changing runtime behavior, local private paths were
redacted, and a placeholder MIT LICENSE plus public-release guides were added.
The original source project is unchanged. Current candidate status and detached
archive checksum instructions are in [PUBLIC_RELEASE_READINESS.md](PUBLIC_RELEASE_READINESS.md).

## License-finalized release candidate update

The earlier audit/candidate descriptions above are historical. The current LICENSE
header is Copyright (c) 2026 Mounesh H Pattar; full MIT body is preserved. Rights and
notice clearance remain owner gates. See PUBLIC_RELEASE_READINESS.md for current
integrity scope; this task did not rerun application tests or alter functionality.

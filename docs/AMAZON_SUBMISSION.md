# Copy-ready draft — owner review required

**Project title:** Arqon SafeAction

**Tagline:** Let an assistant propose; let a person decide.

**Problem statement:** Assistant-generated actions need a trustworthy handoff from
suggestion to execution. A conversational approval alone can hide which exact
content was reviewed and whether an action was already performed.

**Solution:** SafeAction creates a deterministic synthetic travel checklist through
an official MCP stdio server. A separately authenticated local operator reviews the
full proposal, fingerprint and expiration in a dashboard, then explicitly approves
saving it or rejects it without saving. SQLite preserves the proposal and decision.

**Technical implementation:** Python 3.13, official MCP SDK, FastAPI, SQLite and
Next.js/React/TypeScript. Three narrowly allowlisted MCP tools provide health, a
mock agent and proposal creation. Node server sessions, CSRF and exact reviewed
fingerprints protect the human boundary. Atomic SQLite decisions provide
exactly-once checklist saving and replay rejection.

**Amazon/Alexa+ relevance:** This is a simulated Alexa+-style experience using an
MCP-compatible architecture. It is not a live Alexa+ integration. It illustrates
how a future voice-assistant integration could propose an action while preserving
a separate human review boundary. Actual Alexa+ transport, registration, hosting,
identity, consent and compatibility remain unverified future work. Owner must
confirm the current hackathon rules allow this local simulation before submitting.

**Innovation:** A small, inspectable proposal-only MCP surface paired with an
independent authenticated human decision channel, content binding, explicit
confirmation and durable replay protection. This is an implementation approach,
not a claim of novelty over all existing systems or a measured benchmark.

**Demonstration summary:** Official MCP creates two synthetic proposals. The browser
operator approves A, producing one saved checklist, and rejects B, producing none.
Session, CSRF, integrity, expiry and replay checks are tested with controlled data.
A recording script is provided; no actual video file is included.

**Limitations:** Local stdio only, mock model, one operator and one Node process.
No Alexa+ connection, voice invocation, real booking, live model inference, public
deployment, customer traction, awards or performance benchmarks are claimed.

**Repository link:** [OWNER MUST ADD AN AUTHORIZED PUBLIC REPOSITORY URL]

**Video link:** [OWNER MUST RECORD, VERIFY, AUTHORIZE UPLOAD AND ADD URL]

**License/rights:** MIT proposed; LICENSE header finalized as Copyright (c) 2026 Mounesh H Pattar. Owner attestations are recorded and scoped source-only notice review is complete; independent legal verification is not claimed. Separate publication authorization remains required.

Do not submit this draft until owner gates in RELEASE_CHECKLIST.md are satisfied.
No repository, deployment or submission was created by release preparation.

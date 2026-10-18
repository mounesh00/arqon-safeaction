# Contributing

This repository is being prepared as a local single-operator prototype. The MIT header names Mounesh H Pattar as approved by the owner. Source-only rights review now records owner attestations; public publication
still requires separate authorization. The public
security contact and repository URL are not yet set.

Keep contributions small and relevant to the proposal/review boundary. Preserve
MCP's three-tool allowlist, independent operator authentication, session CSRF,
exact reviewed fingerprints, expiry, replay protection and loopback binding.
Do not add real Alexa+ claims, paid inference, scanners or public deployment by default.

Use separate Python environments and the installation/demo commands in
[README.md](README.md). Run affected packaged tests first; use
`bash scripts/verify_local.sh` for a full relevant local release check. Do not
install new dependencies, expand permissions or rework architecture without a
maintainer-approved scope. Only synthetic data belongs in tests and screenshots.
Never commit .env files, credentials, sessions, databases, logs, build output or
private recordings. Review staged files privately before any commit.

For security concerns use an existing private channel to the owner; see
[SECURITY.md](SECURITY.md). No public email address has been designated. Do not put
sensitive exploit details or secrets into public issues.

Only contribute code/assets you are authorized to share. Identify any third-party
source and its exact upstream notice/license. Do not assume project MIT covers
third-party dependencies or that generated content automatically clears rights.
This guide does not create a CLA, verify contributor rights, or grant publication approval.

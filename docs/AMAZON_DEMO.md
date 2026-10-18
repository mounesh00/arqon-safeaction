# Local Amazon hackathon recording demo

This is a simulated Alexa+-style experience using an MCP-compatible architecture. It is not a live Alexa+ integration.
Every checklist is synthetic demonstration data. Nothing contacts Alexa+, an AI
provider or an external destination. Existing Architect-VAPT remains untouched.

## Prerequisites

From `/path/to/arqon-safeaction`, use the existing
`.venv-mcp/bin/python` with official MCP SDK, `.venv-backend/bin/python` with
FastAPI/Uvicorn, installed Node 22+, and `apps/web/node_modules`. See README.md for fresh setup; reuse installed environments during local verification.
Keep ports 8100 and 3210 free. Choose an independent operator password of at least
16 UTF-8 bytes, kept privately in your password manager. Never use an API key.

## Safe local startup

```sh
cd /path/to/arqon-safeaction
.venv-mcp/bin/python -B -m examples.amazon_recording_demo
```

Enter and confirm the operator password at the hidden terminal prompts, before
recording. The launcher generates a separate random backend credential and salted
scrypt login verifier, passed only to the appropriate servers. It never prints
passwords, credentials, cookies or CSRF tokens. MCP receives no operator secrets.
No persistent .env or existing database is changed. Source is copied to a private
temporary frontend directory, using installed dependencies and temporary caches.

Wait for READY. All HTTP listeners bind to **127.0.0.1**, using one persistent
Next.js process. The official SDK launches the actual MCP stdio server and creates
two independent proposals in the same dedicated SQLite database as FastAPI. The
launcher checks both are visible through authenticated backend retrieval. It prints
only public metadata: dashboard URL, A/B IDs, expiry and cleanup command.

Open `http://127.0.0.1:3210`. Log in with the independent password. Do not open
DevTools, environment files, cookie inspectors or network headers while recording.
Only the masked login field may appear. No secrets belong in screenshots or scripts.

## Demonstration sequence

Use AMAZON_VIDEO_SCRIPT.md for the 170-second narration. Start recording only
after READY; keep the launcher running in the same terminal throughout.

1. Show the terminal disclaimer and two **synthetic** IDs.
2. Show dashboard login/session. Fetch A using its exact ID.
3. Read title, all five items, ID, fingerprint, expiry and pending status.
4. Check the review checkbox; click Approve; show the exact fingerprint in the
   separate confirmation; click Confirm approve.
5. Show “Checklist approved and saved by the backend” and approved status.
6. Fetch B. Review its content; check review; Reject; Confirm reject.
7. Show rejected status and “Checklist was not saved”; decision controls disable.
8. Refetch A to show its durable approved state. State the limitations honestly.
9. Stop recording, log out, then clean up.

## Expected outcomes

A and B have different UUIDs but intentionally identical generic travel content.
Labels A/B are terminal demonstration labels, not altered application data.
Before decisions both are pending and neither is saved. After the human flow,
A is approved with exactly one saved checklist; B is rejected with none.
Both remain in the shared database until cleanup. Session and proposal TTLs remain
ten minutes; recording within three minutes leaves room for deliberate review.
No automatic decisions or AI tool calls occur. Fingerprint, CSRF, expiry, replay
and original MCP permission checks remain enforced.

## Troubleshooting

- Startup failure: ensure environments exist and ports are unused. The launcher
  stops its own processes; it never kills another listener. Pick free ports:
  `--backend-port 8101 --web-port 3211`; open the printed dashboard URL.
- Expired proposal/session: log out, stop the launcher and start a fresh rehearsal.
  Never edit timestamps or disable security checks for recording.
- Login rejected: use your independent password; five attempts/minute is the
  existing limit. Wait a minute rather than weakening authentication.
- Slow initial page: let compilation finish before READY. Proposals are created
  after warm-up. Keep the same Node process throughout; do not restart mid-session.
- Changed/conflicting decision: refetch status. Do not retry blindly.
- Private password-file input is available for controlled local verification via
  `--password-file /absolute/private/file`; it must be owned by you and mode 0600.
  It is never copied or deleted by the launcher; its owner manages its lifecycle.

## Cleanup

Log out first. Press **Ctrl-C in the launcher terminal**, or run the exact
`touch /.../STOP` command printed by that instance. This signals only that demo.
The launcher closes its official MCP client/server and terminates only service
process groups it created. It removes only its dedicated temporary directory,
including database, logs, sessions (with Node exit), verifier and backend key.
No `killall`, broad process matching, or repository deletion is needed.

## Honest limitations

Local stdio MCP and a single local operator only. No Alexa+ registration,
connection, voice invocation, public deployment, paid model call or travel booking
is demonstrated. The MCP server can propose, never approve/reject/save. The person
uses authenticated dashboard controls. Session state is in one Node process;
durable proposals/checklists are SQLite records retained only for the demo's
lifetime. Fingerprints provide context integrity, not identity signatures.
Same-OS-user compromise is outside this local boundary. The launcher is recording
orchestration, not a production supervisor.

## Portable verification environments and production rehearsal

The launcher defaults to `.venv-backend/bin/python` and `.venv-mcp/bin/python`
inside this package. To reuse already-installed environments, export absolute
`ARQON_BACKEND_PYTHON` and `ARQON_MCP_PYTHON` paths; these paths are not credentials.
From `apps/web`, run `npm run build`, then start the launcher with `--production`
to rehearse the tested production output locally. No public binding is supported.

# Arqon SafeAction recording — 170 seconds

Prerecord: run AMAZON_DEMO.md startup, wait for READY, know the A/B IDs and sign in
privately or show only the masked password field. Keep one server process running.
Use only synthetic proposals. Never show secrets, DevTools, cookies or CSRF tokens.

| Time | Narration | On-screen action |
| --- | --- | --- |
| 0:00–0:15 | “Arqon OS explores how an assistant can propose useful actions while a person retains control. This is a simulated Alexa+-style experience using an MCP-compatible architecture. It is not a live Alexa+ integration.” | Show dashboard and terminal's explicit simulation disclaimer. |
| 0:15–0:30 | “The official MCP stdio server created two synthetic travel checklists. The local backend and dashboard share their proposals through SQLite.” | Show READY, synthetic A/B IDs and local URL. Do not show environment or private files. |
| 0:30–0:45 | “The model-facing MCP tools cannot approve or save. I sign in independently as the local operator.” | Show authenticated operator session, or briefly enter the masked password and Log in. |
| 0:45–1:10 | “Here is proposal A: every item, its unique ID, exact content fingerprint, expiration and pending status. Approval applies to this reviewed proposal.” | Paste A; Fetch proposal; scroll deliberately through all five items and metadata. |
| 1:10–1:35 | “I acknowledge the review, then explicitly confirm approval. The backend verifies the decision and saves exactly this checklist.” | Check review; Approve; pause on confirmation/fingerprint; Confirm approve. Show approved status and saved message. |
| 1:35–2:05 | “Proposal B is independent. I can decline it just as explicitly. Rejection records the decision without saving a checklist.” | Fetch B; review details; check review; Reject; pause on confirmation; Confirm reject. Show rejected message. |
| 2:05–2:30 | “Decided proposals cannot be submitted again. The controls are disabled. Refetching A returns its approved state from the backend.” | Show disabled decision controls; fetch A again; show approved state. Do not imply this UI alone proves all security properties. |
| 2:30–2:50 | “This local prototype demonstrates proposal, authenticated human review, approval or rejection, and durable state. Alexa+ connectivity, voice invocation and public deployment remain future work.” | End on approved details and simulation caption. Stop recording; log out and clean up afterward. |

Total scripted runtime: **2 minutes 50 seconds (170 seconds)**. If compilation or
login is slow, stop and rehearse again with fresh proposals; do not rush review or
bypass confirmations. No real Alexa+ UI, Alexa branding implication, real traveler
information or invented live integration should appear.

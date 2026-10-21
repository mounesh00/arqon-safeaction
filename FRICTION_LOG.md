# Arqon SafeAction — Development Friction Log

Reviewed: October 21, 2026.

## Project and evidence scope

SafeAction is a local, simulated Alexa+-style experience: an assistant-facing MCP
surface proposes a synthetic travel checklist, and an independently authenticated
person reviews and explicitly approves saving it or rejects it without saving.
It is **not a live Alexa+ integration**. The submitted workflow uses deterministic
mock output, not external AI inference.

The verified stack includes Python 3.13.5, official MCP Python SDK 1.30.0,
FastAPI, SQLite, Next.js, React, TypeScript and Node.js. Local production work used
an Intel Mac with macOS tools. Application evidence is summarized in
[ARCHITECTURE.md](ARCHITECTURE.md), [SECURITY.md](SECURITY.md) and the dated
[verification record](docs/VERIFICATION_RESULTS.json). Recording/export observations
below come from the October 21 local production session; its media and detailed
QA records remain outside this source repository.

## 1. Coordinating MCP proposals and human decisions

**Task attempted:** Connect MCP proposal creation to FastAPI, authenticated browser
review and durable SQLite decisions across separate processes.

**Steps taken:** Reused the existing agent, permission and approval contracts;
stored proposals in shared SQLite; added independent operator authentication,
reviewed-content fingerprints and explicit approve/reject routes; exercised the
MCP-to-backend-to-dashboard flow and checked saved rows.

**Expected result:** Assistant-facing proposals remain pending until an authorized
human decides. Approval saves the reviewed checklist once; rejection never saves it.

**Actual result:** Proposal state, permissions, operator identity, expiry and
persistence had to be coordinated across the MCP, Python API and Node processes.
This was application integration work, not evidence of a defect in an Amazon API.
The local Node session map also requires one persistent server process.

**Severity:** Moderate — cross-process integration effort and security-sensitive
state handling, rather than a confirmed upstream outage.

**Workaround:** Shared durable workflow state, a separate authenticated decision
channel, exact fingerprint checks and atomic SQLite decisions, supported by focused
and end-to-end checks. Expired demo proposals were replaced with fresh proposals;
expiry and authentication were not disabled.

**Actionable suggestion:** MCP tooling and examples could provide a reference
human-approval schema covering proposal identity, content binding, expiry,
operator authentication and terminal decision states, while keeping authorization
outside model-controlled tools.

**Final outcome:** The October 21 gallery rehearsal verified one saved checklist
for approved A and zero for rejected B. The packaged October 18 verification
record reports 392 tests; those historical tests were not rerun for this log.

## 2. Capturing an automated browser demonstration

**Task attempted:** Record the genuine running workflow for the hackathon video.

**Steps taken:** Checked macOS screen-capture access, inspected installed browser
and recording capabilities, tried Playwright with installed Chromium binaries,
and inspected the managed browser's supported APIs.

**Expected result:** Automated video capture of the actual local application.

**Actual result:** Screen-capture preflight returned NO even after the operator
reported enabling access and restarting the host. The restricted environment
prevented conclusive privacy-log diagnosis; the underlying permission-versus-
sandbox cause remains unconfirmed. Playwright expected a browser revision absent
from the cache; explicitly selecting existing binaries still failed, with
SIGTRAP for the headless browser and SIGABRT for the full browser. The managed
browser exposed screenshot capture but no video-export API.

**Severity:** High — blocked the planned continuous automated recording, while the
application itself remained usable.

**Workaround:** Used the working managed browser to perform real operator actions
and capture genuine application states. Kept screenshot provenance and separately
verified SQLite persistence; no synthetic UI, fabricated logs or approval bypasses
were introduced.

**Actionable suggestion:** Automation hosts should distinguish operating-system
permission failures from execution-sandbox restrictions, report the responsible
application/helper identity, and expose a documented browser-only video export
with compatible browser-version diagnostics.

**Final outcome:** Captured authentic proposal, confirmation, approved, rejected
and refetched states. The final video is explicitly labelled as assembled from
screenshots of real application states, not continuous screen footage. The
post-logout screenshot misses the signed-out panel; that limitation is disclosed
onscreen. Three separately verified PNG gallery captures were also prepared.

## 3. Exporting a narrated MP4

**Task attempted:** Assemble the genuine screenshots, existing English narration
and captions into an H.264/AAC MP4 under three minutes.

**Steps taken:** Tried native macOS encoding, inspected existing FFmpeg codecs and
muxers, then tested an explicitly authorized isolated software encoder. Checked
rendered frames, full decoding, browser playback and audio synchronization.

**Expected result:** A valid, readable, synchronized MP4 without changing the app.

**Actual result:** Native encoding failed with AVFoundation -11800 and underlying
VideoToolbox -12903 (invalid session), including software-only H.264 selection.
These errors did not establish a definitive root cause. The preinstalled reduced
Playwright FFmpeg build supported VP8/PNG and WebM, but lacked MP4, H.264 and AAC.
An initial per-scene AAC join also introduced timing drift during assembly.

**Severity:** High — blocked the requested export until a usable encoder and audio
assembly method were available; not a runtime application failure.

**Workaround:** After explicit approval, installed only imageio-ffmpeg 0.6.0 in a
temporary isolated environment. Verified its bundled FFmpeg's MP4, software H.264
and AAC capabilities with an encode/decode probe. Reused all eight narration clips
at 1.06 times their original tempo, retimed captions, and replaced the drifting AAC
join with one continuous narration track before final encoding.

**Actionable suggestion:** Media tooling should offer a tested software-encoding
fallback, list available codecs/muxers before export, explain native session errors
more clearly, and include examples for continuous audio timing across still-image
scenes.

**Final outcome:** Exported a 164.41-second, 1920×1080, 15-fps H.264/AAC MP4.
Full audio/video decoding and browser playback passed. All nine source screenshot
hashes matched provenance; sampled decoded frames matched their intended editorial
frames, and all eight sampled narration segments passed synchronization checks.
The video remains outside the repository; export does not imply upload or submission.

## Limitations and disclosure

These observations concern this local prototype and its recording environment;
they are not general reliability claims about the tools. No issue above is
attributed to Amazon, AWS or an Alexa+ SDK. No Alexa+ registration, live connection,
voice invocation, public runtime deployment or real-world action was tested.
SQLite records are mutable local evidence, not a tamper-proof audit service.
Suggestions are project-specific requests, not claims that an upstream product
has accepted them. This documentation publication changes no application behavior
and does not constitute a Devpost submission.

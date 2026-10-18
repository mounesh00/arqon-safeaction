# Final source-release rights review

**Verdict: READY FOR PUBLICATION AUTHORIZATION, limited to this exact source ZIP.**
**Third-party notice review: COMPLETE for identified shipped materials.**
No current exact-path third-party permission/notice blocker was identified. This
is not legal clearance, proof of title, permission for future bundled dependencies,
or authorization to create/push a public repository.

## Owner-provided attestations

Recorded from the owner's explicit instructions on 2026-10-18:

1. **Original project code: YES**, ownership or publication permission confirmed.
2. **Arqon branding: YES**, ownership or permission confirmed.
3. **Screenshots and visual assets: YES**, ownership or redistribution permission confirmed.

These are owner-provided statements, not independently verified legal conclusions.
They are relied on for the owner's project materials, not used to override any
third-party license. The selected MIT header remains Copyright (c) 2026 Mounesh H
Pattar. Full contribution history and legal title were not independently reconstructed.

## Exact redistribution scope

- **Referenced external dependencies:** requirements-backend.txt (20 recorded
  profile entries), requirements-mcp.txt (35 recorded entries), pyproject.toml,
  apps/web/package.json and apps/web/package-lock.json (100 recorded npm entries).
  The npm inventory matches package names/versions in the lockfile. Metadata does
  not establish all upstream permissions; blank fields are preserved.
- **Actually bundled dependency code/assets/binaries:** none identified. No
  node_modules, environments, .next builds, wheels, archives, native libraries,
  certificate stores, downloaded datasets, external fonts or vendored packages.
- **Copied project materials:** 56 original-source hashes in SOURCE_PROVENANCE.json
  record migration from the owner's project. These are not an external package
  attribution list. Owner attestation covers original project code/permission.
  Hash evidence does not independently prove authorship.
- **Framework scaffolding:** apps/web/next-env.d.ts consists of two triple-slash
  type references only. Next/PostCSS/TypeScript config and package metadata invoke
  external packages without embedding their implementations. No substantive
  copied upstream framework body or associated removed notice was identified.
- **Original/project-prepared assets:** docs/assets/submission-production-approved.png
  and docs/assets/submission-production-rejected.png are the two bundled synthetic
  UI screenshots; owner redistribution permission is explicitly attested. Branding
  is rendered by the project UI; no separate third-party logo, font or icon file
  is bundled. Generated/project-prepared documentation is distinguished from
  independently verified authorship.

## License conditions reviewed against actual release materials

The following applies only to this source ZIP, not installed environments or
future built distributions. Dependency references are not copies of package code.
No license/copyright notice found in shipped source was removed. No exact shipped
third-party implementation, font or asset requiring an additional notice was
identified; this is an evidence-based inventory finding, not proof of universal
originality. No author or upstream copyright text has been invented.

| Referenced material | License source and relevant conditions | Current artifact finding |
| --- | --- | --- |
| certifi 2025.4.26 (both Python profiles); lightningcss 1.32.0 and optional platform variants | [MPL 2.0 §§3.1–3.4](https://www.mozilla.org/en-US/MPL/2.0/): distributed covered files retain notices/MPL terms; executable distribution requires corresponding covered source availability. | Requirements/lockfile/inventory references only; no covered implementation, certificate bundle or binary shipped. No additional covered-source obligation identified for this ZIP. |
| @img/sharp-libvips-* 1.3.4 and LGPL-bearing sharp platform/WASM variants | [LGPL 3.0-or-later §§3–4 and incorporated GPL terms](https://spdx.org/licenses/LGPL-3.0-or-later.html): library/combined-work redistribution can require license copies, notices, corresponding source and a compliant relinking/shared-library mechanism. | Optional dependency metadata only; no libvips, sharp native/WASM code or linked executable shipped. No source offer/relinking files identified as required for this source-only artifact. |
| caniuse-lite 1.0.30001815 | [CC BY 4.0 §3 and §4](https://creativecommons.org/licenses/by/4.0/legalcode.en): sharing covered material requires supplied creator/notice attribution, license information and modification indications as applicable. | Lockfile metadata only; browser-support dataset not included. No dataset attribution text is fabricated. |
| TypeScript, @swc/helpers, sharp and other Apache-tagged entries | [Apache 2.0 §4](https://www.apache.org/licenses/LICENSE-2.0): redistributed covered code requires the license, retained pertinent notices, applicable NOTICE content and modification notices. | No compiler/helper/native implementation or compiled output shipped. TypeScript imports in tests reference installed packages, not copied implementations. |
| Next.js, React/React DOM, Tailwind and other MIT-tagged dependencies | [MIT](https://spdx.org/licenses/MIT.html): copyright/permission notices accompany copies or substantial portions. | Imports/config/lockfile references only. No framework runtime or font/icon packages are vendored. |
| BSD/PSF and unknown Python metadata entries | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html), [Python license history](https://docs.python.org/3/license.html): retain applicable notices/disclaimers when redistributing covered materials; unknown metadata is not permission. | External packages absent; unknown metadata remains accurately marked NOT DECLARED, not guessed or silently relicensed. |

Future node_modules, wheels, executables, browser bundles, containers, fonts or
upstream datasets require a fresh review of exact included versions/files and
full upstream notices/source obligations. A public source repository does not
pre-clear those future artifacts. All dependencies keep their own licenses.

## Remaining actions and boundaries

No identified shipped file is awaiting another copyright holder/source permission.
If a specific copied item or conflicting notice is later discovered, stop and
reopen this review for that exact path; do not remove it silently. Owner attestations
do not erase third-party rights. The project MIT license and existing attribution
records remain intact. No blanket transitive-license compatibility claim is made.

Separate GitHub publication authorization is still required. Real repository/video
URLs and hackathon eligibility/submission review are outside this source-rights gate.
No Git initialization, repository creation, commit, push, deployment or submission
was performed. Runtime and dependency versions remain unchanged.

## Verification scope

Baseline before this update: 84 files, 83 payload hashes; ZIP SHA-256
`d197b110655c5ab4338438f18dc8e83ec7504ce86440fab543a5b652d389820d`.
This ZIP and checksum are preserved as `.license-d197b110655c.zip` and its receipt.
Earlier candidate and audited archives remain preserved. The current manifest
covers every payload except itself; the current ZIP hash is recorded separately
in `.zip.sha256`. Packaging checks verify exact file sets/bytes, safe extraction,
no symlinks/private artifacts and deterministic double-build output. No runtime
tests or dependency installations are needed for these documentation-only changes.

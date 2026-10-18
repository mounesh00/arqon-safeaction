# Owner-only GitHub publication guide

Preparation only. The standard MIT header is finalized for **Mounesh H Pattar**.
Authorship, third-party rights/notices and redistribution obligations are **not
legally verified**. FINAL_RIGHTS_REVIEW.md records owner attestations and a completed source-only
notice review. Separately authorize publication before executing the commands below.
No repository creation, Git initialization, commit or push was performed here.

The intended new public repository is **arqon-safeaction** under the account
currently authenticated by GitHub CLI. Select a different authorized account
before proceeding if needed. Git, GitHub CLI and existing secure GitHub
credentials are prerequisites; no dependency/tool installation is performed.

## Exact standalone publication commands — do not run until authorized

```sh
cd /path/to/arqon-safeaction-submission
test ! -e .git || { echo 'STOP: inspect existing Git history/remotes'; exit 1; }
shasum -a 256 -c RELEASE_MANIFEST.sha256
python3 - <<'PYCODE'
from pathlib import Path
text = Path('LICENSE').read_text()
assert text.startswith('MIT License\n\nCopyright (c) 2026 Mounesh H Pattar\n')
PYCODE
# The check above validates text only, not legal rights or publication authorization.
git init --initial-branch=main
git status --short
git add --dry-run .
git status --ignored --short
# Review candidate files, screenshots and all unresolved rights/notices privately.
git add .
git diff --cached --name-status
git diff --cached --check
git diff --cached --stat
# Stop here if unexpected content or a rights/secret concern remains.
git commit -m "Initial Arqon SafeAction local prototype"
GITHUB_OWNER="$(gh api user --jq .login)"
gh repo create "$GITHUB_OWNER/arqon-safeaction" --public --source=. --remote=origin
git push --set-upstream origin main
```

If a repository already exists, STOP instead of overwriting remotes/history or
creating an unintended destination. Never put a token in a URL/command. Do not
publish the parent Companies directory, original Architect-VAPT source, preserved
archives or private audit reports. Existing .gitignore excludes environments,
secrets, databases, caches, build output, logs and ZIPs; inspect staged contents
privately because ignore rules do not remove tracked files. Review synthetic
screenshots and any secret-scanner findings before committing. Git identity must
already be configured by the owner; no fabricated identity is supplied.

After authorized publication verify the actual repository, LICENSE, README links,
notices, screenshots and source inventory. Only then replace the public repository
placeholder in AMAZON_SUBMISSION.md. Record/review the real video and verify
current official hackathon requirements before any separately authorized Devpost
submission. No website deployment is part of these commands.

If a secret is exposed, stop publication and revoke/rotate it at its issuer;
deleting a visible file alone does not invalidate the credential or copies.
Coordinate owner-authorized remediation privately. No secret rotation, contacting
third parties or destructive history changes are performed by this guide.

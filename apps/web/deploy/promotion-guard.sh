#!/usr/bin/env bash
# Usage: apps/web/deploy/promotion-guard.sh <commit sha>
# Andon at promotion (C6, D-363): the site's image is built only for a commit of main whose newest full-suite run
# succeeded. build-image.sh runs this first when BUILD_SHA is set (the CodeBuild project open-university-web), so a
# confirmed red on main stops the release without holding the merge queue. It reads the public check runs of the
# commit (anonymously, or with GITHUB_TOKEN when the caller has one) and asks scripts/workflow-attest
# promotion-health. It does not wait (no polling): a suite still running ends the build with "not decided yet", and the Torre starts the release after the suite is green. A flake is
# cleared by re-running the full-suite workflow on that commit; its newer run then decides.
# Exit: 0 green; 1 red, not decided, or the check runs unreadable (fail closed: an anonymous read past GitHub's
# per-address limit refuses the release, which the Torre starts again later; production is untouched either way).
set -euo pipefail
sha="${1:?usage: $0 <commit sha>}"
root="$(cd "$(dirname "$0")/../../.." && pwd)"
repo="${PROMOTION_REPO:-openuniversity-si/open-university}"
checks="$(mktemp)"
trap 'rm -f "$checks"' EXIT
url="https://api.github.com/repos/${repo}/commits/${sha}/check-runs?check_name=full-suite&filter=all&per_page=100"
auth=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then auth=(-H "Authorization: Bearer ${GITHUB_TOKEN}"); fi
if ! curl -fsS --retry 2 --max-time 20 "${auth[@]}" -H 'Accept: application/vnd.github+json' "$url" > "$checks"; then
  echo "promotion-guard: the check runs of ${sha} could not be read; not promoting (fail closed)" >&2
  exit 1
fi
set +e
bash "$root/scripts/workflow-attest" promotion-health --checks "$checks" --sha "$sha"
code=$?
set -e
if [[ $code -ne 0 ]]; then
  echo "promotion-guard: ${sha} is not promoted (D-363)" >&2
  exit 1
fi

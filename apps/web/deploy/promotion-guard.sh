#!/usr/bin/env bash
# Usage: apps/web/deploy/promotion-guard.sh <commit sha>
# Andon at promotion (C6, D-363, D-364): a commit of main is released to the site only when its newest full-suite run
# succeeded. The Torre runs this before it starts the CodeBuild project open-university-web, with GITHUB_TOKEN from its
# own GitHub login, and starts the build only on exit 0:
#   GITHUB_TOKEN="$(gh auth token)" apps/web/deploy/promotion-guard.sh <sha> && aws codebuild start-build ... SRC_SHA=<sha>
# It does not run inside the build (D-364): CodeBuild's shared addresses exhaust GitHub's anonymous limit, so the read
# failed closed on every release, and whoever may start a build may also override its buildspec, so the start-build
# permission is the boundary either way. The merge queue is never consulted. It does not wait (no polling): a suite
# still running is "not decided yet". A flake is cleared by re-running the full-suite workflow on that commit.
# Exit: 0 green; 1 red, not decided, or the check runs unreadable (fail closed).
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

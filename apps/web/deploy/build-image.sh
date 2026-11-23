#!/usr/bin/env bash
# Usage: apps/web/deploy/build-image.sh <image repository> <tag>...
# Builds the Lambda image of Open University's site from this checkout (D-319): installs apps/web with its frozen
# lockfile, runs its production build (which reads the build environment the caller exports: the database URL for the
# catalog bake, SITE_ENV, SITE_URL...), assembles the Docker context from the standalone output and builds one image
# with every tag given. It pushes nothing; the caller (the CodeBuild project open-university-web) pushes the tags.
# BUILD_SHA, when set, is the commit the site shows; the caller sets it to the commit it checked out, and the build
# refuses it unless its full-suite is green (deploy/promotion-guard.sh, D-363).
set -euo pipefail
[[ $# -ge 2 ]] || { echo "usage: $0 <image repository> <tag>..." >&2; exit 2; }
image="$1"; shift
web="$(cd "$(dirname "$0")/.." && pwd)"
ctx="$(mktemp -d)"
trap 'rm -rf "$ctx"' EXIT
export NEXT_PRIVATE_STANDALONE=true NEXT_TELEMETRY_DISABLED=1
# Andon at promotion (D-363): a release (BUILD_SHA set) builds only a commit whose full-suite is green; a local build
# without BUILD_SHA is no promotion and skips it.
if [[ -n "${BUILD_SHA:-}" ]]; then bash "$web/deploy/promotion-guard.sh" "$BUILD_SHA"; fi
(cd "$web" && node -v && pnpm install --frozen-lockfile)
# Next stops its first build on a known-vulnerability notice and asks for the same command again; only that stop is
# retried, once (the upgrade of Next is a change of its own). Any other failure ends the build.
log="$ctx/build.log"
if ! (cd "$web" && pnpm build 2>&1 | tee "$log"); then  # pipefail: the status is the build's
  grep -q 'SecurityFatalError' "$log" || exit 1
  (cd "$web" && pnpm build)
fi
mkdir -p "$ctx/out"
cp -a "$web/.next/standalone" "$ctx/out/standalone"
cp -a "$web/.next/static" "$ctx/out/static"
cp -a "$web/public" "$ctx/out/public"
test -f "$ctx/out/standalone/server.js" || { echo "build-image: no server.js at the standalone root" >&2; exit 1; }
cp "$web/deploy/Dockerfile" "$ctx/Dockerfile"
tags=()
for tag in "$@"; do tags+=(-t "$image:$tag"); done
docker build "${tags[@]}" "$ctx"

#!/usr/bin/env bash
# The tree secret scan (secret_tree) on a real repository: ignored build artifacts never hide a dirty or untracked source secret.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# Use the real scanner (no base: the whole tree). Ignored build artifacts must not hide a dirty or untracked source secret.
mkdir -p "$work/repo/.next"
git -C "$work/repo" init -q
cp "$root/.gitleaks.toml" "$work/repo/.gitleaks.toml"
printf '.next/\n' >"$work/repo/.gitignore"
printf 'export const safe = true;\n' >"$work/repo/source.ts"
git -C "$work/repo" add .
token="ghp_$(python3 -c 'import secrets; print(secrets.token_hex(18))')"
printf 'token = "%s"\n' "$token" >"$work/repo/.next/generated.txt"
rc=0; (cd "$work/repo" && secret_tree "" "") >"$work/scan" 2>&1 || rc=$?
check "generated Next secrets do not break a consecutive run" test "$rc" = 0
printf 'token = "%s"\n' "$token" >"$work/repo/untracked.ts"
rc=0; (cd "$work/repo" && secret_tree "" "") >"$work/scan" 2>&1 || rc=$?
check "untracked source secrets fail" test "$rc" != 0
printf 'token = "%s"\n' "$token" >"$work/repo/source.ts"
rm "$work/repo/untracked.ts"
rc=0; (cd "$work/repo" && secret_tree "" "") >"$work/scan" 2>&1 || rc=$?
check "dirty tracked source secrets fail" test "$rc" != 0
no_leak() { ! grep -qF "$token" "$work/scan"; }
check "scanner output is redacted" no_leak
check_done

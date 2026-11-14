#!/bin/sh
# D-222 (5), called from the pre-commit hook: regenerate the committed derived files that this commit's sources feed, and stage them with the commit
# (scripts/generate --changed --stdin, scripts/lib/generate.py). Only staged paths count, fed on stdin; a commit touching no source runs nothing.
# A generation error refuses the commit (exit 1), so a derived file never lags its source.
root="$(cd "$(dirname "$0")/../.." && pwd)"
gen="$root/scripts/generate"
[ -x "$gen" ] || exit 0
command -v "${OU_PYTHON:-python3}" >/dev/null 2>&1 || exit 0
changed="$(git diff --cached --name-only --diff-filter=ACMR)"
[ -n "$changed" ] || exit 0
written="$(printf '%s\n' "$changed" | "$gen" --changed --stdin)" || {
  echo "pre-commit: regenerating the derived files failed (scripts/generate --changed); the commit is refused" >&2
  exit 1
}
[ -n "$written" ] || exit 0
printf '%s\n' "$written" | while IFS= read -r path; do
  git add -- "$root/$path"
done
exit 0

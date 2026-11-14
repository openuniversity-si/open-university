#!/usr/bin/env bash
# shellcheck disable=SC2154  # _ou_cloud_* are assigned by the registry read below
# Idempotent toolchain for the engine's gate and train (OU-DECOUPLE F5 (D-113): the delivery tail left). No Docker and no apt.
# The same steps run for the current user, including uid 0.
# Language runtimes, CLIs and PostgreSQL come from scripts/cloud/toolchain.json into .toolchain/.
# The host supplies a shell, curl, tar, xz, sha256sum, flock, git and Python >= 3.9 to bootstrap.
# Chromium's system libraries are not installed here: preflight names each one that is missing.
# Prints versions only; never secrets.
set -euo pipefail
# BUNDLE-ENV-LEAK: a runner booted from a code bundle (IMAGE-PREWARM-B1) ran with PYTHONSAFEPATH=1 and the bundle first on
# PYTHONPATH, and passed them to the checks: `python scripts/lib/x.py` lost its own directory (ModuleNotFoundError) and the
# tests imported the bundle's tower_infra. The head's checks run the head's code: drop both here.
if [[ -n "${TOWER_CODE_LOADED:-}" ]]; then
  unset PYTHONSAFEPATH
  PYTHONPATH="$(printf '%s' "${PYTHONPATH:-}" | tr ':' '\n' | grep -vxF "$TOWER_CODE_LOADED" | paste -sd: -)" || PYTHONPATH=""
  if [[ -n "$PYTHONPATH" ]]; then export PYTHONPATH; else unset PYTHONPATH; fi
fi

# shellcheck source=scripts/cloud/root-session.sh
source "$(cd "$(dirname "$0")" && pwd)/root-session.sh"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# An environment refusal: its one line on stderr, exit 2.
refuse() {
  echo "$1" >&2
  exit 2
}

missing() {
  refuse "missing host tool: $1"
}

for tool in curl tar xz sha256sum flock git; do
  command -v "$tool" >/dev/null 2>&1 || missing "$tool"
done

# D-068: the oldest bootstrap Python is a registry entry, read by the candidate itself (config.py is standard library
# only), so a host Python that is too old to read it is refused the same way as one that is too old to run the installer.
python_ok() {
  "$1" -c '
import sys
sys.path.insert(0, sys.argv[1])
import config
raise SystemExit(0 if sys.version_info >= tuple(config.get("cloud.bootstrap_python_minimum")) else 1)
' "$ROOT/scripts/lib" >/dev/null 2>&1
}
# The host's own Python first, where a system or an official python image puts it (/usr/bin, and /usr/local/bin in the
# runner's image on AWS, 04/11), then PATH's: a PATH python3 can be a test's shim or a session's wrapper.
bootstrap=""
for candidate in /usr/bin/python3 /usr/local/bin/python3; do
  if [[ -x "$candidate" ]] && python_ok "$candidate"; then
    bootstrap="$candidate"
    break
  fi
done
if [[ -z "$bootstrap" ]]; then
  if command -v python3 >/dev/null 2>&1 && python_ok python3; then
    bootstrap=python3
  else
    missing python3
  fi
fi

# The other settings of this script, read once through the registry (variables _ou_cloud_<key>). A failed read is one
# FAIL env: line with config.py's reason and a refusal (NANO-UNBLOCK, as in env.sh), never an unset variable below.
settings=(cloud.setup_lock_path cloud.setup_log_path cloud.setup_log_tail_lines cloud.postgres_host cloud.postgres_port)
failed="FAIL env: scripts/cloud/setup.sh cannot read ${settings[*]} from the registry"
found="$("$bootstrap" "$ROOT/scripts/lib/config.py" get "${settings[@]}" 2>&1)" || refuse "$failed: ${found##*$'\n'}"
# config.py answers on its last line (one JSON document); a line above it came from its stderr and is passed on.
assignments="$(printf '%s\n' "${found##*$'\n'}" | "$bootstrap" -c '
import json, shlex, sys
try:
    found = json.load(sys.stdin)
except ValueError:
    raise SystemExit(1)
for name, value in found.items():
    print("_ou_" + name.replace(".", "_") + "=" + shlex.quote(str(value)))
')" || refuse "$failed: config.py did not answer with JSON"
[[ "$found" != *$'\n'* ]] || printf '%s\n' "${found%$'\n'*}" >&2
eval "$assignments"
LOG="$_ou_cloud_setup_log_path"
# CHECK-USER-SHARED: the runner's uid 0 and the check user (tower-check) run this on one task; a /tmp log another uid made
# is not this one's to truncate (0644, and O_CREAT on another user's file in sticky /tmp is refused under
# fs.protected_regular, root included): this uid writes its own beside it.
if [[ -e "$LOG" && ! -O "$LOG" ]]; then
  LOG="${LOG%.log}.$(id -u).log"
fi

# A /tmp lock is shared by the session uid and uid 0. Create it only when it
# is absent: O_CREAT on another user's file in sticky /tmp is rejected
# (fs.protected_regular) even at mode 0666. The held descriptor is read-only.
setup_lock="$_ou_cloud_setup_lock_path"
if [[ ! -e "$setup_lock" ]] && ! : >>"$setup_lock"; then
  echo "missing writable path: $(dirname "$setup_lock")" >&2
  exit 2
fi
if [[ ${EUID} -eq 0 || -O "$setup_lock" ]]; then
  chmod 666 "$setup_lock" 2>/dev/null || true
fi
if ! mkdir -p "$ROOT/.toolchain" || ! : >>"$ROOT/.toolchain/.write-probe"; then
  echo "missing writable path: .toolchain" >&2
  exit 2
fi
rm -f "$ROOT/.toolchain/.write-probe"

: >"$LOG"
if ! exec 8<"$setup_lock"; then
  echo "missing writable path: $(dirname "$setup_lock")" >&2
  exit 2
fi
flock 8

run_quiet() {
  if ! "$@" >>"$LOG" 2>&1; then
    echo "FAIL: $1" >&2
    tail -n "$_ou_cloud_setup_log_tail_lines" "$LOG" >&2 || true
    exit 1
  fi
}

run_quiet "$bootstrap" "$ROOT/scripts/cloud/toolchain.py" install
# shellcheck source=scripts/cloud/env.sh
source "$ROOT/scripts/cloud/env.sh"
hash -r

# postgres.py prints the exact problem on stderr. stdout is the ready line, kept in the log.
if ! "$OU_PYTHON" "$ROOT/scripts/cloud/postgres.py" ensure >>"$LOG"; then
  exit 1
fi
# Probe the maintenance database: on a fresh machine this checkout's own database does not exist yet.
if ! psql "${TEST_DATABASE_URL%/*}/postgres" -qtAc 'select 1' >>"$LOG" 2>&1; then
  echo "FAIL: postgres is not accepting connections on $_ou_cloud_postgres_host:${OU_POSTGRES_PORT:-$_ou_cloud_postgres_port}" >&2
  exit 1
fi
# GX-29: the cluster holds throwaway data; durability off keeps CREATE/DROP DATABASE checkpoints short under a loaded gate.
while IFS= read -r pg_setting; do
  psql "${TEST_DATABASE_URL%/*}/postgres" -qtAc "alter system set ${pg_setting%%=*} = '${pg_setting#*=}'" >>"$LOG" 2>&1 || true
done < <("$OU_PYTHON" -c '
import sys
sys.path.insert(0, sys.argv[1])
import config
print("\n".join(config.get("cloud.postgres_test_settings")))
' "$ROOT/scripts/lib")
psql "${TEST_DATABASE_URL%/*}/postgres" -qtAc 'select pg_reload_conf()' >>"$LOG" 2>&1 || true
# D-064 (b): this checkout's own test database (tower_test_<hash of the path>), created before first use.
ou_test_db_ensure "${TEST_DATABASE_URL:-}" || exit 1
if ! psql "$TEST_DATABASE_URL" -qtAc 'select 1' >>"$LOG" 2>&1; then
  echo "FAIL: local test database ${TEST_DATABASE_URL##*/} does not answer" >&2
  exit 1
fi

if [[ ${EUID} -eq 0 && -n "${GATE_CHECKOUT_ROOT:-}" ]]; then
  # Every directory from / down to the slot checkouts must be traversable by an unprivileged uid.
  # Only the directories created here (root's umask may be 077) and the checkout root itself get 0755.
  # A pre-existing ancestor stays as it is and is named when it blocks.
  gate_dir="$GATE_CHECKOUT_ROOT"
  gate_new=("$gate_dir")
  while [[ ! -e "$(dirname "$gate_dir")" ]]; do
    gate_dir="$(dirname "$gate_dir")"
    gate_new+=("$gate_dir")
  done
  mkdir -p "$GATE_CHECKOUT_ROOT"
  chmod 755 "${gate_new[@]}"
  gate_dir="$GATE_CHECKOUT_ROOT"
  while [[ "$gate_dir" != / ]]; do
    if (( (8#$(stat -c %a "$gate_dir") & 1) == 0 )); then
      echo "WARN: $gate_dir is not traversable by other uids; script tests that drop root will fail" >&2
    fi
    gate_dir="$(dirname "$gate_dir")"
  done
fi

# OU-DECOUPLE F4 (D-111): no web package here. The product install and its offline seeds (Playwright browsers, the
# pnpm store, the media cache, the Inter font tooling) left with Open University, and pnpm itself left the toolchain
# (vazão F16, D-292).

if [[ "$(git -C "$ROOT" rev-parse --is-shallow-repository)" == true ]]; then
  run_quiet git -C "$ROOT" fetch --unshallow origin
fi

# Daniel 04/11 16:57 BRT: this checkout's origin is Origin, and git signs in to it through the origin CLI (I-4257299c:
# a cloud checkout can come with origin on the archived GitHub repository). After the fetch above, which still reads the
# remote the checkout came with; it never fails the setup, and .githooks/pre-push stays the safety net.
"$OU_PYTHON" "$ROOT/scripts/lib/origin_remote.py" "$ROOT" >>"$LOG" 2>&1 || true

# CENSO-NO-MANIFESTO 3bis: committed generated files (.gitattributes) merge through the regenerate driver.
run_quiet "$OU_PYTHON" "$ROOT/scripts/lib/merge_regenerate.py" install --root "$ROOT"

if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
  {
    # $PATH stays literal: the next shell prepends the toolchain to whatever PATH it has.
    # shellcheck disable=SC2016
    printf 'export PATH="%s:$PATH"\n' "$ROOT/.toolchain/bin"
    printf 'export TEST_DATABASE_URL=%s\n' "$TEST_DATABASE_URL"
    printf 'export APP_DATABASE_URL_CONTAINER_UNPOOLED=%s\n' "$APP_DATABASE_URL_CONTAINER_UNPOOLED"
    if [[ -n "${GATE_CHECKOUT_ROOT:-}" ]]; then
      printf 'export GATE_CHECKOUT_ROOT=%s\n' "$GATE_CHECKOUT_ROOT"
    fi
    ou_node_env_proxy_exports
  } >>"$CLAUDE_ENV_FILE"
fi

# SETUP-PER-HEAD: the versions as the installed binaries report them, each probe kept while its binary keeps its
# identity (toolchain_manifest.observed_versions): `gitleaks version` alone was 0.35 of the 1.2 s of a set-up toolchain
"$OU_PYTHON" - "$ROOT/scripts/lib" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import toolchain_manifest
seen = toolchain_manifest.observed_versions(tools=['node', 'python', 'postgres', 'gitleaks'])
print('the-tower cloud setup: ' + ', '.join(f'{tool} {seen[tool]}' for tool in ('node', 'python', 'postgres', 'gitleaks')))
PY
